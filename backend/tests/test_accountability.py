"""Tests for the accountability data layer: models, parsers, service, and endpoints."""
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.bill import Bill
from app.models.bill_event import BillEvent
from app.models.committee_meeting import CommitteeMeeting
from app.models.committee_attendance import CommitteeAttendance
from app.models.party import Party
from app.models.politician import Politician
from app.models.vote_event import VoteEvent
from app.models.vote_record import VoteRecord
from app.ingestion.bills import parse_pmg_bills, parse_parliament_bills, _normalize_status, _parse_bill_number, _parse_year
from app.ingestion.votes import parse_pmg_votes_index, parse_pmg_vote_event, _normalize_vote_value, _normalize_result
from app.ingestion.committee_activity import parse_pmg_meetings_index, parse_pmg_meeting, _normalize_attendance
from app.services.accountability_service import (
    upsert_bill,
    upsert_vote_event,
    upsert_committee_meeting,
    list_bills,
    list_vote_events,
    list_committee_meetings,
)


# ---------------------------------------------------------------------------
# Test DB fixture (SQLite in-memory)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(db_engine):
    Session_ = sessionmaker(bind=db_engine)
    session = Session_()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Ingestion parsers — bills
# ---------------------------------------------------------------------------

PMG_BILLS_HTML = """
<html><body>
<table>
<tr><th>Bill</th><th>Year</th><th>Status</th></tr>
<tr><td><a href="/bills/123/">National Health Insurance Bill B11</a></td><td>2023</td><td>Introduced</td></tr>
<tr><td><a href="/bills/456/">Schools Act B5A</a></td><td>2022</td><td>Assented</td></tr>
</table>
</body></html>
"""

PARLIAMENT_BILLS_HTML = """
<html><body>
<a href="/bill/200">Basic Education Laws Amendment Bill</a>
<a href="/bill/201">National Council on Gender-Based Violence Bill</a>
</body></html>
"""


def test_parse_pmg_bills_extracts_rows():
    bills = parse_pmg_bills(PMG_BILLS_HTML)
    assert len(bills) == 2
    titles = [b["title"] for b in bills]
    assert any("Health Insurance" in t for t in titles)


def test_parse_pmg_bills_status_normalization():
    bills = parse_pmg_bills(PMG_BILLS_HTML)
    statuses = {b["title"]: b["status"] for b in bills}
    assert any(v == "introduced" for v in statuses.values())
    assert any(v == "assented" for v in statuses.values())


def test_parse_pmg_bills_bill_number_extraction():
    bills = parse_pmg_bills(PMG_BILLS_HTML)
    bill_numbers = [b.get("bill_number") for b in bills]
    assert any(bn and "B11" in bn for bn in bill_numbers)


def test_parse_parliament_bills_extracts_links():
    bills = parse_parliament_bills(PARLIAMENT_BILLS_HTML)
    assert len(bills) >= 2


def test_normalize_status_known():
    assert _normalize_status("Passed by National Assembly") == "passed"
    assert _normalize_status("Assented to by President") == "assented"
    assert _normalize_status("Withdrawn") == "withdrawn"


def test_normalize_status_unknown():
    assert _normalize_status("") == "unknown"
    assert _normalize_status("Some weird status") == "unknown"


def test_parse_bill_number():
    assert _parse_bill_number("NHI Bill B11-2023") == "B11"
    assert _parse_bill_number("No bill number here") is None


def test_parse_year():
    assert _parse_year("Bill B5 of 2022") == 2022
    assert _parse_year("nothing") is None


# ---------------------------------------------------------------------------
# Ingestion parsers — votes
# ---------------------------------------------------------------------------

PMG_VOTES_INDEX_HTML = """
<html><body>
<a href="/vote/100">Vote 100</a>
<a href="/division/200">Division 200</a>
<a href="/other">Not a vote</a>
</body></html>
"""

PMG_VOTE_EVENT_HTML = """
<html><body>
<h1>National Health Insurance Bill: Final Reading Vote</h1>
<span class="date">15 October 2023</span>
<p>The bill was agreed to.</p>
<table>
<tr><th>Party</th><th>Yes</th><th>No</th></tr>
<tr><td>ANC</td><td>210</td><td>0</td></tr>
<tr><td>DA</td><td>0</td><td>84</td></tr>
</table>
</body></html>
"""


def test_parse_pmg_votes_index_returns_urls():
    urls = parse_pmg_votes_index(PMG_VOTES_INDEX_HTML)
    assert len(urls) == 2
    assert all("pmg.org.za" in u for u in urls)


def test_parse_pmg_vote_event_title():
    event = parse_pmg_vote_event(PMG_VOTE_EVENT_HTML, "https://pmg.org.za/vote/100")
    assert event is not None
    assert "National Health Insurance" in event["title"]


