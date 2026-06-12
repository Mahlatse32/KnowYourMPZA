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


def build_inspect_payload(db, samples: int = 2, include_sweep: bool = True) -> dict:
    """Machine-readable inspection payload: table counts, sample rows
    (id/title/name/status/source_url columns only), and sweep states."""
    payload: dict = {"tables": {}, "sweep_states": []}
    for model in INSPECT_MODELS:
        count = db.scalar(select(func.count()).select_from(model)) or 0
        rows = []
        if count and samples:
            for row in db.scalars(select(model).limit(samples)):
                rows.append(
                    {
                        c.name: str(getattr(row, c.name, ""))[:120]
                        for c in model.__table__.columns
                        if c.name in ("id", "title", "full_name", "name", "status", "source_url")
                    }
                )
        payload["tables"][model.__tablename__] = {"count": count, "samples": rows}
    if include_sweep:
        from app.services.sweep_service import list_sweep_states, sweep_state_as_dict

        payload["sweep_states"] = [sweep_state_as_dict(s) for s in list_sweep_states(db)]
    return payload


def main() -> None:
    import json

    parser = argparse.ArgumentParser(description="Inspect database contents (read-only).")
    parser.add_argument("--samples", type=int, default=2, help="Sample rows to print per table.")
    parser.add_argument("--show-sweep-state", action="store_true", help="Also print incremental sweep states.")
    parser.add_argument("--json-output", action="store_true", help="Print the inspection payload as JSON.")
    args = parser.parse_args()

    from app.db import SessionLocal

    try:
        if args.json_output:
            with SessionLocal() as db:
                payload = build_inspect_payload(db, samples=args.samples, include_sweep=True)
            print(json.dumps(payload, default=str))
            return
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
            if args.show_sweep_state:
                from app.services.sweep_service import list_sweep_states, sweep_state_as_dict

                print("\n--- sweep states ---")
                states = list_sweep_states(db)
                if not states:
                    print("(no sweep states yet)")
                for state in states:
                    info = sweep_state_as_dict(state)
                    pct = None
                    if info["source_total"] and state.stream_name == "pmg_committee_meetings":
                        pct = round(info["next_page"] * 50 / info["source_total"] * 100, 2)
                    print(
                        f"{info['source_name']}/{info['stream_name']}: next_page={info['next_page']}"
                        f" status={info['last_status']} completed_at={info['last_completed_at']}"
                        f" totals(seen={info['total_seen']} created={info['total_created']}"
                        f" updated={info['total_updated']} failed={info['total_failed']})"
                        f" source_total={info['source_total']}"
                        + (f" est_covered={pct}%" if pct is not None else "")
                    )
                    if info["last_error"]:
                        print(f"  last_error: {info['last_error'][:160]}")
    except Exception as exc:
        print(f"SKIP: database not reachable ({exc}).")
        sys.exit(0)


if __name__ == "__main__":
    main()
