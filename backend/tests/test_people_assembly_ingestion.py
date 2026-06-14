"""People's Assembly source-access observability (#47).

Covers structured fetch diagnostics, systemic source-access classification, and
the guarantee that no response body or secret ever appears in the diagnostics.
The unit tests need no network or database; the single service test mirrors
test_app.py and runs against the configured database (Docker).
"""
import sys
from pathlib import Path

import pytest
import requests
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base, SessionLocal, engine
from app.ingestion import people_assembly as pa
from app.models.unresolved_entity import UnresolvedEntity
from app.services.ingestion_service import ingest_people_assembly_profiles
from ingestion_batch_utils import build_result, empty_summary, run_url_batch


class _FakeResponse:
    def __init__(self, status_code=200, text="<html>ok</html>", content_type="text/html",
                 url="https://www.pa.org.za/person/test/"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


@pytest.fixture(autouse=True)
def _clear_fetch_outcomes():
    pa._LAST_FETCH_OUTCOME.clear()
    yield
    pa._LAST_FETCH_OUTCOME.clear()


def _source_access_part(url: str, error_type: str = "HTTPError", message: str = "Source fetch failed from www.pa.org.za: HTTP 403.") -> dict:
    part = empty_summary()
    part["failed_count"] = 1
    part["errors"].append({"url": url, "type": error_type, "error": message})
    return part


def _processed_part() -> dict:
    part = empty_summary()
    part["processed_count"] = 1
    part["created_count"] = 1
    return part


# ---------------------------------------------------------------------------
# Structured fetch diagnostics (no network)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [403, 429, 503])
def test_http_error_captured_as_structured_error(monkeypatch, status):
    url = "https://www.pa.org.za/person/test/"
    monkeypatch.setattr(
        pa.requests, "get",
        lambda *a, **k: _FakeResponse(status_code=status, text="<html>challenge page</html>", url=url),
    )
    outcome = pa.fetch_page_detailed(url)
    assert outcome.ok is False
    assert outcome.error_kind == "http_error"
    assert outcome.status_code == status
    assert outcome.final_domain == "www.pa.org.za"

    error_type, message = pa.describe_fetch_failure(url)
    assert error_type == "HTTPError"
    assert str(status) in message
    assert "www.pa.org.za" in message
    # The response body is never surfaced.
    assert "challenge page" not in message


def test_timeout_captured_as_structured_error(monkeypatch):
    url = "https://www.pa.org.za/person/test/"

    def _raise(*a, **k):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(pa.requests, "get", _raise)
    outcome = pa.fetch_page_detailed(url)
    assert outcome.ok is False
    assert outcome.error_kind == "timeout"
    assert outcome.status_code is None
    assert outcome.final_domain == "www.pa.org.za"

    error_type, message = pa.describe_fetch_failure(url)
    assert error_type == "Timeout"
    assert "timed out" in message.lower()


def test_connection_error_captured_as_structured_error(monkeypatch):
    url = "https://www.pa.org.za/person/test/"

    def _raise(*a, **k):
        raise requests.ConnectionError("name resolution failed")

    monkeypatch.setattr(pa.requests, "get", _raise)
    outcome = pa.fetch_page_detailed(url)
    assert outcome.error_kind == "connection_error"
    assert pa.describe_fetch_failure(url)[0] == "ConnectionError"


def test_empty_body_captured_as_structured_error(monkeypatch):
    url = "https://www.pa.org.za/person/test/"
    monkeypatch.setattr(pa.requests, "get", lambda *a, **k: _FakeResponse(status_code=200, text="", url=url))
    outcome = pa.fetch_page_detailed(url)
    assert outcome.ok is False
    assert outcome.error_kind == "empty_body"
    assert outcome.status_code == 200
    assert pa.describe_fetch_failure(url)[0] == "EmptyResponse"


def test_fetch_page_preserves_string_contract(monkeypatch):
    monkeypatch.setattr(pa.requests, "get", lambda *a, **k: _FakeResponse(text="<html>ok</html>"))
    assert pa.fetch_page("https://www.pa.org.za/ok/") == "<html>ok</html>"
    monkeypatch.setattr(pa.requests, "get", lambda *a, **k: _FakeResponse(status_code=503, text="error"))
    assert pa.fetch_page("https://www.pa.org.za/bad/") == ""


def test_diagnostics_never_leak_credentials_path_or_body(monkeypatch, capsys):
    url = "https://user:hunter2@www.pa.org.za/person/secret-x/?token=abc123"
    monkeypatch.setattr(
        pa.requests, "get",
        lambda *a, **k: _FakeResponse(status_code=403, text="<html>blocked secret-x</html>", url=url),
    )
    outcome = pa.fetch_page_detailed(url)
    _, message = pa.describe_fetch_failure(url)

    # Bare host only — no credentials, no path, no query string, no body.
    assert outcome.final_domain == "www.pa.org.za"
    for leak in ("hunter2", "token=abc123", "secret-x", "blocked secret-x"):
        assert leak not in message
    # The fetch helpers print nothing (no full HTML logged).
    assert capsys.readouterr().out == ""


def test_unknown_failure_falls_back_to_generic_message():
    # No fetch recorded for this URL (e.g. fetch was monkeypatched away).
    error_type, message = pa.describe_fetch_failure("https://www.pa.org.za/person/never-fetched/")
    assert error_type == "SourceAccessError"
    assert message == "Fetch failed or returned empty HTML."


# ---------------------------------------------------------------------------
# Systemic source-access classification (no network)
# ---------------------------------------------------------------------------

def test_all_fetches_failing_marks_systemic_source_access():
    urls = [f"https://www.pa.org.za/person/{i}/" for i in range(6)]
    total, systemic = run_url_batch(urls, lambda url: _source_access_part(url), sleep_seconds=0, retry_attempts=1)
    result = build_result("people_assembly", len(urls), total, systemic)

    assert result["systemic_source_access_failure"] is True
    assert result["failed_fetch_count"] == 6
    assert result["processed_count"] == 0
    assert result["status"] == "failed"
    assert result["top_error_types"] == {"HTTPError": 6}
    assert result["recommendation"]
    assert "non-blocked host" in result["recommendation"]
    assert len(result["sample_safe_errors"]) == 3


def test_partial_fetch_failure_is_not_systemic():
    def ingest(url: str) -> dict:
        return _source_access_part(url) if url.endswith("/bad/") else _processed_part()

    urls = ["https://www.pa.org.za/person/ok/", "https://www.pa.org.za/person/bad/"]
    total, systemic = run_url_batch(urls, ingest, sleep_seconds=0, retry_attempts=1)
    result = build_result("people_assembly", len(urls), total, systemic)

    assert result["systemic_source_access_failure"] is False
    assert result["processed_count"] == 1
    assert result["failed_fetch_count"] == 1
    assert result["status"] == "partial"
    assert result["recommendation"] == ""


def test_all_parse_failures_are_not_source_access():
    # Every URL fails, but as a parse error — not a fetch/access failure.
    def ingest(url: str) -> dict:
        part = empty_summary()
        part["failed_count"] = 1
        part["errors"].append({"url": url, "type": "ValueError", "error": "Could not parse profile"})
        return part

    urls = [f"https://www.pa.org.za/person/{i}/" for i in range(5)]
    total, systemic = run_url_batch(urls, ingest, sleep_seconds=0, retry_attempts=1)
    result = build_result("people_assembly", len(urls), total, systemic)

    assert result["status"] == "failed"
    assert result["systemic_source_access_failure"] is False
    assert result["failed_fetch_count"] == 0


def test_mixed_fetch_and_parse_all_failures_are_not_systemic():
    # Every URL fails (processed == 0), but the failures mix a fetch-access error
    # and a parse error. Because not every failure is a source-access failure,
    # this must NOT be classified systemic (guards the all(...) vs any(...) rule).
    def ingest(url: str) -> dict:
        part = empty_summary()
        part["failed_count"] = 1
        if url.endswith("/0/"):
            part["errors"].append({"url": url, "type": "HTTPError", "error": "HTTP 403 from www.pa.org.za"})
        else:
            part["errors"].append({"url": url, "type": "ValueError", "error": "Could not parse profile"})
        return part

    urls = [f"https://www.pa.org.za/person/{i}/" for i in range(4)]
    total, systemic = run_url_batch(urls, ingest, sleep_seconds=0, retry_attempts=1)
    result = build_result("people_assembly", len(urls), total, systemic)

    assert result["processed_count"] == 0
    assert result["status"] == "failed"
    assert result["systemic_source_access_failure"] is False
    assert result["failed_fetch_count"] == 1  # only the HTTPError counts as a fetch failure


def test_summary_redacts_secrets_in_sample_errors():
    secret_url = "postgresql://admin:super-secret@db/app"
    part = _source_access_part(
        "https://www.pa.org.za/person/x/",
        error_type="HTTPError",
        message=f"connection failed DATABASE_URL={secret_url}",
    )
    result = build_result("people_assembly", 1, part, systemic_failure=False)
    blob = str(result["sample_safe_errors"])
    assert "super-secret" not in blob
    assert "[REDACTED]" in blob


# ---------------------------------------------------------------------------
# Service wiring (database-backed; runs in Docker)
# ---------------------------------------------------------------------------

def test_profile_fetch_failure_records_source_access_typed_error(monkeypatch):
    url = "https://www.pa.org.za/person/blocked-runner/"
    Base.metadata.create_all(bind=engine)

    def fake_fetch(target: str) -> str:
        pa._record(target, pa.FetchOutcome("", False, 403, "http_error", "text/html", "www.pa.org.za"))
        return ""

    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", fake_fetch)
    with SessionLocal() as db:
        summary = ingest_people_assembly_profiles(db, [url])
        leaked = list(db.scalars(select(UnresolvedEntity).where(UnresolvedEntity.source_url == url)))

    assert summary["processed_count"] == 0
    assert summary["failed_count"] == 1
    error = summary["errors"][0]
    assert error["type"] == "HTTPError"
    assert "403" in error["error"]
    assert "www.pa.org.za" in error["error"]
    assert leaked == []
