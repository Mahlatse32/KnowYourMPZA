#!/usr/bin/env python3
"""Ingest bills from the PMG public API (api.pmg.org.za/bill/).

The HTML pages at pmg.org.za/bills/ and parliament.gov.za/bills are
JavaScript-rendered shells with no bill data in the static HTML, so the
documented PMG JSON API is used as the source. Every ingested bill stores
its human-readable source URL (https://pmg.org.za/bill/<id>/).

Dry-run semantics (same convention as backfill_legislative_history.py):
  --dry-run                 Fast and offline: prints the plan, no network,
                            no DB writes, never advances sweep state.
  --dry-run --discover      Fetches API pages (bounded by --max-pages) and
                            prints what WOULD be upserted. Still no DB
                            writes and no sweep advancement.

Sweep mode (incremental coverage across scheduled runs):
  --sweep                   Start from the durable sweep cursor instead of
                            page 0 and advance it after a successful run.
  --pages-per-run N         Bounded window per sweep run (required bound).
  --no-advance-sweep        Record the run but keep the cursor in place.
  --reset-sweep             Intentionally restart the sweep from page 0.
  --show-sweep-state        Print the sweep state and exit.

Examples:
    python scripts/ingest_bills.py --dry-run
    python scripts/ingest_bills.py --dry-run --discover --limit 10 --max-pages 1 --sleep 0.5
    python scripts/ingest_bills.py --limit 10 --max-pages 1 --sleep 0.5
    python scripts/ingest_bills.py --sweep --pages-per-run 2 --sleep 0.5
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.bills import fetch_page, parse_pmg_api_bills, pmg_api_page_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STREAM_NAME = "pmg_bills"
SOURCE_NAME = "PMG"
_PAGE_SIZE = 50  # PMG API page size


def run_bills_ingest(
    db,
    *,
    limit: int = 50,
    max_pages: int = 1,
    start_page: int = 0,
    sleep: float = 0.5,
    dry_run: bool = False,
    discover: bool = False,
    fetch=fetch_page,
) -> dict:
    """Core ingest logic, injectable for tests.

    Never writes to the DB when dry_run is True. Never touches the network
    when dry_run is True and discover is False.
    """
    summary = {
        "start_page": start_page,
        "pages_attempted": 0,
        "bills_seen": 0,
        "processed": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
        "end_reached": False,
        "source_total": None,
        "dry_run": dry_run,
        "discover": discover,
    }

    if dry_run and not discover:
        logger.info(
            "dry-run: skipping live discovery (pass --discover to enable). "
            "Would fetch pages %d..%d of %s (limit %d bills).",
            start_page, start_page + max_pages - 1, pmg_api_page_url(0), limit,
        )
        return summary

    bills: list[dict] = []
    for page in range(start_page, start_page + max_pages):
        url = pmg_api_page_url(page)
        logger.info("Fetching PMG bills API page %d: %s", page, url)
        try:
            raw = fetch(url)
            payload = raw if isinstance(raw, dict) else json.loads(raw)
        except Exception as exc:
            summary["failed"] += 1
            summary["errors"].append({"url": url, "error": str(exc), "type": type(exc).__name__})
            logger.warning("FAILED page %s: %s", url, exc)
            break
        summary["pages_attempted"] += 1
        if payload.get("count") is not None:
            summary["source_total"] = payload["count"]
        page_bills = parse_pmg_api_bills(payload)
        logger.info("  parsed %d bills", len(page_bills))
        bills.extend(page_bills)
        if not payload.get("next"):
            summary["end_reached"] = True
            break
        if len(bills) >= limit:
            break
        time.sleep(sleep)

    summary["bills_seen"] = len(bills)
    bills = bills[:limit]

    if db is None and not dry_run:
        raise ValueError("db session required for real runs")

    for bill_data in bills:
        if dry_run:
            logger.info(
                "dry-run: would upsert bill %r (number=%s year=%s status=%s source=%s)",
                bill_data["title"][:80],
                bill_data.get("bill_number"),
                bill_data.get("year"),
                bill_data.get("status"),
                bill_data.get("source_url"),
            )
            summary["processed"] += 1
            continue
        try:
            from sqlalchemy import select

            from app.models.bill import Bill
            from app.services.accountability_service import upsert_bill

            existing = db.scalar(select(Bill).where(Bill.source_url == bill_data.get("source_url")))
            upsert_bill(db, bill_data)
            db.commit()
            summary["processed"] += 1
            if existing:
                summary["updated"] += 1
            else:
                summary["created"] += 1
        except Exception as exc:
            db.rollback()
            summary["failed"] += 1
            summary["errors"].append({"url": bill_data.get("source_url") or "", "error": str(exc), "type": type(exc).__name__})
            logger.warning("Failed bill %s: %s", bill_data.get("title", "?"), exc)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded bills ingestion from the PMG API.")
    parser.add_argument("--limit", type=int, default=50, help="Max bills to upsert in total.")
    parser.add_argument("--max-pages", type=int, default=1, help="Max API pages to fetch (50 bills/page).")
    parser.add_argument("--start-page", type=int, default=0, help="API page to start from (direct mode).")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    parser.add_argument("--json-output", action="store_true", help="Print the summary as JSON.")
    add_sweep_args(parser)
    args = parser.parse_args()

    summary = execute_with_optional_sweep(
        args,
        stream_name=STREAM_NAME,
        run_core=lambda db, start_page, max_pages: run_bills_ingest(
            db,
            limit=args.limit if not args.sweep else max_pages * _PAGE_SIZE,
            max_pages=max_pages,
            start_page=start_page,
            sleep=args.sleep,
            dry_run=args.dry_run,
            discover=args.discover,
        ),
        run_type="bills_ingest",
    )
    print_summary(summary, json_output=args.json_output)


# ---------------------------------------------------------------------------
# Shared sweep-mode CLI plumbing (imported by the other ingestion scripts).
# ---------------------------------------------------------------------------

def add_sweep_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sweep", action="store_true", help="Resume from the durable sweep cursor and advance it on success.")
    parser.add_argument("--stream-name", default=None, help="Override the sweep stream name.")
    parser.add_argument("--pages-per-run", type=int, default=2, help="Bounded page window per sweep run.")
    parser.add_argument("--no-advance-sweep", action="store_true", help="Record the sweep run but do not advance the cursor.")
    parser.add_argument("--reset-sweep", action="store_true", help="Intentionally restart the sweep from page 0, then exit.")
    parser.add_argument("--show-sweep-state", action="store_true", help="Print the sweep state and exit.")


def execute_with_optional_sweep(args, *, stream_name: str, run_core, run_type: str, needs_db_for_dry_run: bool = False) -> dict:
    """Run a script core in direct or sweep mode with shared rules:

    - direct mode: behaves exactly as before (start page from --start-page)
    - sweep mode: start page comes from the durable sweep state; the cursor
      advances only after a successful real run (never on dry runs, never on
      failures, never with --no-advance-sweep)
    """
    stream = args.stream_name or stream_name

    if not args.sweep:
        if args.dry_run:
            if needs_db_for_dry_run:
                from app.db import SessionLocal

                with SessionLocal() as db:
                    return run_core(db, args.start_page, args.max_pages)
            return run_core(None, args.start_page, args.max_pages)
        from app.db import SessionLocal
        from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run

        with SessionLocal() as db:
            run = start_ingestion_run(db, SOURCE_NAME, run_type, args.limit if hasattr(args, "limit") else 0)
            summary = run_core(db, args.start_page, args.max_pages)
            finish_ingestion_run(db, run, _run_summary(summary))
            db.commit()
        return summary

    # --- sweep mode ---
    if args.pages_per_run < 1:
        raise SystemExit("sweep mode requires --pages-per-run >= 1 (sweeps are always bounded)")

    from app.db import SessionLocal
    from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
    from app.services.sweep_service import (
        complete_sweep_run,
        fail_sweep_run,
        get_or_create_sweep_state,
        plan_sweep_run,
        reset_sweep_state,
        start_sweep_run,
        sweep_state_as_dict,
    )

    with SessionLocal() as db:
        state = get_or_create_sweep_state(db, SOURCE_NAME, stream)

        if args.show_sweep_state:
            print(json.dumps(sweep_state_as_dict(state), default=str, indent=1))
            return {"sweep": sweep_state_as_dict(state), "action": "show"}
        if args.reset_sweep:
            state = reset_sweep_state(db, state)
            print(json.dumps(sweep_state_as_dict(state), default=str, indent=1))
            return {"sweep": sweep_state_as_dict(state), "action": "reset"}

        plan = plan_sweep_run(state, args.pages_per_run)
        start_page = plan["start_page"]

        if args.dry_run:
            # Dry runs never touch sweep state.
            summary = run_core(db if needs_db_for_dry_run else None, start_page, args.pages_per_run)
            summary["sweep"] = {**sweep_state_as_dict(state), "planned_start_page": start_page, "advanced": False}
            return summary

        start_sweep_run(db, state, args.pages_per_run)
        run = start_ingestion_run(db, SOURCE_NAME, run_type, args.pages_per_run)
        try:
            summary = run_core(db, start_page, args.pages_per_run)
        except Exception as exc:
            fail_sweep_run(db, state, str(exc))
            finish_ingestion_run(db, run, {"processed_count": 0, "created_count": 0, "updated_count": 0, "skipped_count": 0, "failed_count": 1, "errors": [{"url": "", "error": str(exc), "type": type(exc).__name__}]})
            db.commit()
            raise

        run_failed = summary["pages_attempted"] == 0 and summary["failed"] > 0
        advance = not args.no_advance_sweep and not run_failed
        if run_failed:
            fail_sweep_run(db, state, (summary["errors"][0]["error"] if summary["errors"] else "no pages fetched"))
        else:
            complete_sweep_run(
                db,
                state,
                pages_attempted=summary["pages_attempted"],
                seen=summary.get("bills_seen") or summary.get("meetings_discovered") or summary.get("meetings_scanned") or summary.get("bills_selected") or 0,
                created=summary.get("created", summary.get("events_created", 0)),
                updated=summary.get("updated", summary.get("events_existing", 0)),
                failed=summary["failed"],
                errors=summary["errors"],
                end_reached=summary.get("end_reached", False),
                source_total=summary.get("source_total"),
                advance=advance,
            )
        finish_ingestion_run(db, run, _run_summary(summary))
        db.commit()
        summary["sweep"] = {
            **sweep_state_as_dict(state),
            "start_page_used": start_page,
            "advanced": advance and not run_failed,
        }
        return summary


def _run_summary(summary: dict) -> dict:
    return {
        "processed_count": summary.get("processed", 0),
        "created_count": summary.get("created", summary.get("events_created", 0)),
        "updated_count": summary.get("updated", summary.get("events_existing", 0)),
        "skipped_count": 0,
        "failed_count": summary.get("failed", 0),
        "errors": summary.get("errors", []),
    }


def print_summary(summary: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(summary, default=str))
        return
    for key, value in summary.items():
        if key == "errors":
            continue
        if key == "sweep" and isinstance(value, dict):
            print("sweep:")
            for k, v in value.items():
                print(f"  {k}: {v}")
            continue
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
