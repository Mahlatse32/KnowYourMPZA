#!/usr/bin/env python3
"""Backfill legislative history (bill lifecycle events) for bills already in the DB.

For each bill with a source_url, fetches the bill detail page and parses
lifecycle events (introduced, readings, committee referral, passed, assented)
into bill_events. Idempotent: events are upserted by their natural key.

Dry-run semantics:
  --dry-run                 Fast and offline: lists the bills that WOULD be
                            processed (read-only DB query), no network calls,
                            no writes.
  --dry-run --discover      Additionally fetches pages (bounded by --limit,
                            --max-pages, --sleep) and reports parsed event
                            counts. Still no DB writes.

Examples:
    python scripts/backfill_legislative_history.py --dry-run --limit 5
    python scripts/backfill_legislative_history.py --dry-run --discover --limit 5 --max-pages 1
    python scripts/backfill_legislative_history.py --limit 50 --max-pages 50 --sleep 0.5
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.bills import fetch_page, parse_bill_history
from app.models.bill import Bill

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_backfill(
    db: Session,
    *,
    limit: int = 50,
    max_pages: int = 20,
    sleep: float = 0.5,
    dry_run: bool = False,
    discover: bool = False,
    fetch=fetch_page,
) -> dict:
    """Core backfill logic, injectable for tests.

    Returns a summary dict. Never writes to the DB when dry_run is True.
    Never touches the network when dry_run is True and discover is False.
    """
    bills = list(
        db.scalars(
            select(Bill).where(Bill.source_url.is_not(None)).order_by(Bill.year.desc().nullslast()).limit(limit)
        )
    )
    summary = {
        "bills_selected": len(bills),
        "pages_fetched": 0,
        "events_parsed": 0,
        "events_created": 0,
        "events_existing": 0,
        "failed": 0,
        "dry_run": dry_run,
        "discover": discover,
    }

    if dry_run and not discover:
        logger.info("dry-run: %d bills would be processed (pass --discover to fetch pages).", len(bills))
        for bill in bills:
            logger.info("  would fetch: %s (%s)", bill.title[:80], bill.source_url)
        return summary

    from app.services.accountability_service import _upsert_bill_event

    for bill in bills:
        if summary["pages_fetched"] >= max_pages:
            logger.info("max-pages limit (%d) reached, stopping.", max_pages)
            break
        try:
            html = fetch(bill.source_url)
            summary["pages_fetched"] += 1
            events = parse_bill_history(html, bill.source_url)
            summary["events_parsed"] += len(events)
            if dry_run:
                logger.info("dry-run: %s -> %d events parsed (not written).", bill.source_url, len(events))
            else:
                for event_data in events:
                    from app.models.bill_event import BillEvent

                    existing = db.scalar(
                        select(BillEvent).where(
                            BillEvent.bill_id == bill.id,
                            BillEvent.event_type == event_data["event_type"],
                            BillEvent.event_date == event_data.get("event_date"),
                            BillEvent.source_url == event_data.get("source_url"),
                        )
                    )
                    if existing:
                        summary["events_existing"] += 1
                    else:
                        _upsert_bill_event(db, bill, event_data)
                        summary["events_created"] += 1
                db.commit()
        except Exception as exc:
            if not dry_run:
                db.rollback()
            summary["failed"] += 1
            logger.warning("FAILED %s: %s", bill.source_url, exc)
        time.sleep(sleep)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill bill lifecycle events from bill source pages.")
    parser.add_argument("--limit", type=int, default=50, help="Max bills to process.")
    parser.add_argument("--max-pages", type=int, default=20, help="Max pages to fetch.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    args = parser.parse_args()

    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            summary = run_backfill(
                db,
                limit=args.limit,
                max_pages=args.max_pages,
                sleep=args.sleep,
                dry_run=args.dry_run,
                discover=args.discover,
            )
    except Exception as exc:
        logger.warning("SKIP: database not reachable (%s). Nothing done.", exc)
        sys.exit(0 if args.dry_run else 1)

    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
