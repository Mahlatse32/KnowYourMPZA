#!/usr/bin/env python3
"""Ingest bills from the PMG public API (api.pmg.org.za/bill/).

The HTML pages at pmg.org.za/bills/ and parliament.gov.za/bills are
JavaScript-rendered shells with no bill data in the static HTML, so the
documented PMG JSON API is used as the source. Every ingested bill stores
its human-readable source URL (https://pmg.org.za/bill/<id>/).

Dry-run semantics (same convention as backfill_legislative_history.py):
  --dry-run                 Fast and offline: prints the plan, no network,
                            no DB writes.
  --dry-run --discover      Fetches API pages (bounded by --max-pages) and
                            prints what WOULD be upserted. Still no DB writes.

Examples:
    python scripts/ingest_bills.py --dry-run
    python scripts/ingest_bills.py --dry-run --discover --limit 10 --max-pages 1 --sleep 0.5
    python scripts/ingest_bills.py --limit 10 --max-pages 1 --sleep 0.5
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded bills ingestion from the PMG API.")
    parser.add_argument("--limit", type=int, default=50, help="Max bills to upsert in total.")
    parser.add_argument("--max-pages", type=int, default=1, help="Max API pages to fetch (50 bills/page).")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    args = parser.parse_args()

    if args.dry_run and not args.discover:
        print("dry-run: skipping live discovery (pass --discover to enable).")
        print(f"  would fetch up to {args.max_pages} page(s) of {pmg_api_page_url(0)} (limit {args.limit} bills)")
        return

    from app.db import SessionLocal
    from app.services.accountability_service import upsert_bill
    from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run

    processed = created = updated = failed = 0
    errors: list[dict] = []

    db = SessionLocal()
    try:
        run = None
        if not args.dry_run:
            run = start_ingestion_run(db, "PMG", "bills_ingest", args.limit)

        bills: list[dict] = []
        for page in range(args.max_pages):
            url = pmg_api_page_url(page)
            logger.info("Fetching PMG bills API page %d: %s", page, url)
            try:
                payload = json.loads(fetch_page(url))
            except Exception as exc:
                logger.warning("FAILED page %s: %s", url, exc)
                errors.append({"url": url, "error": str(exc), "type": type(exc).__name__})
                failed += 1
                break
            page_bills = parse_pmg_api_bills(payload)
            logger.info("  parsed %d bills", len(page_bills))
            bills.extend(page_bills)
            if len(bills) >= args.limit or not payload.get("next"):
                break
            time.sleep(args.sleep)
        bills = bills[: args.limit]

        for bill_data in bills:
            if args.dry_run:
                logger.info(
                    "dry-run: would upsert bill %r (number=%s year=%s status=%s source=%s)",
                    bill_data["title"][:80],
                    bill_data.get("bill_number"),
                    bill_data.get("year"),
                    bill_data.get("status"),
                    bill_data.get("source_url"),
                )
                processed += 1
                continue
            try:
                from sqlalchemy import select
                from app.models.bill import Bill

                existing = db.scalar(select(Bill).where(Bill.source_url == bill_data.get("source_url")))
                upsert_bill(db, bill_data)
                db.commit()
                processed += 1
                if existing:
                    updated += 1
                else:
                    created += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                errors.append({"url": bill_data.get("source_url") or "", "error": str(exc), "type": type(exc).__name__})
                logger.warning("Failed bill %s: %s", bill_data.get("title", "?"), exc)

        if run is not None:
            finish_ingestion_run(
                db,
                run,
                {
                    "processed_count": processed,
                    "created_count": created,
                    "updated_count": updated,
                    "skipped_count": 0,
                    "failed_count": failed,
                    "errors": errors,
                },
            )
            db.commit()
    finally:
        db.close()

    logger.info(
        "done: %d processed, %d created, %d updated, %d failed%s",
        processed, created, updated, failed,
        " (dry-run, nothing written)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
