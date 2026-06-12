#!/usr/bin/env python3
"""Print row counts and a few sample rows per table. Read-only.

Examples:
    python scripts/inspect_db.py --samples 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app import models


INSPECT_MODELS = [
    models.Politician,
    models.Party,
    models.Committee,
    models.CommitteeMembership,
    models.Document,
    models.DocumentMention,
    models.ParliamentaryQuestion,
    models.UnresolvedEntity,
    models.IngestionRun,
    models.Bill,
    models.BillEvent,
    models.VoteEvent,
    models.VoteRecord,
    models.CommitteeMeeting,
    models.CommitteeAttendance,
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect database contents (read-only).")
    parser.add_argument("--samples", type=int, default=2, help="Sample rows to print per table.")
    args = parser.parse_args()

    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            for model in INSPECT_MODELS:
                count = db.scalar(select(func.count()).select_from(model)) or 0
                print(f"\n{model.__tablename__}: {count} rows")
                if count and args.samples:
                    for row in db.scalars(select(model).limit(args.samples)):
                        cols = {
                            c.name: str(getattr(row, c.name, ""))[:60]
                            for c in model.__table__.columns
                            if c.name in ("id", "title", "full_name", "name", "status", "source_url")
                        }
                        print(f"  {cols}")
    except Exception as exc:
        print(f"SKIP: database not reachable ({exc}).")
        sys.exit(0)


if __name__ == "__main__":
    main()
