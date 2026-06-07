from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.ingestion_error import IngestionError
from app.models.ingestion_run import IngestionRun


def start_ingestion_run(db: Session, source_name: str, run_type: str, attempted_count: int) -> IngestionRun:
    run = IngestionRun(
        source_name=source_name,
        run_type=run_type,
        started_at=datetime.now(UTC),
        status="running",
        attempted_count=attempted_count,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_ingestion_run(db: Session, run: IngestionRun, summary: dict) -> IngestionRun:
    run.finished_at = datetime.now(UTC)
    run.status = "failed" if summary.get("failed_count", 0) and not summary.get("processed_count", 0) else "completed"
    run.processed_count = summary.get("processed_count", 0)
    run.created_count = summary.get("created_count", 0)
    run.updated_count = summary.get("updated_count", 0)
    run.skipped_count = summary.get("skipped_count", 0)
    run.failed_count = summary.get("failed_count", 0)
    run.error_summary = "; ".join(error.get("error", "")[:200] for error in summary.get("errors", [])[:5]) or None
    for error in summary.get("errors", []):
        db.add(
            IngestionError(
                ingestion_run=run,
                source_url=error.get("url", ""),
                error_message=error.get("error", ""),
                error_type=error.get("type"),
            )
        )
    db.commit()
    db.refresh(run)
    return run


def list_ingestion_runs(db: Session, limit: int = 20, offset: int = 0) -> list[IngestionRun]:
    statement = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement))


def get_ingestion_run(db: Session, run_id: UUID) -> IngestionRun | None:
    return db.scalars(
        select(IngestionRun).options(joinedload(IngestionRun.errors)).where(IngestionRun.id == run_id)
    ).unique().first()
