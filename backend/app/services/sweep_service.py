"""Durable sweep-state management for incremental source ingestion.

A "sweep" walks a paginated public source across many bounded runs. The state
row remembers where the next run should start; it advances only after a
successful run, so failed runs are retried from the same window. When the
source end is reached the cursor wraps to page 0 so future runs refresh the
newest data first.

Stream names in use:
  pmg_bills
  pmg_committee_meetings
  pmg_votes_from_meetings
  pmg_bill_lifecycle_backfill
The (source_name, stream_name) pair is open-ended so People's Assembly /
Parliament archive sweeps can be added later without schema changes.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion_sweep_state import IngestionSweepState

logger = logging.getLogger(__name__)

KNOWN_STREAMS = [
    "pmg_bills",
    "pmg_committee_meetings",
    "pmg_votes_from_meetings",
    "pmg_bill_lifecycle_backfill",
]


def get_or_create_sweep_state(
    db: Session,
    source_name: str,
    stream_name: str,
    cursor_type: str = "page",
    batch_size: int | None = None,
) -> IngestionSweepState:
    """Load the sweep state for (source, stream), creating it at page 0 if absent."""
    state = db.scalar(
        select(IngestionSweepState).where(
            IngestionSweepState.source_name == source_name,
            IngestionSweepState.stream_name == stream_name,
        )
    )
    if state is None:
        state = IngestionSweepState(
            source_name=source_name,
            stream_name=stream_name,
            cursor_type=cursor_type,
            page_number=0,
            batch_size=batch_size,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
        logger.info("Created sweep state %s/%s at page 0", source_name, stream_name)
    return state


def plan_sweep_run(state: IngestionSweepState, pages_per_run: int) -> dict[str, Any]:
    """Compute the bounded window the next run should cover. Read-only."""
    if pages_per_run < 1:
        raise ValueError("pages_per_run must be >= 1 — sweeps are always bounded")
    return {
        "stream_name": state.stream_name,
        "start_page": state.page_number,
        "pages_per_run": pages_per_run,
        "cursor_type": state.cursor_type,
    }


def start_sweep_run(db: Session, state: IngestionSweepState, pages_per_run: int) -> None:
    state.last_started_at = datetime.now(UTC)
    state.last_status = "running"
    state.max_pages_per_run = pages_per_run
    db.commit()


def complete_sweep_run(
    db: Session,
    state: IngestionSweepState,
    *,
    pages_attempted: int,
    seen: int = 0,
    created: int = 0,
    updated: int = 0,
    failed: int = 0,
    errors: list[dict] | None = None,
    end_reached: bool = False,
    source_total: int | None = None,
    advance: bool = True,
) -> IngestionSweepState:
    """Record a finished run. The cursor advances only when advance=True; on
    end_reached it wraps to page 0 (a completed full pass) so subsequent runs
    refresh newest-first. Idempotent records are the ingest layer's concern —
    this only tracks progress totals."""
    state.total_seen += seen
    state.total_created += created
    state.total_updated += updated
    state.total_failed += failed
    if source_total is not None:
        state.source_total = source_total
    state.last_completed_at = datetime.now(UTC)
    state.last_error = _format_errors(errors)

    if not advance:
        state.last_status = "completed_no_advance"
    elif end_reached:
        state.page_number = 0
        state.sweeps_completed += 1
        state.last_status = "completed_end_of_source"
        logger.info(
            "Sweep %s/%s reached end of source — wrapped to page 0 (pass #%d done)",
            state.source_name, state.stream_name, state.sweeps_completed,
        )
    else:
        state.page_number += pages_attempted
        state.last_status = "completed"
    db.commit()
    db.refresh(state)
    return state


def fail_sweep_run(
    db: Session,
    state: IngestionSweepState,
    error: str,
    *,
    advance: bool = False,
) -> IngestionSweepState:
    """Record a failed run. By default the cursor does NOT advance, so the
    same window is retried next run."""
    state.last_completed_at = datetime.now(UTC)
    state.last_status = "failed"
    state.last_error = (error or "")[:2000]
    state.total_failed += 1
    if advance:
        state.page_number += state.max_pages_per_run or 1
    db.commit()
    db.refresh(state)
    return state


def reset_sweep_state(db: Session, state: IngestionSweepState) -> IngestionSweepState:
    """Intentionally restart a sweep from page 0, clearing progress totals."""
    logger.warning("Resetting sweep state %s/%s (was at page %d)", state.source_name, state.stream_name, state.page_number)
    state.page_number = 0
    state.cursor_value = None
    state.total_seen = 0
    state.total_created = 0
    state.total_updated = 0
    state.total_failed = 0
    state.sweeps_completed = 0
    state.last_status = "reset"
    state.last_error = None
    db.commit()
    db.refresh(state)
    return state


def list_sweep_states(db: Session) -> list[IngestionSweepState]:
    return list(
        db.scalars(
            select(IngestionSweepState).order_by(
                IngestionSweepState.source_name, IngestionSweepState.stream_name
            )
        )
    )


def sweep_state_as_dict(state: IngestionSweepState) -> dict[str, Any]:
    return {
        "source_name": state.source_name,
        "stream_name": state.stream_name,
        "cursor_type": state.cursor_type,
        "next_page": state.page_number,
        "source_total": state.source_total,
        "total_seen": state.total_seen,
        "total_created": state.total_created,
        "total_updated": state.total_updated,
        "total_failed": state.total_failed,
        "sweeps_completed": state.sweeps_completed,
        "last_status": state.last_status,
        "last_started_at": state.last_started_at.isoformat() if state.last_started_at else None,
        "last_completed_at": state.last_completed_at.isoformat() if state.last_completed_at else None,
        "last_error": state.last_error,
    }


def _format_errors(errors: list[dict] | None) -> str | None:
    if not errors:
        return None
    parts = [f"{e.get('url', '')}: {e.get('error', '')}"[:300] for e in errors[:5]]
    return "; ".join(parts)[:2000]