def test_parse_pmg_vote_event_records():
    event = parse_pmg_vote_event(PMG_VOTE_EVENT_HTML, "https://pmg.org.za/vote/100")
    assert len(event["vote_records"]) >= 2
    party_names = {r["party_name"] for r in event["vote_records"]}
    assert "ANC" in party_names
    assert "DA" in party_names


def test_parse_pmg_vote_event_no_h1():
    result = parse_pmg_vote_event("<html><body><p>nothing</p></body></html>", "https://pmg.org.za/vote/999")
    assert result is None


def test_normalize_vote_value():
    assert _normalize_vote_value("Yes") == "yes"
    assert _normalize_vote_value("Nay") == "no"
    assert _normalize_vote_value("Abstain") == "abstain"
    assert _normalize_vote_value("unknown_value") == "unknown"


def test_normalize_result():
    assert _normalize_result("The motion was agreed to") == "agreed_to"
    assert _normalize_result("Motion negatived") == "negatived"
    assert _normalize_result("") is None


# ---------------------------------------------------------------------------
# Ingestion parsers — committee meetings
# ---------------------------------------------------------------------------

PMG_MEETINGS_INDEX_HTML = """
<html><body>
<a href="/committee-meeting/1001">Meeting 1</a>
<a href="/committee-meeting/1002">Meeting 2</a>
<a href="/other">Not a meeting</a>
</body></html>
"""

PMG_MEETING_HTML = """
<html><body>
<h1>Portfolio Committee on Health: Quarterly Briefing</h1>
<span class="date">3 March 2024</span>
<div class="summary">The committee was briefed on budget plans.</div>
<p>Members present:</p>
<ul>
<li>Ms Nkosi (ANC)</li>
<li>Mr Van der Berg (DA)</li>
</ul>
<p>Apologies:</p>
<ul><li>Dr Sithole (EFF)</li></ul>
</body></html>
"""


def test_parse_pmg_meetings_index_returns_urls():
    urls = parse_pmg_meetings_index(PMG_MEETINGS_INDEX_HTML)
    assert len(urls) == 2


def test_parse_pmg_meeting_title():
    result = parse_pmg_meeting(PMG_MEETING_HTML, "https://pmg.org.za/committee-meeting/1001")
    assert result is not None
    assert "Portfolio Committee" in result["title"]


def test_parse_pmg_meeting_no_h1():
    result = parse_pmg_meeting("<html><body></body></html>", "https://pmg.org.za/committee-meeting/9")
    assert result is None


def test_normalize_attendance():
    assert _normalize_attendance("present") == "present"
    assert _normalize_attendance("attended") == "present"
    assert _normalize_attendance("apologies") == "apology"
    assert _normalize_attendance("absent") == "absent"
    assert _normalize_attendance("xyz") == "unknown"


# ---------------------------------------------------------------------------
# Service layer — bills
# ---------------------------------------------------------------------------

def test_upsert_bill_creates(db):
    data = {
        "title": "Test Bill",
        "bill_number": "B99",
        "year": 2025,
        "house": "National Assembly",
        "status": "introduced",
        "source_url": "https://pmg.org.za/bills/test-bill",
        "source_type": "pmg",
        "events": [],
    }
    bill = upsert_bill(db, data)
    db.commit()
    assert bill.id is not None
    assert bill.title == "Test Bill"
    assert bill.status == "introduced"


def test_upsert_bill_is_idempotent(db):
    data = {
        "title": "Idempotent Bill",
        "bill_number": "B88",
        "year": 2025,
        "house": "NCOP",
        "status": "introduced",
        "source_url": "https://pmg.org.za/bills/idempotent",
        "source_type": "pmg",
        "events": [],
    }
    b1 = upsert_bill(db, data)
    db.commit()
    data["status"] = "passed"
    b2 = upsert_bill(db, data)
    db.commit()
    assert b1.id == b2.id
    assert b2.status == "passed"


def test_list_bills_filters_by_status(db):
    data = {
        "title": "Filter Test Bill",
        "bill_number": "B77",
        "year": 2024,
        "house": None,
        "status": "assented",
        "source_url": "https://pmg.org.za/bills/filter-test",
        "source_type": "pmg",
        "events": [],
    }
    upsert_bill(db, data)
    db.commit()
    results = list_bills(db, status="assented")
    assert any(b.bill_number == "B77" for b in results)
    none_results = list_bills(db, status="withdrawn")
    assert not any(b.bill_number == "B77" for b in none_results)


# ---------------------------------------------------------------------------
# Service layer — vote events
# ---------------------------------------------------------------------------

def test_upsert_vote_event_creates(db):
    data = {
        "title": "Test Vote",
        "date": date(2025, 3, 1),
        "chamber": "National Assembly",
        "vote_type": "bill_vote",
        "result": "agreed_to",
        "source_url": "https://pmg.org.za/vote/test-vote",
        "source_type": "pmg",
        "vote_records": [],
    }
    event = upsert_vote_event(db, data)
    db.commit()
    assert event.id is not None
    assert event.chamber == "National Assembly"


