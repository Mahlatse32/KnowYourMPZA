"""Tests for the scheduled accountability sweep: workflow shape, safety
guards, report writer, and JSON output integrity."""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base

from run_scheduled_sweep import (
    DEFAULT_PAGES_CAP,
    SweepConfigError,
    build_report,
    parse_stage_summaries,
    recommend_next_batch,
    render_markdown,
    validate_sweep_config,
    write_report_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Workflow file shape
# ---------------------------------------------------------------------------

def test_workflow_file_exists():
    assert WORKFLOW.exists(), "accountability-sweep workflow file missing"


def test_workflow_has_manual_dispatch_and_inputs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "pages_per_run" in text
    assert "dry_run" in text


def test_workflow_has_schedule():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron:" in text


def test_workflow_has_concurrency_protection():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text


def test_workflow_has_timeout():
    assert "timeout-minutes:" in WORKFLOW.read_text(encoding="utf-8")


def test_workflow_uploads_artifacts():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact" in text
    assert "backend/reports/" in text


def test_workflow_never_echoes_database_url():
    """No line may print the database URL (it can contain credentials)."""
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "echo" in line and "DATABASE_URL=" in line:
            # writing to $GITHUB_ENV is the only permitted use
            assert "GITHUB_ENV" in line, f"workflow prints DATABASE_URL: {line.strip()}"


def test_workflow_uses_secret_for_real_mode():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.DATABASE_URL" in text
    assert "SWEEP_DB_PERSISTENT" in text


# ---------------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------------

def _config(**overrides):
    base = dict(
        pages_per_run=3,
        dry_run=False,
        database_url="postgresql://persistent",
        db_persistent=True,
        allow_large_batch=False,
    )
    base.update(overrides)
    return base


def test_guard_accepts_valid_real_run():
    validate_sweep_config(**_config())


def test_guard_requires_pages_per_run():
    with pytest.raises(SweepConfigError, match="pages_per_run is required"):
        validate_sweep_config(**_config(pages_per_run=None))


def test_guard_rejects_nonpositive_pages():
    with pytest.raises(SweepConfigError):
        validate_sweep_config(**_config(pages_per_run=0))


def test_guard_caps_pages_per_run():
    with pytest.raises(SweepConfigError, match="safety cap"):
        validate_sweep_config(**_config(pages_per_run=DEFAULT_PAGES_CAP + 1))
    # explicit override allows it
    validate_sweep_config(**_config(pages_per_run=DEFAULT_PAGES_CAP + 1, allow_large_batch=True))


def test_guard_real_run_requires_database_url():
    with pytest.raises(SweepConfigError, match="DATABASE_URL is not set"):
        validate_sweep_config(**_config(database_url=None))


def test_guard_real_run_requires_persistent_db():
    with pytest.raises(SweepConfigError, match="not marked persistent"):
        validate_sweep_config(**_config(db_persistent=False))


def test_guard_dry_run_allowed_without_persistent_db():
    validate_sweep_config(**_config(dry_run=True, database_url=None, db_persistent=False))


def test_guard_messages_never_contain_secrets():
    secret_url = "postgresql://user:hunter2@db.example.com/prod"
    try:
        validate_sweep_config(**_config(database_url=secret_url, db_persistent=False))
    except SweepConfigError as exc:
        assert "hunter2" not in str(exc)
        assert secret_url not in str(exc)


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

SAMPLE_STAGE = {
    "pages_attempted": 2, "processed": 100, "created": 70, "updated": 30, "failed": 0,
    "errors": [], "end_reached": False, "source_total": 1246,
    "sweep": {"stream_name": "pmg_bills", "next_page": 2, "advanced": True},
}

SAMPLE_STATES = [
    {"source_name": "PMG", "stream_name": "pmg_bills", "cursor_type": "page", "next_page": 2,
     "source_total": 1246, "total_seen": 100, "total_created": 70, "total_updated": 30,
     "total_failed": 0, "sweeps_completed": 0, "last_status": "completed",
     "last_started_at": None, "last_completed_at": None, "last_error": None},
    {"source_name": "PMG", "stream_name": "pmg_committee_meetings", "cursor_type": "page", "next_page": 2,
     "source_total": 34648, "total_seen": 100, "total_created": 79, "total_updated": 21,
     "total_failed": 0, "sweeps_completed": 0, "last_status": "completed",
     "last_started_at": None, "last_completed_at": None, "last_error": None},
]


def _report(**overrides):
    base = dict(
        timestamp="2026-06-12T10:00:00+00:00",
        command=["run_full_ingestion.py", "--accountability-sweep", "--pages-per-run", "3"],
        mode="real",
        pages_per_run=3,
        counts_before={"bills": 20, "bill_events": 47, "vote_events": 2, "vote_records": 0,
                       "committee_meetings": 20, "committee_attendance": 174},
        counts_after={"bills": 90, "bill_events": 359, "vote_events": 9, "vote_records": 0,
                      "committee_meetings": 99, "committee_attendance": 1029},
        stage_summaries=[SAMPLE_STAGE],
        sweep_states=SAMPLE_STATES,
        exit_code=0,
    )
    base.update(overrides)
    return build_report(**base)


def test_report_writer_produces_json_and_markdown(tmp_path):
    json_path, md_path = write_report_files(_report(), tmp_path)
    assert json_path.exists() and md_path.exists()
    blob = json.loads(json_path.read_text(encoding="utf-8"))
    assert blob["mode"] == "real"
    md = md_path.read_text(encoding="utf-8")
    assert "# Accountability Sweep Report" in md


def test_report_includes_sweep_states():
    report = _report()
    streams = {s["stream_name"] for s in report["sweep_states"]}
    assert {"pmg_bills", "pmg_committee_meetings"} <= streams
    md = render_markdown(report)
    assert "pmg_committee_meetings" in md


def test_report_includes_before_after_counts_and_delta():
    report = _report()
    assert report["counts_delta"]["bills"] == 70
    assert report["counts_delta"]["committee_attendance"] == 855
    md = render_markdown(report)
    assert "| bills | 20 | 90 | 70 |" in md


def test_report_handles_unavailable_counts():
    report = _report(counts_before=None, counts_after=None)
    assert report["counts_delta"] is None
    render_markdown(report)  # must not raise


def test_report_estimates_meeting_coverage():
    report = _report()
    assert report["estimated_meeting_coverage_percent"] == round(99 / 34648 * 100, 2)


def test_report_includes_source_totals():
    report = _report()
    assert report["source_totals"]["pmg_bills"] == 1246
    assert report["source_totals"]["pmg_committee_meetings"] == 34648


def test_report_collects_stage_errors():
    bad_stage = {**SAMPLE_STAGE, "failed": 1,
                 "errors": [{"url": "https://api.pmg.org.za/bill/?page=9", "error": "HTTP 502", "type": "HTTPError"}]}
    report = _report(stage_summaries=[bad_stage])
    assert report["errors"][0]["type"] == "HTTPError"
    md = render_markdown(report)
    assert "HTTP 502" in md


def test_report_json_stays_parseable(tmp_path):
    json_path, _ = write_report_files(_report(), tmp_path)
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(parsed["stage_summaries"], list)
    assert isinstance(parsed["sweep_states"], list)


def test_next_batch_recommendation():
    assert "scale" in recommend_next_batch([SAMPLE_STAGE], 3).lower()
    failed_stage = {**SAMPLE_STAGE, "failed": 2}
    assert "Stay at" in recommend_next_batch([failed_stage], 3)
    assert "steady state" in recommend_next_batch([SAMPLE_STAGE], 6)


def test_parse_stage_summaries_extracts_json_lines():
    stdout = "\n".join([
        "STAGE: Bills sweep",
        "INFO some log line",
        json.dumps(SAMPLE_STAGE),
        "ACCOUNTABILITY SWEEP SUMMARY",
        '{"not_a_stage": true}',
        "not json {",
    ])
    summaries = parse_stage_summaries(stdout)
    assert len(summaries) == 1
    assert summaries[0]["created"] == 70


# ---------------------------------------------------------------------------
# Reports stay out of git
# ---------------------------------------------------------------------------

def test_reports_path_is_gitignored():
    root_ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    backend_ignore = (REPO_ROOT / "backend" / ".gitignore").read_text(encoding="utf-8")
    assert "reports/" in root_ignore
    assert "reports/" in backend_ignore