from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"


def test_scheduled_ingestion_workflow_has_early_configuration_guards():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = text.split("\n  weekly:", 1)
    assert len(jobs) == 2

    for job in jobs:
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


def test_scheduled_ingestion_workflow_checks_both_required_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count('case "${INGESTION_ENABLED,,}"') == 2
    assert text.count('if [ -z "$DATABASE_URL" ]') == 2
    assert "Set the repository Actions secret INGESTION_ENABLED to true." in text
    assert "The repository Actions secret DATABASE_URL is not configured." in text


def test_scheduled_ingestion_workflow_never_echoes_secret_values():
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "echo" not in line:
            continue
        assert "$INGESTION_ENABLED" not in line
        assert "$DATABASE_URL" not in line
        assert "${{ secrets." not in line
