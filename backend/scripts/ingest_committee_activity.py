#!/usr/bin/env python3
"""Ingest committee meetings (and explicit attendance) from the PMG API.

Sources:
  - Listing:    https://api.pmg.org.za/committee-meeting/?page=N
  - Attendance: https://api.pmg.org.za/committee-meeting/<id>/attendance/

The HTML pages at pmg.org.za are JS-rendered shells, so the public JSON API
is used. Each meeting stores the human source URL
https://pmg.org.za/committee-meeting/<id>/. Attendance rows are created ONLY
from the explicit attendance endpoint (member name + P/A/AP code) — never
inferred. Meetings whose attendance endpoint returns nothing are stored
without attendance and counted in the summary.

Dry-run semantics:
  --dry-run                 Fast and offline: prints the plan, no network,
                            no DB writes.
  --dry-run --discover      Fetches bounded API pages, no DB writes.

Examples:
    python scripts/ingest_committee_activity.py --dry-run
    python scripts/ingest_committee_activity.py --dry-run --discover --limit 20 --max-pages 2 --sleep 0.5
    python scripts/ingest_committee_activity.py --limit 20 --max-pages 2 --from-date 2026-01-01 --sleep 0.5
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
    fetch_page,
    meeting_attendance_api_url,
    parse_pmg_api_attendance,
    parse_pmg_api_meetings,
    pmg_meetings_api_url,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _fetch_json(fetch, url: str) -> dict:
    raw = fetch(url)
    return raw if isinstance(raw, dict) else json.loads(raw)


def run_committee_activity_ingest(
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
        "start_page": start_page,
        "pages_attempted": 0,
        "end_reached": False,
        "source_total": None,
        "listing_pages_fetched": 0,
        "attendance_pages_fetched": 0,
        "meetings_discovered": 0,
        "meetings_in_date_range": 0,
        "processed": 0,
        "created": 0,
        "updated": 0,
        "meetings_with_attendance": 0,
        "meetings_without_attendance": 0,
        "attendance_rows": 0,
        "failed": 0,
        "errors": [],
        "dry_run": dry_run,
        "discover": discover,
    }

    if dry_run and not discover:
        logger.info(
            "dry-run: skipping live discovery (pass --discover to enable). "
            "Would fetch up to %d listing page(s) of %s (limit %d meetings).",
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
        summary["pages_attempted"] += 1
        if payload.get("count") is not None:
            summary["source_total"] = payload["count"]
        page_meetings = parse_pmg_api_meetings(payload)
        meetings.extend(page_meetings)
        logger.info("page %d: %d meetings", page, len(page_meetings))
        if not payload.get("next"):
            summary["end_reached"] = True
            break
        if len(meetings) >= limit:
            break
        time.sleep(sleep)

    summary["meetings_discovered"] = len(meetings)
    if from_date:
        meetings = [m for m in meetings if m["date"] and m["date"] >= from_date]
    if to_date:
        meetings = [m for m in meetings if m["date"] and m["date"] <= to_date]
    summary["meetings_in_date_range"] = len(meetings)
    meetings = meetings[:limit]

    if db is None and not dry_run:
        raise ValueError("db session required for real runs")

    from sqlalchemy import select

    from app.models.committee_meeting import CommitteeMeeting
    from app.services.accountability_service import upsert_committee_meeting

    for meeting_data in meetings:
        try:
            attendance_url = meeting_attendance_api_url(meeting_data["api_id"])
            try:
                att_payload = _fetch_json(fetch, attendance_url)
                summary["attendance_pages_fetched"] += 1
                attendance = parse_pmg_api_attendance(att_payload, meeting_data["source_url"])
            except Exception as exc:
                # Attendance being unavailable is a modelled limitation, not a
                # fatal error: store the meeting without attendance.
                logger.warning("attendance unavailable for %s: %s", meeting_data["source_url"], exc)
                attendance = []
            meeting_data["attendance"] = attendance
            if attendance:
                summary["meetings_with_attendance"] += 1
            else:
                summary["meetings_without_attendance"] += 1

            if dry_run:
                logger.info(
                    "dry-run: would upsert meeting %r (%s, %d attendance rows, not written)",
                    meeting_data["title"][:70], meeting_data["date"], len(attendance),
                )
                summary["processed"] += 1
                summary["attendance_rows"] += len(attendance)
                continue

            existing = db.scalar(
                select(CommitteeMeeting).where(CommitteeMeeting.source_url == meeting_data["source_url"])
            )
            upsert_committee_meeting(db, meeting_data)
            db.commit()
            summary["processed"] += 1
            summary["attendance_rows"] += len(attendance)
            if existing:
                summary["updated"] += 1
            else:
                summary["created"] += 1
        except Exception as exc:
            if not dry_run:
                db.rollback()
            summary["failed"] += 1
            summary["errors"].append(
                {"url": meeting_data.get("source_url") or "", "error": str(exc), "type": type(exc).__name__}
            )
            logger.warning("FAILED %s: %s", meeting_data.get("source_url"), exc)
        time.sleep(sleep)

    return summary


def main() -> None:
    from ingest_bills import add_sweep_args, execute_with_optional_sweep, print_summary

    parser = argparse.ArgumentParser(description="Bounded PMG API committee meeting ingestion.")
    parser.add_argument("--limit", type=int, default=20, help="Max meetings to upsert.")
    parser.add_argument("--max-pages", type=int, default=2, help="Max listing API pages to fetch (50 meetings/page).")
    parser.add_argument("--start-page", type=int, default=0, help="Listing page to start from (direct mode).")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--from-date", default=None, help="Only meetings on/after this date (YYYY-MM-DD).")
    parser.add_argument("--to-date", default=None, help="Only meetings on/before this date (YYYY-MM-DD).")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes; offline unless --discover.")
    parser.add_argument("--discover", action="store_true", help="Allow live fetches during --dry-run.")
    parser.add_argument("--json-output", action="store_true", help="Print the summary as JSON.")
    add_sweep_args(parser)
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    summary = execute_with_optional_sweep(
        args,
        stream_name="pmg_committee_meetings",
        run_core=lambda db, start_page, max_pages: run_committee_activity_ingest(
            db,
            limit=args.limit if not args.sweep else max_pages * 50,
            max_pages=max_pages,
            start_page=start_page,
            sleep=args.sleep,
            from_date=from_date,
            to_date=to_date,
            dry_run=args.dry_run,
            discover=args.discover,
        ),
        run_type="committee_activity_ingest",
    )
    print_summary(summary, json_output=args.json_output)


if __name__ == "__main__":
    main()
