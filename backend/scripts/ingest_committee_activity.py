#!/usr/bin/env python3
"""Ingest committee meeting records from PMG.

Fetches up to --max-pages individual meeting pages.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.committee_activity import (
    fetch_page,
    parse_pmg_meeting,
    parse_pmg_meetings_index,
    _PMG_MEETINGS_URL,
)
from app.services.accountability_service import upsert_committee_meeting
from app.services.ingestion_service import start_ingestion_run, finish_ingestion_run

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=20, help="Max individual meeting pages to fetch")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run = start_ingestion_run(db, source_name="pmg", run_type="committee_activity_ingest", source_url=_PMG_MEETINGS_URL)
        processed = created = updated = failed = 0
        try:
            logger.info("Fetching PMG meetings index")
            index_html = fetch_page(_PMG_MEETINGS_URL)
            meeting_urls = parse_pmg_meetings_index(index_html)
            logger.info("Found %d meeting URLs; will process up to %d", len(meeting_urls), args.max_pages)

            for url in meeting_urls[: args.max_pages]:
                try:
                    html = fetch_page(url)
                    meeting_data = parse_pmg_meeting(html, source_url=url)
                    if not meeting_data:
                        logger.warning("SKIP %s (no data parsed)", url)
                        continue
                    from sqlalchemy import select
                    from app.models.committee_meeting import CommitteeMeeting
                    existing = db.scalar(select(CommitteeMeeting).where(CommitteeMeeting.source_url == url))
                    upsert_committee_meeting(db, meeting_data)
                    db.commit()
                    processed += 1
                    if existing:
                        updated += 1
                    else:
                        created += 1
                except Exception as exc:
                    db.rollback()
                    failed += 1
                    logger.warning("FAILED %s: %s", url, exc)
        except Exception as exc:
            logger.error("Committee activity ingestion failed: %s", exc)
            finish_ingestion_run(db, run, status="failed", processed=processed, created=created, updated=updated, failed=failed)
            db.commit()
            sys.exit(1)

        finish_ingestion_run(db, run, status="completed", processed=processed, created=created, updated=updated, failed=failed)
        db.commit()
        logger.info("Done: %d processed, %d created, %d updated, %d failed", processed, created, updated, failed)
    finally:
        db.close()


if __name__ == "__main__":
    main()