def test_upsert_vote_event_is_idempotent(db):
    data = {
        "title": "Idempotent Vote",
        "date": date(2025, 4, 1),
        "chamber": "NCOP",
        "vote_type": "motion",
        "result": None,
        "source_url": "https://pmg.org.za/vote/idempotent-vote",
        "source_type": "pmg",
        "vote_records": [],
    }
    e1 = upsert_vote_event(db, data)
    db.commit()
    data["result"] = "negatived"
    e2 = upsert_vote_event(db, data)
    db.commit()
    assert e1.id == e2.id
    assert e2.result == "negatived"


# ---------------------------------------------------------------------------
# Service layer — committee meetings
# ---------------------------------------------------------------------------

def test_upsert_committee_meeting_creates(db):
    data = {
        "title": "Test Committee Meeting",
        "date": date(2024, 6, 10),
        "summary": "Budget briefing.",
        "source_url": "https://pmg.org.za/committee-meeting/test",
        "pmg_url": "https://pmg.org.za/committee-meeting/test",
        "source_type": "pmg",
        "attendance": [],
    }
    meeting = upsert_committee_meeting(db, data)
    db.commit()
    assert meeting.id is not None
    assert meeting.title == "Test Committee Meeting"


def test_upsert_committee_meeting_is_idempotent(db):
    data = {
        "title": "Idempotent Meeting",
        "date": date(2024, 7, 1),
        "summary": "Old summary.",
        "source_url": "https://pmg.org.za/committee-meeting/idempotent",
        "pmg_url": "https://pmg.org.za/committee-meeting/idempotent",
        "source_type": "pmg",
        "attendance": [],
    }
    m1 = upsert_committee_meeting(db, data)
    db.commit()
    data["summary"] = "Updated summary."
    m2 = upsert_committee_meeting(db, data)
    db.commit()
    assert m1.id == m2.id
    assert m2.summary == "Updated summary."


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def test_get_bills_endpoint_returns_list(client):
    resp = client.get("/bills")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_bills_endpoint_filter_by_status(client, db):
    data = {
        "title": "API Filter Bill",
        "bill_number": "B66",
        "year": 2026,
        "house": None,
        "status": "withdrawn",
        "source_url": "https://pmg.org.za/bills/api-filter",
        "source_type": "pmg",
        "events": [],
    }
    upsert_bill(db, data)
    db.commit()
    resp = client.get("/bills?status=withdrawn")
    assert resp.status_code == 200
    bills = resp.json()
    assert any(b["bill_number"] == "B66" for b in bills)


def test_get_bill_by_id_not_found(client):
    resp = client.get(f"/bills/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_bill_by_id(client, db):
    data = {
        "title": "ID Lookup Bill",
        "bill_number": "B55",
        "year": 2026,
        "house": None,
        "status": "introduced",
        "source_url": "https://pmg.org.za/bills/id-lookup",
        "source_type": "pmg",
        "events": [],
    }
    bill = upsert_bill(db, data)
    db.commit()
    resp = client.get(f"/bills/{bill.id}")
    assert resp.status_code == 200
    assert resp.json()["bill_number"] == "B55"


def test_get_bill_events_endpoint(client, db):
    data = {
        "title": "Events Bill",
        "bill_number": "B44",
        "year": 2026,
        "house": None,
        "status": "introduced",
        "source_url": "https://pmg.org.za/bills/events-bill",
        "source_type": "pmg",
        "events": [
            {
                "event_type": "introduced",
                "event_date": date(2026, 1, 15),
                "description": "Bill introduced",
                "source_url": "https://pmg.org.za/bills/events-bill#event1",
            }
        ],
    }
    bill = upsert_bill(db, data)
    db.commit()
    resp = client.get(f"/bills/{bill.id}/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["event_type"] == "introduced"


def test_get_votes_endpoint_returns_list(client):
    resp = client.get("/votes")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_vote_by_id_not_found(client):
    resp = client.get(f"/votes/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_meetings_endpoint_returns_list(client):
    resp = client.get("/committees/meetings")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_meeting_by_id_not_found(client):
    resp = client.get(f"/committees/meetings/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_meeting_attendance_endpoint(client, db):
    meeting_data = {
        "title": "Attendance Test Meeting",
        "date": date(2025, 5, 20),
        "summary": None,
        "source_url": "https://pmg.org.za/committee-meeting/attendance-test",
        "pmg_url": "https://pmg.org.za/committee-meeting/attendance-test",
        "source_type": "pmg",
        "attendance": [
            {"name_raw": "Ms Dlamini", "attendance_status": "present", "confidence": 0.9, "source_url": None},
        ],
    }
    meeting = upsert_committee_meeting(db, meeting_data)
    db.commit()
    resp = client.get(f"/committees/meetings/{meeting.id}/attendance")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["name_raw"] == "Ms Dlamini"
    assert records[0]["attendance_status"] == "present"
