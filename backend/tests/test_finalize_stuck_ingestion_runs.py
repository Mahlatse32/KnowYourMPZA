import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.ingestion_run import IngestionRun
from scripts.finalize_stuck_ingestion_runs import finalize_stuck_runs, write_report

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"

NOW = datetime(2026, 7, 4, 16, 0, 0, tzinfo=UTC)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _run(status: str, hours_ago: float) -> IngestionRun:
    return IngestionRun(
        source_name="Parliamentary Questions",
        run_type="PARLIAMENTARY_QUESTIONS",
        started_at=NOW - timedelta(hours=hours_ago),
        status=status,
    )


def test_old_running_run_is_finalized_with_audit_note():
    with _session() as db:
        db.add(_run("running", hours_ago=30))
        db.commit()
        report = finalize_stuck_runs(db, now=NOW)

        assert report["finalized_count"] == 1
        row = db.query(IngestionRun).one()
        assert row.status == "failed"
        assert row.finished_at is not None
        assert "cancelled or timed out" in row.error_summary


def test_recent_running_and_completed_runs_are_untouched():
    with _session() as db:
        db.add(_run("running", hours_ago=2))
        db.add(_run("completed", hours_ago=100))
        db.add(_run("failed", hours_ago=100))
        db.commit()
        report = finalize_stuck_runs(db, now=NOW)

        assert report["finalized_count"] == 0
        statuses = sorted(r.status for r in db.query(IngestionRun).all())
        assert statuses == ["completed", "failed", "running"]


def test_dry_run_reports_without_modifying():
    with _session() as db:
        db.add(_run("running", hours_ago=30))
        db.commit()
        report = finalize_stuck_runs(db, now=NOW, dry_run=True)

        assert report["finalized_count"] == 1
        assert report["dry_run"] is True
        assert db.query(IngestionRun).one().status == "running"


def test_counts_and_provenance_are_never_rewritten():
    with _session() as db:
        run = _run("running", hours_ago=30)
        run.attempted_count = 50
        run.processed_count = 12
        run.created_count = 12
        db.add(run)
        db.commit()
        finalize_stuck_runs(db, now=NOW)

        row = db.query(IngestionRun).one()
        assert (row.attempted_count, row.processed_count, row.created_count) == (50, 12, 12)


def test_report_file_is_written_and_secret_safe(tmp_path):
    with _session() as db:
        db.add(_run("running", hours_ago=30))
        db.commit()
        report = finalize_stuck_runs(db, now=NOW)
    path = write_report(report, tmp_path)
    blob = path.read_text(encoding="utf-8")

    payload = json.loads(blob)
    assert payload["finalized_count"] == 1
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob


def test_scheduled_workflow_finalizes_before_quality_checks():
    text = SCHEDULED_WORKFLOW.read_text(encoding="utf-8")
    assert text.count("python scripts/finalize_stuck_ingestion_runs.py --json-only || true") == 2
    daily, weekly = text.split("\n  weekly:", 1)
    for job in (daily, weekly):
        finalize = job.find("finalize_stuck_ingestion_runs.py")
        quality = job.find("check_data_quality.py")
        assert -1 < finalize < quality
