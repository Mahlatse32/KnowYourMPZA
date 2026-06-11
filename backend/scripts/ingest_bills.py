#!/usr/bin/env python3
"""Ingest bills from PMG and parliament.gov.za."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.bills import (
    fetch_page,
    parse_parliament_bills,
    parse_pmg_bills,
    _PMG_BILLS_URL,
    _PARLIAMENT_BILLS_URL,
)
from app.services.accountability_service import upsert_bill
from app.services.ingestion_service import start_ingestion_run, finish_ingestion_run

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SOURCES = [
    ("pmg", _PMG_BILLS_URL, parse_pmg_bills),
    ("parliament", _PARLIAMENT_BILLS_URL, parse_parliament_bills),
]


def main() -> None:
    db = SessionLocal()
    try:
        for source_name, url, parser in _SOURCES:
            run = start_ingestion_run(db, source_name=source_name, run_type="bills_ingest", source_url=url)
            processed = created = updated = failed = 0
            try:
                logger.info("Fetching %s bills from %s", source_name, url)
                html = fetch_page(url)
                bills = parser(html, url)
                logger.info("Parsed %d bills from %s", len(bills), source_name)
                for bill_data in bills:
                    try:
                        existing_title = None
                        from sqlalchemy import select
                        from app.models.bill import Bill
                        existing = db.scalar(select(Bill).where(Bill.source_url == bill_data.get("source_url")))
                        if existing:
                            existing_title = existing.title
                        upsert_bill(db, bill_data)
                        db.commit()
                        processed += 1
                        if existing_title:
                            updated += 1
                        else:
                            created += 1
                    except Exception as exc:
                        db.rollback()
                        failed += 1
                        logger.warning("Failed bill %s: %s", bill_data.get("title", "?"), exc)
            except Exception as exc:
                logger.error("Source %s failed: %s", source_name, exc)
                finish_ingestion_run(db, run, status="failed", processed=processed, created=created, updated=updated, failed=failed)
                db.commit()
                continue
            finish_ingestion_run(db, run, status="completed", processed=processed, created=created, updated=updated, failed=failed)
            db.commit()
            logger.info("%s: %d processed, %d created, %d updated, %d failed", source_name, processed, created, updated, failed)
    finally:
        db.close()


if __name__ == "__main__":
    main()
