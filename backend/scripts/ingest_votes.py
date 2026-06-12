#!/usr/bin/env python3
"""Ingest vote/division events detected in PMG committee meeting minutes.

PMG exposes no /vote/ or /division/ API endpoint (both 404), so vote signals
are detected from the minutes text ("body") of committee-meeting detail
pages: https://api.pmg.org.za/committee-meeting/<id>/.

Rules (source-backed only):
  - A VoteEvent is created only when the minutes contain an explicit
    division/vote marker (division, votes in favour/against, abstentions,
    put to a/the vote ...).
  - VoteRecords are created only from explicit aggregate counts in the text
    ("X votes in favour", "Y votes against", "Z abstentions"),
    record_level="aggregate".
  - Individual MP votes are NEVER inferred from party positions.
  - If only the outcome is known, a VoteEvent is created with no records.

Dry-run semantics:
  --dry-run                 Fast and offline: prints the plan, no network,
                            no DB writes.
  --dry-run --discover      Fetches bounded API pages, no DB writes.

Examples:
    python scripts/ingest_votes.py --dry-run
    python scripts/ingest_votes.py --dry-run --discover --limit 20 --max-pages 2 --sleep 0.5
    python scripts/ingest_votes.py --limit 20 --max-pages 2 --from-date 2026-01-01 --sleep 0.5
"""
import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.committee_activity import (
    meeting_detail_api_url,
    parse_pmg_api_meetings,
    pmg_meetings_api_url,
)
from app.ingestion.votes import build_vote_event_from_meeting, fetch_page

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _fetch_json(fetch, url: str) -> dict:
    raw = fetch(url)
    return raw if isinstance(raw, dict) else json.loads(raw)


def run_votes_ingest(
    db,
    *,
    limit: int = 20,
    max_pages: int = 2,
    start_page: int = 0,
    sleep: float = 0.5,
    from_date: date | None = None,
    to_date: date | None = None,
    dry_run: bool = False,
    discover: bool = False,
    fetch=fetch_page,
) -> dict:
    """Core ingest logic, injectable for tests.

    Never writes to the DB when dry_run is True. Never touches the network
    when dry_run is True and discover is False.
    """
    summary = {
        "listing_pages_fetched": 0,
        "detail_pages_fetched": 0,
        "meetings_scanned": 0,
        "vote_events_found": 0,
        "processed": 0,
        "created": 0,
        "updated": 0,
        "vote_records": 0,
        "outcome_only_events": 0,
        "failed": 0,
        "errors": [],
        "dry_run": dry_run,
        "discover": discover,
    }

    if dry_run and not discover:
        logger.info(
            "dry-run: skipping live discovery (pass --discover to enable). "
            "Would scan up to %d listing page(s) of %s, detail-fetching up to %d meetings.",
            max_pages, pmg_meetings_api_url(0), limit,
        )
        return summary

    meetings: list[dict] = []
    for page in range(start_page, start_page + max_pages):
        url = pmg_meetings_api_url(page)
        try:
            payload = _fetch_json(fetch, url)
        except Exception as exc:
            summary["failed"] += 1
            summary["errors"].append({"url": url, "error": str(exc), "type": type(exc).__name__})
            logger.warning("FAILED listing page %s: %s", url, exc)
            break
        summary["listing_pages_fetched"] += 1
        meetings.extend(parse_pmg_api_meetings(payload))
        if len(meetings) >= limit or not payload.get("next"):
            break
        time.sleep(sleep)

    if from_date:
        meetings = [m for m in meetings if m["date"] and m["date"] >= from_date]
    if to_date:
        meetings = [m for m in meetings if m["date"] and m["date"] <= to_date]
    meetings = meetings[:limit]

    if db is None and not dry_run:
        raise ValueError("db session required for real runs")

    from sqlalchemy import select

    from app.models.vote_event import VoteEvent
    from app.services.accountability_service import upsert_vote_event

    for meeting in meetings:
        try:
            detail = _fetch_json(fetch, meeting_detail_api_url(meeting["api_id"]))
            summary["detail_pages_fetched"] += 1
            summary["meetings_scanned"] += 1
            event_data = build_vote_event_from_meeting(detail)
            if not event_data:
                continue
            summary["vote_events_found"] += 1
            if not event_data["vote_records"]:
                summary["outcome_only_events"] += 1

            if dry_run:
                logger.info(
                    "dry-run: would upsert vote event %r (result=%s, %d aggregate records, not written)",
                    event_data["title"][:70], event_data["result"], len(event_data["vote_records"]),
                )
                summary["processed"] += 1
                summary["vote_records"] += len(event_data["vote_records"])
                continue

            existing = db.scalar(select(VoteEvent).where(VoteEvent.source_url == event_data["source_url"]))
            upsert_vote_event(db, event_data)
            db.commit()
            summary["processed"] += 1
            summary["vote_records"] += len(event_data["vote_records"])
            if existing:
                summary["updated"] += 1
            else:
                summary["created"] += 1
        except Exception as exc:
            if not dry_run:
                db.rollback()
            summary["failed"] += 1
            summary["errors"].append(
                {"url": meeting.get("source_url") or "", "error": str(exc), "type": type(exc).__name__}
            )
            logger.warning("FAILED %s: %s", meeting.get("source_url"), exc)
        time.sleep(sleep)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded PMG vote/division detection from meeting minutes.")
    parser.add_argument("--limit", type=int, default=20, help="Max meetings to detail-scan.")
    parser.add_argument("--max-pages", type=int, default=2, help="Max listing API pages to fetch (50 meetings/page).")
    parser.add_argument("--start-page", type=int, default=0, help="Listing page to start from (0 = newest; minutes are published with a lag, so vote signals live on older pages).")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--from-date", default=None, help="Only meetings on/after this date (YYYY-MM-DD).")
    parser.add_argument("--to-date", default=None, help="Only meetings on/before this date (YYYY-MM-DD).")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    parser.add_argument("--json-output", action="store_true", help="Print the summary as JSON.")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    kwargs = dict(
        limit=args.limit,
        max_pages=args.max_pages,
        start_page=args.start_page,
        sleep=args.sleep,
        from_date=from_date,
        to_date=to_date,
        dry_run=args.dry_run,
        discover=args.discover,
    )

    if args.dry_run:
        summary = run_votes_ingest(None, **kwargs)
    else:
        from app.db import SessionLocal
        from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run

        with SessionLocal() as db:
            run = start_ingestion_run(db, "PMG", "votes_ingest", args.limit)
            summary = run_votes_ingest(db, **kwargs)
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

    if args.json_output:
        print(json.dumps(summary, default=str))
    else:
        for key, value in summary.items():
            if key != "errors":
                print(f"{key}: {value}")


if __name__ == "__main__":
    main()
