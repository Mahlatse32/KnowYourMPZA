from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "iec-ingestion-dry-run.yml"
RUNBOOK = REPO_ROOT / "backend" / "docs" / "iec-election-results-ingestion.md"


def test_workflow_is_manual_only_and_dry_run():
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_block = text.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "schedule:" not in trigger_block
    assert 'default: "true"' in text
    assert "--dry-run" in text
    assert "--offline-fixture" in text


def test_workflow_never_runs_vote_total_ingestion_or_large_downloads():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ingest_iec_vote_totals.py" not in text
    assert "curl " not in text
    assert "wget " not in text
    assert "download" not in text.lower()


def test_workflow_does_not_echo_database_url_and_uploads_reports():
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "echo" in line.lower():
            assert "DATABASE_URL" not in line
            assert "$DATABASE_URL" not in line
    assert "actions/upload-artifact@v4" in text
    assert "backend/reports/" in text
    assert "python scripts/report_iec_coverage.py" in text


def test_runbook_has_operator_safety_rules_and_commands():
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    assert "dry-run first" in text
    assert "ingest_iec_metadata_manifest.py" in text
    assert "ingest_iec_vote_totals.py" in text
    assert "report_iec_coverage.py" in text
    assert "manifest_key" in text
    assert "do not commit" in text
    assert "no winner" in text
    assert "idempotent" in text
