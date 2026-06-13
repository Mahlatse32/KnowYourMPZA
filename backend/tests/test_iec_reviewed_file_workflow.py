"""Tests for the IEC reviewed-file ingestion workflow (#24). Static YAML/doc checks."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "iec-reviewed-file-ingestion.yml"
RUNBOOK = REPO_ROOT / "backend" / "docs" / "iec-election-results-ingestion.md"


def _wf() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.exists()


def test_workflow_dispatch_only_no_schedule():
    text = _wf()
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text


def test_inputs_present_with_dry_run_default_true():
    text = _wf()
    assert "manifest_key:" in text
    assert "reviewed_file_path:" in text
    assert "dry_run:" in text
    assert "upload_reports:" in text
    # dry_run default is "true"
    dry_block = text.split("dry_run:", 1)[1].split("upload_reports:", 1)[0]
    assert 'default: "true"' in dry_block


def test_refuses_unsafe_runs():
    text = _wf()
    # required-when-not-dry-run
    assert "reviewed_file_path is required when dry_run=false" in text
    # allowed-directory enforcement
    assert "tests/fixtures/iec/" in text and "data/iec/" in text
    assert "must be under tests/fixtures/iec/ or data/iec/" in text
    # traversal + existence
    assert "must not contain '..'" in text
    assert "does not exist" in text


def test_does_not_echo_database_url():
    for line in _wf().splitlines():
        if "echo" in line:
            assert "$DATABASE_URL" not in line
            assert "${{ secrets" not in line


def test_no_live_download_commands():
    text = _wf().lower()
    assert "curl " not in text
    assert "wget " not in text


def test_uses_ephemeral_postgres_not_persistent():
    text = _wf()
    assert "postgres:16-alpine" in text
    # ephemeral localhost URL, never a secret/persistent DB
    assert "localhost:5432" in text
    assert "secrets.DATABASE_URL" not in text


def test_runs_alembic_and_vote_total_ingestion():
    text = _wf()
    assert "alembic upgrade head" in text
    assert "scripts/ingest_iec_vote_totals.py" in text
    assert "--manifest-key" in text and "--input-file" in text


def test_uploads_reports():
    text = _wf()
    assert "actions/upload-artifact@v4" in text
    assert "backend/reports/" in text


def test_runbook_documents_reviewed_file_rule():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "reviewed" in text.lower()
    assert "iec-reviewed-file-ingestion.yml" in text
    assert "dry-run" in text.lower()
