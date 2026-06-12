#!/usr/bin/env python3
"""Ingest vote events from PMG (index page + individual vote pages).

Dry-run semantics (same convention as ingest_bills.py):
  --dry-run                 Fast and offline: prints the plan, no network,
                            no DB writes.
  --dry-run --discover      Fetches the index and up to --max-pages vote
                            pages and prints what WOULD be upserted.
                            Still no DB writes.

Examples:
    python scripts/ingest_votes.py --dry-run
    python scripts/ingest_votes.py --dry-run --discover --limit 10 --max-pages 5 --sleep 0.5
    python scripts/ingest_votes.py --limit 10 --max-pages 10 --sleep 0.5
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.votes import (
    fetch_page,
    parse_pmg_vote_event,
    parse_pmg_votes_index,
    _PMG_VOTES_URL,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_votes_ingest(
    db,
    *,
    limit: int = 20,
    max_pages: int = 20,
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
        "urls_discovered": 0,
        "pages_fetched": 0,
        "processed": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
        "dry_run": dry_run,
        "discover": discover,
    }

    if dry_run and not discover:
        logger.info(
            "dry-run: skipping live discovery (pass --discover to enable). "
            "Would fetch %s then up to %d vote pages (limit %d).",
            _PMG_VOTES_URL, max_pages, limit,
        )
        return summary

    from sqlalchemy import select

    from app.models.vote_event import VoteEvent
    from app.services.accountability_service import upsert_vote_event

    index_html = fetch(_PMG_VOTES_URL)
    summary["pages_fetched"] += 1
    vote_urls = parse_pmg_votes_index(index_html)
    summary["urls_discovered"] = len(vote_urls)
    logger.info("Found %d vote URLs; processing up to %d", len(vote_urls), limit)

    for url in vote_urls[:limit]:
        if summary["pages_fetched"] >= max_pages + 1:  # +1 for the index page
            logger.info("max-pages limit (%d) reached, stopping.", max_pages)
            break
        try:
            html = fetch(url)
            summary["pages_fetched"] += 1
            event_data = parse_pmg_vote_event(html, source_url=url)
            if not event_data:
                logger.warning("SKIP %s (no data parsed)", url)
                continue
            if dry_run:
                logger.info(
                    "dry-run: would upsert vote event %r (%d records, not written).",
                    event_data["title"][:80], len(event_data["vote_records"]),
                )
                summary["processed"] += 1
                continue
            existing = db.scalar(select(VoteEvent).where(VoteEvent.source_url == url))
            upsert_vote_event(db, event_data)
            db.commit()
            summary["processed"] += 1
            if existing:
                summary["updated"] += 1
            else:
                summary["created"] += 1
        except Exception as exc:
            if not dry_run:
                db.rollback()
            summary["failed"] += 1
            summary["errors"].append({"url": url, "error": str(exc), "type": type(exc).__name__})
            logger.warning("FAILED %s: %s", url, exc)
        time.sleep(sleep)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded PMG vote events ingestion.")
    parser.add_argument("--limit", type=int, default=20, help="Max vote events to upsert.")
    parser.add_argument("--max-pages", type=int, default=20, help="Max individual vote pages to fetch.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    args = parser.parse_args()

    if args.dry_run and not args.discover:
        # No DB needed for the offline plan.
        run_votes_ingest(None, limit=args.limit, max_pages=args.max_pages, sleep=args.sleep, dry_run=True, discover=False)
        return

    from app.db import SessionLocal
    from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run

    with SessionLocal() as db:
        run = None
        if not args.dry_run:
            run = start_ingestion_run(db, "PMG", "votes_ingest", args.limit)
        summary = run_votes_ingest(
            db,
            limit=args.limit,
            max_pages=args.max_pages,
            sleep=args.sleep,
            dry_run=args.dry_run,
            discover=args.discover,
        )
        if run is not None:
            finish_ingestion_run(
                db,
                run,
                {
                    "processed_count": summary["processed"],
                    "created_count": summary["created"],
                    "updated_count": summary["updated"],
                    "skipped_count": 0,
                    "failed_count": summary["failed"],
                    "errors": summary["errors"],
                },
            )
            db.commit()

    for key, value in summary.items():
        if key != "errors":
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
