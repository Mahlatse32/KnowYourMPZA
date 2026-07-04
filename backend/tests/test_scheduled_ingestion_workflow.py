from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"


def _jobs() -> tuple[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    daily, weekly = text.split("\n  weekly:", 1)
    return daily, weekly


def test_scheduled_ingestion_workflow_has_early_configuration_guards():
    for job in _jobs():
        guard = job.find("Validate scheduled ingestion configuration")
        install = job.find("pip install -r requirements.txt")
        migration = job.find("alembic upgrade head")
        ingestion = job.find("run_daily_ingestion.py")
        if ingestion == -1:
            ingestion = job.find("run_weekly_ingestion.py")

        assert guard != -1
        assert install != -1
        assert migration != -1
        assert ingestion != -1
        assert guard < install < migration < ingestion


def test_scheduled_ingestion_jobs_create_reports_directory():
    for job in _jobs():
        mkdir = job.find("mkdir -p reports")
        first_report_write = job.find("> reports/inspect_db.json")
        assert mkdir != -1
        assert first_report_write != -1
        assert mkdir < first_report_write


def test_scheduled_ingestion_jobs_upload_distinct_artifacts_always():
    daily, weekly = _jobs()
    assert "name: scheduled-ingestion-daily-reports-${{ github.run_number }}" in daily
    assert "name: scheduled-ingestion-weekly-reports-${{ github.run_number }}" in weekly
    for job in (daily, weekly):
        upload = job[job.find("uses: actions/upload-artifact@v4") - 100 :]
        assert "if: always()" in upload
        assert "path: backend/reports/" in upload


def test_scheduled_ingestion_report_generation_is_non_blocking():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("python scripts/inspect_db.py --samples 3 --json-output > reports/inspect_db.json || true") == 2
    assert text.count("python scripts/dataset_report.py || true") == 2
    assert text.count("python scripts/generate_ingestion_brief.py --reports-dir reports || true") == 2
    assert text.count("python scripts/report_v1_readiness.py --reports-dir reports || true") == 2


def test_scheduled_ingestion_workflow_checks_both_required_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count('case "${INGESTION_ENABLED,,}"') == 2
    assert text.count('if [ -z "$DATABASE_URL" ]') == 2
    assert "Set the repository Actions secret INGESTION_ENABLED to true." in text
    assert "The repository Actions secret DATABASE_URL is not configured." in text


def test_scheduled_ingestion_workflow_uses_required_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("DATABASE_URL: ${{ secrets.DATABASE_URL }}") == 2
    assert text.count("INGESTION_ENABLED: ${{ secrets.INGESTION_ENABLED }}") == 2


def test_scheduled_ingestion_workflow_never_echoes_secret_values():
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "echo" not in line:
            continue
        assert "$INGESTION_ENABLED" not in line
        assert "$DATABASE_URL" not in line
        assert "${{ secrets." not in line
