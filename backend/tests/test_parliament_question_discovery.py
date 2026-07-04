"""Regression tests for docsjson discovery pagination.

The production docsjson endpoint ignores the `page` parameter and repeats
the newest window forever; only `offset` advances the result set (verified
against the live API on 2026-07-04). The pre-fix code paged with `page` and
only broke out of the loop when `limit is None`, so scheduled ingestion
with the new-record-first discovery limit of 1000 hung indefinitely and
was killed by the job timeout (runs 28702236614 and 28708619234).
"""

from app.ingestion import parliament_question_discovery as discovery
from app.ingestion.parliament_question_discovery import discover_docsjson_urls


def _record(n: int) -> dict:
    return {"id": n, "file_location": f"/Docs/question-{n}.pdf", "name": f"RNW{n}", "date": "2026-01-01"}


class _FakeResponse:
    def __init__(self, records):
        self._records = records

    def raise_for_status(self):
        return None

    def json(self):
        return {"records": self._records}


def _install_fake(monkeypatch, handler):
    calls = []

    def fake_get(url, *, params, timeout, headers):
        calls.append(params)
        return _FakeResponse(handler(params))

    monkeypatch.setattr(discovery.requests, "get", fake_get)
    return calls


def test_pagination_uses_offset_and_never_page(monkeypatch):
    def handler(params):
        assert "page" not in params, "docsjson ignores `page`; requests must use `offset`"
        offset = params["offset"]
        if offset >= 100:
            return []
        return [_record(offset + i) for i in range(50)]

    calls = _install_fake(monkeypatch, handler)
    urls = discover_docsjson_urls(limit=1000)

    offsets = [c["offset"] for c in calls if c["queries[type]"] == "EXE_RQ_NA"]
    assert offsets == [0, 50, 100]
    assert len(urls) == 100  # all doc types serve the same records


def test_repeating_source_terminates_quickly(monkeypatch):
    """A source that returns the same window regardless of offset (the real
    pre-fix production behavior) must terminate instead of looping forever."""
    same_window = [_record(i) for i in range(50)]
    calls = _install_fake(monkeypatch, lambda params: same_window)

    urls = discover_docsjson_urls(limit=1000)

    assert len(urls) == 50
    # First doc type: 1 productive batch + 2 stale; remaining doc types: 2 stale each.
    assert len(calls) <= 3 + 3 * 2


def test_limit_short_circuits_discovery(monkeypatch):
    def handler(params):
        offset = params["offset"]
        return [_record(offset + i) for i in range(50)]

    calls = _install_fake(monkeypatch, handler)
    urls = discover_docsjson_urls(limit=75)

    assert len(urls) == 75
    assert len(calls) == 2  # limit hit inside the second window of the first doc type


def test_short_page_ends_doc_type(monkeypatch):
    def handler(params):
        if params["offset"] == 0:
            return [_record(i) for i in range(41)]
        raise AssertionError("must not request past a short page")

    _install_fake(monkeypatch, handler)
    urls = discover_docsjson_urls(limit=1000)
    assert len(urls) == 41


def test_unbounded_discovery_is_still_request_capped(monkeypatch):
    """Even with limit=None, a doc type may consume at most 20 requests."""

    def handler(params):
        offset = params["offset"]
        return [_record(offset + i) for i in range(50)]

    calls = _install_fake(monkeypatch, handler)
    discover_docsjson_urls(limit=None)
    per_type = [c for c in calls if c["queries[type]"] == "EXE_RQ_NA"]
    assert len(per_type) == 20


def test_fetch_error_yields_no_records(monkeypatch):
    def fake_get(url, *, params, timeout, headers):
        raise OSError("boom")

    monkeypatch.setattr(discovery.requests, "get", fake_get)
    assert discover_docsjson_urls(limit=10) == []
