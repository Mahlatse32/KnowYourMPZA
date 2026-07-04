"""Tests for PMG committee meeting coverage recovery (issue #59): sweep
stream selection, the dedicated backfill workflow shape, and resilient
fetch behaviour for the meetings API."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.ingestion.committee_activity import fetch_page

from run_scheduled_sweep import (
    DEFAULT_PAGES_CAP,
    STREAM_SKIP_FLAGS,
    SweepConfigError,
    parse_streams,
    stream_selection_args,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKFILL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pmg-meeting-backfill.yml"
SWEEP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"


# ---------------------------------------------------------------------------
# Stream selection for run_scheduled_sweep --streams
# ---------------------------------------------------------------------------

def test_parse_streams_none_means_all():
    assert parse_streams(None) is None
    assert parse_streams("") is None
    assert parse_streams(" , ") is None


def test_parse_streams_splits_and_strips():
    assert parse_streams("pmg_committee_meetings") == ["pmg_committee_meetings"]
    assert parse_streams(" pmg_bills , pmg_votes_from_meetings ") == [
        "pmg_bills",
        "pmg_votes_from_meetings",
    ]


def test_stream_selection_all_streams_adds_no_skips():
    assert stream_selection_args(None) == []


def test_stream_selection_single_stream_skips_all_others():
    flags = stream_selection_args(["pmg_committee_meetings"])
    assert "--skip-committee-meeting-sweep" not in flags
    assert set(flags) == {
        "--skip-bill-sweep",
        "--skip-bill-lifecycle-sweep",
        "--skip-vote-sweep",
    }


def test_stream_selection_multiple_streams():
    flags = stream_selection_args(["pmg_bills", "pmg_committee_meetings"])
    assert set(flags) == {"--skip-bill-lifecycle-sweep", "--skip-vote-sweep"}


def test_stream_selection_rejects_unknown_stream():
    with pytest.raises(SweepConfigError, match="Unknown sweep stream"):
        stream_selection_args(["pmg_committee_meetings", "not_a_stream"])


def test_stream_skip_flags_cover_known_streams():
    """Every stream the sweep service knows must be selectable."""
    from app.services.sweep_service import KNOWN_STREAMS

    assert set(STREAM_SKIP_FLAGS) == set(KNOWN_STREAMS)


# ---------------------------------------------------------------------------
# Backfill workflow shape (mirrors the accountability-sweep workflow tests)
# ---------------------------------------------------------------------------

def test_backfill_workflow_file_exists():
    assert BACKFILL_WORKFLOW.exists(), "pmg-meeting-backfill workflow file missing"


def test_backfill_workflow_has_manual_dispatch_and_inputs():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "pages_per_run" in text
    assert "dry_run" in text


def test_backfill_workflow_has_schedule():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron:" in text


def test_backfill_workflow_shares_sweep_concurrency_group():
    """The backfill must never run concurrently with the daily sweep — both
    advance the same durable cursor rows."""
    backfill = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    sweep = SWEEP_WORKFLOW.read_text(encoding="utf-8")

    def concurrency_group(text: str) -> str:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "concurrency:":
                return lines[i + 1].split(":", 1)[1].strip()
        raise AssertionError("workflow has no concurrency block")

    assert concurrency_group(backfill) == concurrency_group(sweep)
    assert "cancel-in-progress: false" in backfill


def test_backfill_workflow_has_timeout():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "timeout-minutes: 90" in text


def test_backfill_workflow_targets_only_meetings_stream():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "--streams pmg_committee_meetings" in text


def test_backfill_workflow_default_pages_within_safety_cap():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert f"|| '{DEFAULT_PAGES_CAP}'" in text
    assert "--allow-large-batch" not in text


def test_backfill_workflow_never_echoes_database_url():
    """No line may print the database URL (it can contain credentials)."""
    for line in BACKFILL_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "echo" in line and "DATABASE_URL=" in line:
            # writing to $GITHUB_ENV is the only permitted use
            assert "GITHUB_ENV" in line, f"workflow prints DATABASE_URL: {line.strip()}"


def test_backfill_workflow_uses_secret_for_real_mode():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.DATABASE_URL" in text
    assert "SWEEP_DB_PERSISTENT" in text


def test_backfill_workflow_uploads_artifacts():
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact" in text
    assert "backend/reports/" in text


def test_backfill_workflow_generates_v1_readiness_artifacts_before_upload():
    """Every backfill run must ship the consolidated V1 readiness report
    (PR #62) alongside the sweep artifacts, built from the same run's
    inspect_db and dashboard outputs, and must never block the sweep."""
    text = BACKFILL_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/report_v1_readiness.py --reports-dir reports || true" in text

    inspect = text.find("scripts/inspect_db.py")
    dashboard = text.find("report_data_coverage_dashboard.py")
    readiness = text.find("report_v1_readiness.py")
    upload = text.find("actions/upload-artifact")
    assert -1 < inspect < dashboard < readiness < upload


# ---------------------------------------------------------------------------
# Resilient fetch for the meetings API (same contract as bills.fetch_page)
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, status_code=200, text='{"ok": true}'):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error


def test_fetch_page_retries_transient_timeout(monkeypatch):
    calls = []
    sleeps = []

    def get(url, *, timeout, headers):
        calls.append({"url": url, "timeout": timeout, "headers": headers})
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return _Response()

    monkeypatch.setattr("app.ingestion.committee_activity.requests.get", get)
    monkeypatch.setattr("app.ingestion.committee_activity.time.sleep", lambda delay: sleeps.append(delay))

    assert fetch_page("https://api.pmg.org.za/committee-meeting/?page=1") == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["timeout"] == 45
    assert sleeps == [1.0]


def test_fetch_page_backoff_is_exponential(monkeypatch):
    calls = []
    sleeps = []

    def get(url, *, timeout, headers):
        calls.append(url)
        if len(calls) < 3:
            raise requests.ConnectionError("reset")
        return _Response()

    monkeypatch.setattr("app.ingestion.committee_activity.requests.get", get)
    monkeypatch.setattr("app.ingestion.committee_activity.time.sleep", lambda delay: sleeps.append(delay))

    assert fetch_page("https://api.pmg.org.za/committee-meeting/?page=1") == '{"ok": true}'
    assert sleeps == [1.0, 2.0]


def test_fetch_page_retries_retryable_http_errors(monkeypatch):
    calls = []
    sleeps = []

    def get(url, *, timeout, headers):
        calls.append(url)
        if len(calls) == 1:
            return _Response(status_code=503)
        return _Response()

    monkeypatch.setattr("app.ingestion.committee_activity.requests.get", get)
    monkeypatch.setattr("app.ingestion.committee_activity.time.sleep", lambda delay: sleeps.append(delay))

    assert fetch_page("https://api.pmg.org.za/committee-meeting/?page=1") == '{"ok": true}'
    assert len(calls) == 2


def test_fetch_page_does_not_retry_permanent_http_errors(monkeypatch):
    calls = []

    def get(url, *, timeout, headers):
        calls.append(url)
        return _Response(status_code=404)

    monkeypatch.setattr("app.ingestion.committee_activity.requests.get", get)
    monkeypatch.setattr(
        "app.ingestion.committee_activity.time.sleep",
        lambda delay: pytest.fail("must not sleep for a non-retryable error"),
    )

    with pytest.raises(requests.HTTPError):
        fetch_page("https://api.pmg.org.za/committee-meeting/?page=1")
    assert len(calls) == 1


def test_fetch_page_gives_up_after_bounded_retries(monkeypatch):
    calls = []
    sleeps = []

    def get(url, *, timeout, headers):
        calls.append(url)
        raise requests.Timeout("slow")

    monkeypatch.setattr("app.ingestion.committee_activity.requests.get", get)
    monkeypatch.setattr("app.ingestion.committee_activity.time.sleep", lambda delay: sleeps.append(delay))

    with pytest.raises(requests.Timeout):
        fetch_page("https://api.pmg.org.za/committee-meeting/?page=1")
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
