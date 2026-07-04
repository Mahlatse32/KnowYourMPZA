"""Workflow-shape tests for the Parliament questions backfill (mirrors the
pmg-meeting-backfill workflow tests). Question ingestion is idempotent
(upsert by source_url) and new-record-first, so a frequent bounded batch is
the safe way to close the ~44k docsjson coverage gap for V1."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "parliament-questions-backfill.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_file_exists():
    assert WORKFLOW.exists(), "parliament-questions-backfill workflow file missing"


def test_workflow_has_manual_dispatch_and_schedule():
    text = _text()
    assert "workflow_dispatch" in text
    assert "max_urls" in text
    assert "schedule:" in text
    assert "cron:" in text


def test_workflow_has_bounded_batch_and_timeout():
    text = _text()
    assert "timeout-minutes: 90" in text
    assert '--limit "$MAX_QUESTION_BACKFILL_URLS"' in text
    assert "|| '200'" in text


def test_workflow_guards_both_required_secrets():
    text = _text()
    assert 'case "${INGESTION_ENABLED,,}"' in text
    assert 'if [ -z "$DATABASE_URL" ]' in text
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in text
    assert "INGESTION_ENABLED: ${{ secrets.INGESTION_ENABLED }}" in text


def test_workflow_never_echoes_secret_values():
    for line in _text().splitlines():
        if "echo" not in line:
            continue
        assert "$DATABASE_URL" not in line
        assert "$INGESTION_ENABLED" not in line
        assert "${{ secrets." not in line


def test_workflow_has_own_concurrency_group_without_cancel():
    text = _text()
    assert "group: parliament-questions-backfill" in text
    assert "cancel-in-progress: false" in text


def test_workflow_runs_reports_non_blocking_before_upload():
    text = _text()
    for step in (
        "python scripts/inspect_db.py --samples 3 --json-output > reports/inspect_db.json || true",
        "python scripts/report_data_coverage_dashboard.py || true",
        "python scripts/finalize_stuck_ingestion_runs.py --json-only || true",
        "python scripts/check_data_quality.py --json-only || true",
        "python scripts/report_v1_readiness.py --reports-dir reports || true",
    ):
        assert step in text
    ingest = text.find("ingest_all_parliamentary_questions.py")
    readiness = text.find("report_v1_readiness.py")
    upload = text.find("actions/upload-artifact")
    assert -1 < ingest < readiness < upload


def test_workflow_uploads_artifacts_always():
    text = _text()
    assert "actions/upload-artifact" in text
    assert "path: backend/reports/" in text
    upload_region = text[text.find("Upload run reports as artifacts") - 200 :]
    assert "if: always()" in upload_region


def test_cron_offsets_do_not_collide_with_other_ingestion_workflows():
    """The questions backfill (:20 odd hours) must not share a firing minute
    pattern with the meeting backfill (:50 every 2 hours) or the daily jobs."""
    questions = _text()
    meetings = (REPO_ROOT / ".github" / "workflows" / "pmg-meeting-backfill.yml").read_text(encoding="utf-8")
    assert "20 1-23/2 * * *" in questions
    assert "50 */2 * * *" in meetings
