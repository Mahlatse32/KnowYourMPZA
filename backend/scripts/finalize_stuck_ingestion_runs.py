#!/usr/bin/env python3
"""Finalize ingestion runs stuck in status 'running'.

When a GitHub Actions job is cancelled or hits its timeout, the ingestion
process dies before `finish_ingestion_run` executes, leaving the run row in
status 'running' forever. Those zombie rows permanently fail the
'stuck ingestion runs' data quality check even though the underlying job is
long dead. This script marks runs older than a bounded age as failed with
an explicit audit note, so the quality gate reflects reality: the failure
window (7 days) captures them, then they age out.

Safe by construction: it only touches rows in status 'running' older than
the threshold, never rewrites counts or provenance, and records why the
row was finalized in error_summary.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_MAX_AGE_HOURS = 24


def finalize_stuck_runs(db, now: datetime | None = None, max_age_hours: int = DEFAULT_MAX_AGE_HOURS, dry_run: bool = False) -> dict:
    from sqlalchemy import select

    from app.models.ingestion_run import IngestionRun

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=max_age_hours)
    stuck = list(
        db.scalars(
            select(IngestionRun).where(IngestionRun.status == "running", IngestionRun.started_at < cutoff)
        )
    )
    finalized = []
    for run in stuck:
        finalized.append(
            {
                "id": str(run.id),
                "source_name": run.source_name,
                "run_type": run.run_type,
                "started_at": run.started_at.isoformat() if run.started_at else None,
            }
        )
        if not dry_run:
            run.status = "failed"
            run.finished_at = now
            run.error_summary = (
                f"Finalized by finalize_stuck_ingestion_runs: still 'running' after "
                f"{max_age_hours} hours; the job was cancelled or timed out before finalization."
            )
    if not dry_run:
        db.commit()
    return {
        "generated_at": now.isoformat(),
        "max_age_hours": max_age_hours,
        "dry_run": dry_run,
        "finalized_count": len(finalized),
        "finalized_runs": finalized,
    }


def write_report(report: dict, output_dir: str | Path = "reports") -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "stuck_runs_finalized.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize ingestion runs stuck in status 'running'.")
    parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        report = finalize_stuck_runs(db, max_age_hours=args.max_age_hours, dry_run=args.dry_run)
    path = write_report(report, args.reports_dir)
    if args.json_only:
        print(json.dumps({"finalized_count": report["finalized_count"], "report": str(path)}, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
