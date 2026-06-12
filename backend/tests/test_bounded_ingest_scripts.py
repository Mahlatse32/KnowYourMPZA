"""Fixture-driven tests for the PMG API votes / committee-activity ingestion:
dry-run network isolation, bounds, pagination, idempotency, no fabrication."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.ingestion.committee_activity import parse_pmg_api_attendance, parse_pmg_api_meetings
from app.ingestion.votes import build_vote_event_from_meeting, detect_vote_signal, extract_aggregate_counts
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.vote_event import VoteEvent
from app.models.vote_record import VoteRecord

from ingest_committee_activity import run_committee_activity_ingest
from ingest_votes import run_votes_ingest


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# PMG API fixtures (shapes verified against api.pmg.org.za)
# ---------------------------------------------------------------------------

def _meeting_item(mid: int, title: str, date_iso: str = "2026-06-01T09:00:00+00:00", committee: str = "Health"):
    return {
        "id": mid,
        "title": title,
        "date": date_iso,
        "committee": {"id": 1, "name": committee, "house": {"id": 3, "name": "National Assembly"}},
        "url": f"http://api.pmg.org.za/committee-meeting/{mid}/",
    }


MEETINGS_PAGE_0 = {
    "count": 4,
    "next": "https://api.pmg.org.za/committee-meeting/?page=1",
    "results": [
        _meeting_item(101, "Budget briefing"),
        _meeting_item(102, "Bill deliberations", "2026-05-15T09:00:00+00:00"),
    ],
}

MEETINGS_PAGE_1 = {
    "count": 4,
    "next": None,
    "results": [
        _meeting_item(103, "Oversight visit report", "2026-04-01T09:00:00+00:00"),
        _meeting_item(104, "Annual report", "2025-11-01T09:00:00+00:00"),
    ],
}

ATTENDANCE_PAYLOAD = {
    "count": 3,
    "next": None,
    "results": [
        {"attendance": "P", "chairperson": True, "member": {"name": "Dlamini, Ms A", "party": {"id": 1, "name": "ANC"}}},
        {"attendance": "A", "chairperson": False, "member": {"name": "Smith, Mr B", "party": {"id": 2, "name": "DA"}}},
        {"attendance": "AP", "chairperson": False, "member": {"name": "Zulu, Mr C", "party": None}},
    ],
}

EMPTY_ATTENDANCE = {"count": 0, "next": None, "results": []}

DETAIL_WITH_DIVISION = {
    "id": 102,
    "title": "Bill deliberations",
    "date": "2026-05-15T09:00:00+00:00",
    "committee": {"id": 1, "name": "Health", "house": {"id": 3, "name": "National Assembly"}},
    "body": "<p>The Bill was put to a vote: 8 votes in favour, 3 votes against and 1 abstention. The Bill was agreed to.</p>",
}

DETAIL_OUTCOME_ONLY = {
    "id": 103,
    "title": "Oversight visit report",
    "date": "2026-04-01T09:00:00+00:00",
    "committee": {"id": 1, "name": "Health", "house": {"id": 3, "name": "National Assembly"}},
    "body": "<p>Following a division, the report was adopted.</p>",
}

DETAIL_NO_VOTE = {
    "id": 101,
    "title": "Budget briefing",
    "date": "2026-06-01T09:00:00+00:00",
    "committee": {"id": 1, "name": "Health", "house": {"id": 3, "name": "National Assembly"}},
    "body": "<p>The committee was briefed on the budget. The agenda was adopted.</p>",
}


def _network_forbidden(url):
    raise AssertionError(f"unexpected network call to {url}")


def _api_fetch(attendance_by_id=None, details_by_id=None, fail_urls=()):
    """Simulated PMG API with pagination and per-URL failure injection."""
    attendance_by_id = attendance_by_id or {}
    details_by_id = details_by_id or {}

    def fetch(url):
        if url in fail_urls:
            raise ConnectionError("boom")
        if "page=0" in url:
            return json.dumps(MEETINGS_PAGE_0)
        if "page=1" in url:
            return json.dumps(MEETINGS_PAGE_1)
        if url.endswith("/attendance/"):
            mid = int(url.rstrip("/").split("/")[-2])
            return json.dumps(attendance_by_id.get(mid, EMPTY_ATTENDANCE))
        if "/committee-meeting/" in url:
            mid = int(url.rstrip("/").split("/")[-1])
            return json.dumps(details_by_id.get(mid, DETAIL_NO_VOTE))
        raise AssertionError(f"unexpected url {url}")

    return fetch


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def test_parse_pmg_api_meetings():
    meetings = parse_pmg_api_meetings(MEETINGS_PAGE_0)
    assert len(meetings) == 2
    m = meetings[0]
    assert m["title"] == "Budget briefing"
    assert m["date"] == date(2026, 6, 1)
    assert m["committee_name"] == "Health"
    assert m["house"] == "National Assembly"
    assert m["source_url"] == "https://pmg.org.za/committee-meeting/101/"


def test_parse_pmg_api_attendance_explicit_codes():
    rows = parse_pmg_api_attendance(ATTENDANCE_PAYLOAD, "https://pmg.org.za/committee-meeting/101/")
    assert len(rows) == 3
    by_name = {r["name_raw"]: r for r in rows}
    assert by_name["Dlamini, Ms A"]["attendance_status"] == "present"
    assert by_name["Dlamini, Ms A"]["party_name"] == "ANC"
    assert by_name["Smith, Mr B"]["attendance_status"] == "absent"
    assert by_name["Zulu, Mr C"]["attendance_status"] == "apology"
    assert by_name["Zulu, Mr C"]["party_name"] is None
    assert all(r["source_url"] == "https://pmg.org.za/committee-meeting/101/" for r in rows)


def test_parse_pmg_api_attendance_unknown_code_not_guessed():
    payload = {"results": [{"attendance": "ZZ", "member": {"name": "Mystery, Mr X"}}]}
    rows = parse_pmg_api_attendance(payload)
    assert rows[0]["attendance_status"] == "unknown"


def test_detect_vote_signal_requires_division_marker():
    # "adopted" alone (agendas, minutes) must NOT create a vote event.
    assert detect_vote_signal("The agenda was adopted.") is None
    assert detect_vote_signal("Following a division, the report was adopted.") == {
        "vote_type": "unknown", "result": "adopted",
    }
    assert detect_vote_signal("8 votes in favour. The Bill was agreed to.")["result"] == "agreed_to"


def test_extract_aggregate_counts_explicit_only():
    text = "The Bill was put to a vote: 8 votes in favour, 3 votes against and 1 abstention."
    records = extract_aggregate_counts(text, "https://x")
    assert {(r["vote_value"], r["count"]) for r in records} == {("yes", 8), ("no", 3), ("abstain", 1)}
    assert all(r["record_level"] == "aggregate" for r in records)
    assert all(r["politician_name"] is None and r["party_name"] is None for r in records)
    # no counts in text -> no records
    assert extract_aggregate_counts("The report was adopted after a division.") == []


def test_build_vote_event_from_meeting():
    event = build_vote_event_from_meeting(DETAIL_WITH_DIVISION)
    assert event is not None
    assert event["source_url"] == "https://pmg.org.za/committee-meeting/102/"
    assert event["chamber"] == "National Assembly"
    assert event["result"] == "agreed_to"
    assert len(event["vote_records"]) == 3

    assert build_vote_event_from_meeting(DETAIL_NO_VOTE) is None

    outcome_only = build_vote_event_from_meeting(DETAIL_OUTCOME_ONLY)
    assert outcome_only is not None
    assert outcome_only["vote_records"] == []


# ---------------------------------------------------------------------------
# Committee activity ingest
# ---------------------------------------------------------------------------

def test_meetings_dry_run_makes_no_network_calls(db):
    summary = run_committee_activity_ingest(db, dry_run=True, discover=False, sleep=0, fetch=_network_forbidden)
    assert summary["listing_pages_fetched"] == 0
    assert summary["failed"] == 0


def test_meetings_dry_run_discover_makes_no_db_writes(db):
    fetch = _api_fetch(attendance_by_id={101: ATTENDANCE_PAYLOAD})
    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, sleep=0, max_pages=2, fetch=fetch)
    db.commit()
    assert summary["processed"] == 4
    assert db.scalar(select(CommitteeMeeting).limit(1)) is None
    assert db.scalar(select(CommitteeAttendance).limit(1)) is None


def test_meetings_max_pages_enforced(db):
    calls = []

    def counting(url):
        calls.append(url)
        return _api_fetch()(url)

    run_committee_activity_ingest(db, dry_run=True, discover=True, max_pages=1, limit=50, sleep=0, fetch=counting)
    assert sum(1 for u in calls if "page=" in u) == 1


def test_meetings_limit_enforced(db):
    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, limit=1, max_pages=2, sleep=0, fetch=_api_fetch())
    assert summary["processed"] == 1


def test_meetings_pagination_follows_next(db):
    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, limit=10, max_pages=5, sleep=0, fetch=_api_fetch())
    # page 1 has next=None so only 2 pages exist
    assert summary["listing_pages_fetched"] == 2
    assert summary["meetings_discovered"] == 4


def test_meetings_date_filter(db):
    summary = run_committee_activity_ingest(
        db, dry_run=True, discover=True, limit=10, max_pages=2, sleep=0,
        from_date=date(2026, 5, 1), to_date=date(2026, 5, 31), fetch=_api_fetch(),
    )
    assert summary["meetings_in_date_range"] == 1


def test_meetings_real_run_creates_and_links_committee(db):
    db.add(Committee(name="Health", slug="health"))
    db.commit()
    fetch = _api_fetch(attendance_by_id={101: ATTENDANCE_PAYLOAD})
    summary = run_committee_activity_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    assert summary["created"] == 4
    assert summary["failed"] == 0
    meetings = list(db.scalars(select(CommitteeMeeting)))
    assert len(meetings) == 4
    assert all(m.source_url and m.source_url.startswith("https://pmg.org.za/committee-meeting/") for m in meetings)
    linked = [m for m in meetings if m.committee_id is not None]
    assert len(linked) == 4  # all fixtures use committee "Health"


def test_meetings_attendance_only_when_explicit(db):
    """Meeting 101 has explicit attendance; the rest return empty payloads —
    no attendance rows may be invented for them."""
    fetch = _api_fetch(attendance_by_id={101: ATTENDANCE_PAYLOAD})
    summary = run_committee_activity_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    assert summary["meetings_with_attendance"] == 1
    assert summary["meetings_without_attendance"] == 3
    rows = list(db.scalars(select(CommitteeAttendance)))
    assert len(rows) == 3  # exactly the explicit fixture rows
    meeting_101 = db.scalar(
        select(CommitteeMeeting).where(CommitteeMeeting.source_url == "https://pmg.org.za/committee-meeting/101/")
    )
    assert all(r.meeting_id == meeting_101.id for r in rows)


def test_meetings_upsert_is_idempotent(db):
    fetch = _api_fetch(attendance_by_id={101: ATTENDANCE_PAYLOAD})
    run_committee_activity_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    second = run_committee_activity_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    assert second["created"] == 0
    assert second["updated"] == 4
    assert len(list(db.scalars(select(CommitteeMeeting)))) == 4
    assert len(list(db.scalars(select(CommitteeAttendance)))) == 3


def test_meetings_attendance_failure_is_not_fatal(db):
    fetch = _api_fetch(fail_urls=("https://api.pmg.org.za/committee-meeting/101/attendance/",))
    summary = run_committee_activity_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    # meeting still stored, attendance recorded as unavailable
    assert summary["created"] == 4
    assert summary["failed"] == 0
    assert summary["meetings_without_attendance"] == 4


def test_meetings_listing_failure_recorded_as_structured_error(db):
    fetch = _api_fetch(fail_urls=("https://api.pmg.org.za/committee-meeting/?page=0",))
    summary = run_committee_activity_ingest(db, dry_run=False, sleep=0, fetch=fetch)
    assert summary["failed"] == 1
    err = summary["errors"][0]
    assert err["type"] == "ConnectionError"
    assert "page=0" in err["url"]


# ---------------------------------------------------------------------------
# Votes ingest
# ---------------------------------------------------------------------------

def test_votes_dry_run_makes_no_network_calls(db):
    summary = run_votes_ingest(db, dry_run=True, discover=False, sleep=0, fetch=_network_forbidden)
    assert summary["listing_pages_fetched"] == 0
    assert summary["failed"] == 0


def test_votes_dry_run_discover_makes_no_db_writes(db):
    fetch = _api_fetch(details_by_id={102: DETAIL_WITH_DIVISION, 103: DETAIL_OUTCOME_ONLY})
    summary = run_votes_ingest(db, dry_run=True, discover=True, sleep=0, max_pages=2, fetch=fetch)
    db.commit()
    assert summary["vote_events_found"] == 2
    assert db.scalar(select(VoteEvent).limit(1)) is None


def test_votes_limit_and_max_pages_enforced(db):
    calls = []

    def counting(url):
        calls.append(url)
        return _api_fetch(details_by_id={102: DETAIL_WITH_DIVISION})(url)

    summary = run_votes_ingest(db, dry_run=True, discover=True, limit=2, max_pages=1, sleep=0, fetch=counting)
    assert sum(1 for u in calls if "page=" in u) == 1
    assert summary["meetings_scanned"] == 2  # limit applied to detail scans


def test_votes_created_only_from_explicit_signals(db):
    fetch = _api_fetch(details_by_id={102: DETAIL_WITH_DIVISION, 103: DETAIL_OUTCOME_ONLY})
    summary = run_votes_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    # 4 meetings scanned; 101/104 have no division marker -> no events
    assert summary["meetings_scanned"] == 4
    assert summary["created"] == 2
    events = list(db.scalars(select(VoteEvent)))
    assert len(events) == 2
    assert all(e.source_url for e in events)


def test_vote_records_only_from_explicit_counts(db):
    fetch = _api_fetch(details_by_id={102: DETAIL_WITH_DIVISION, 103: DETAIL_OUTCOME_ONLY})
    run_votes_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    division_event = db.scalar(
        select(VoteEvent).where(VoteEvent.source_url == "https://pmg.org.za/committee-meeting/102/")
    )
    outcome_event = db.scalar(
        select(VoteEvent).where(VoteEvent.source_url == "https://pmg.org.za/committee-meeting/103/")
    )
    division_records = list(db.scalars(select(VoteRecord).where(VoteRecord.vote_event_id == division_event.id)))
    outcome_records = list(db.scalars(select(VoteRecord).where(VoteRecord.vote_event_id == outcome_event.id)))
    assert {(r.vote_value, r.count) for r in division_records} == {("yes", 8), ("no", 3), ("abstain", 1)}
    assert all(r.record_level == "aggregate" for r in division_records)
    assert all(r.politician_id is None and r.party_id is None for r in division_records)
    assert outcome_records == []  # outcome only -> VoteEvent only, nothing invented


def test_votes_ingest_is_idempotent(db):
    fetch = _api_fetch(details_by_id={102: DETAIL_WITH_DIVISION})
    run_votes_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    second = run_votes_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    assert second["created"] == 0
    assert second["updated"] == 1
    assert len(list(db.scalars(select(VoteEvent)))) == 1
    # aggregate records must not duplicate either
    assert len(list(db.scalars(select(VoteRecord)))) == 3


def test_votes_start_page_offsets_listing(db):
    calls = []

    def fetch(url):
        calls.append(url)
        if "page=3" in url:
            return json.dumps({**MEETINGS_PAGE_1, "next": None})
        if "/committee-meeting/" in url:
            return json.dumps(DETAIL_NO_VOTE)
        raise AssertionError(f"unexpected url {url}")

    run_votes_ingest(db, dry_run=True, discover=True, start_page=3, max_pages=1, sleep=0, fetch=fetch)
    assert any("page=3" in u for u in calls)


def test_votes_detail_failure_recorded_and_run_continues(db):
    fetch = _api_fetch(
        details_by_id={102: DETAIL_WITH_DIVISION},
        fail_urls=("https://api.pmg.org.za/committee-meeting/101/",),
    )
    summary = run_votes_ingest(db, dry_run=False, sleep=0, max_pages=2, fetch=fetch)
    assert summary["failed"] == 1
    assert summary["errors"][0]["type"] == "ConnectionError"
    assert summary["created"] == 1  # 102 still ingested