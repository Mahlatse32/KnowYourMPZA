"""Tests for legislative history backfill and dry-run network isolation."""
import sys
from datetime import date
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.ingestion.bills import (
    bill_detail_api_url,
    fetch_page,
    parse_bill_history,
    parse_pmg_api_bill,
    parse_pmg_api_bill_events,
    parse_pmg_api_bills,
)
from app.models.bill import Bill
from app.models.bill_event import BillEvent
from app.services.accountability_service import upsert_bill

from backfill_legislative_history import run_backfill
from ingest_people_assembly_full import should_discover


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


@pytest.fixture()
def seeded_bill(db):
    bill = upsert_bill(
        db,
        {
            "title": "History Test Bill",
            "bill_number": "B1",
            "year": 2025,
            "house": "National Assembly",
            "status": "introduced",
            "source_url": "https://pmg.org.za/bills/history-test/",
            "source_type": "pmg",
            "events": [],
        },
    )
    db.commit()
    return bill


BILL_HISTORY_HTML = """
<html><body>
<h1>History Test Bill</h1>
<table>
<tr><td>15 February 2025</td><td>Bill introduced in the National Assembly</td></tr>
<tr><td>20 March 2025</td><td>Referred to Portfolio Committee on Health</td></tr>
<tr><td>10 June 2025</td><td>Second reading debate</td></tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_bill_history_extracts_events():
    events = parse_bill_history(BILL_HISTORY_HTML, "https://pmg.org.za/bills/history-test/")
    assert len(events) == 3
    types = [e["event_type"] for e in events]
    assert "introduced" in types
    assert "committee_referral" in types
    assert "second_reading" in types


def test_parse_bill_history_extracts_dates():
    events = parse_bill_history(BILL_HISTORY_HTML, "https://pmg.org.za/bills/history-test/")
    dates = [e["event_date"] for e in events]
    assert date(2025, 2, 15) in dates


def test_parse_bill_history_empty_page():
    assert parse_bill_history("<html><body></body></html>", "https://x") == []


# ---------------------------------------------------------------------------
# Dry-run network isolation
# ---------------------------------------------------------------------------

def _network_forbidden(url):
    raise AssertionError(f"unexpected network call to {url}")


def test_dry_run_makes_no_network_calls(db, seeded_bill):
    """Plain dry-run must never fetch, even with bills available."""
    summary = run_backfill(db, dry_run=True, discover=False, sleep=0, fetch=_network_forbidden)
    assert summary["bills_selected"] == 1
    assert summary["pages_fetched"] == 0
    assert summary["failed"] == 0


def test_dry_run_makes_no_db_writes(db, seeded_bill):
    run_backfill(db, dry_run=True, discover=True, sleep=0, fetch=lambda url: BILL_HISTORY_HTML)
    db.commit()
    assert db.scalar(select(BillEvent).limit(1)) is None


def test_dry_run_with_discover_fetches_and_parses(db, seeded_bill):
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return BILL_HISTORY_HTML

    summary = run_backfill(db, dry_run=True, discover=True, sleep=0, fetch=counting_fetch)
    assert calls == [seeded_bill.source_url]
    assert summary["pages_fetched"] == 1
    assert summary["events_parsed"] == 3


def test_discover_respects_max_pages(db):
    for i in range(5):
        upsert_bill(
            db,
            {
                "title": f"Bill {i}",
                "bill_number": f"B{i + 10}",
                "year": 2025,
                "house": None,
                "status": "introduced",
                "source_url": f"https://pmg.org.za/bills/bounded-{i}/",
                "source_type": "pmg",
                "events": [],
            },
        )
    db.commit()
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return BILL_HISTORY_HTML

    summary = run_backfill(db, dry_run=True, discover=True, max_pages=2, sleep=0, fetch=counting_fetch)
    assert len(calls) == 2
    assert summary["pages_fetched"] == 2


def test_discover_respects_limit(db):
    for i in range(5):
        upsert_bill(
            db,
            {
                "title": f"Limit Bill {i}",
                "bill_number": f"B{i + 20}",
                "year": 2025,
                "house": None,
                "status": "introduced",
                "source_url": f"https://pmg.org.za/bills/limit-{i}/",
                "source_type": "pmg",
                "events": [],
            },
        )
    db.commit()
    summary = run_backfill(db, dry_run=True, discover=True, limit=3, sleep=0, fetch=lambda url: BILL_HISTORY_HTML)
    assert summary["bills_selected"] == 3


# ---------------------------------------------------------------------------
# Real backfill writes and is idempotent
# ---------------------------------------------------------------------------

def test_backfill_writes_events(db, seeded_bill):
    summary = run_backfill(db, dry_run=False, sleep=0, fetch=lambda url: BILL_HISTORY_HTML)
    assert summary["events_created"] == 3
    events = list(db.scalars(select(BillEvent).where(BillEvent.bill_id == seeded_bill.id)))
    assert len(events) == 3
    assert all(e.source_url == seeded_bill.source_url for e in events)


def test_backfill_is_idempotent(db, seeded_bill):
    run_backfill(db, dry_run=False, sleep=0, fetch=lambda url: BILL_HISTORY_HTML)
    summary = run_backfill(db, dry_run=False, sleep=0, fetch=lambda url: BILL_HISTORY_HTML)
    assert summary["events_created"] == 0
    assert summary["events_existing"] == 3
    events = list(db.scalars(select(BillEvent).where(BillEvent.bill_id == seeded_bill.id)))
    assert len(events) == 3


def test_backfill_failure_is_not_fatal(db, seeded_bill):
    def broken_fetch(url):
        raise ConnectionError("boom")

    summary = run_backfill(db, dry_run=False, sleep=0, fetch=broken_fetch)
    assert summary["failed"] == 1
    assert summary["events_created"] == 0


def test_backfill_bill_timeout_is_not_fatal(db, seeded_bill):
    second = upsert_bill(
        db,
        {
            "title": "Second History Bill",
            "bill_number": "B2",
            "year": 2025,
            "house": "National Assembly",
            "status": "introduced",
            "source_url": "https://pmg.org.za/bills/history-second/",
            "source_type": "pmg",
            "events": [],
        },
    )
    db.commit()

    def fetch(url):
        if url == seeded_bill.source_url:
            raise requests.Timeout("timed out")
        return BILL_HISTORY_HTML

    summary = run_backfill(db, dry_run=False, sleep=0, fetch=fetch)
    assert summary["failed"] == 1
    assert summary["errors"][0]["type"] == "Timeout"
    assert summary["events_created"] == 3
    events = list(db.scalars(select(BillEvent).where(BillEvent.bill_id == second.id)))
    assert len(events) == 3


def test_fetch_page_retries_transient_timeout(monkeypatch):
    calls = []
    sleeps = []

    class Response:
        text = '{"ok": true}'

        def raise_for_status(self):
            return None

    def get(url, *, timeout, headers):
        calls.append({"url": url, "timeout": timeout, "headers": headers})
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return Response()

    monkeypatch.setattr("app.ingestion.bills.requests.get", get)
    monkeypatch.setattr("app.ingestion.bills.time.sleep", lambda delay: sleeps.append(delay))

    assert fetch_page("https://api.pmg.org.za/bill/?page=1") == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["timeout"] == 45
    assert sleeps == [1.0]


# ---------------------------------------------------------------------------
# Discovery gate for People's Assembly full ingestion
# ---------------------------------------------------------------------------

def test_should_discover_dry_run_default_off():
    assert should_discover(dry_run=True, discover=False, discover_only=False) is False


def test_should_discover_dry_run_with_flag():
    assert should_discover(dry_run=True, discover=True, discover_only=False) is True


def test_should_discover_discover_only():
    assert should_discover(dry_run=True, discover=False, discover_only=True) is True


def test_should_discover_real_run():
    assert should_discover(dry_run=False, discover=False, discover_only=False) is True


# ---------------------------------------------------------------------------
# PMG API parsing
# ---------------------------------------------------------------------------

PMG_API_BILL = {
    "id": 1000,
    "title": "Appropriation Bill",
    "number": 4,
    "year": 2021,
    "code": "B4-2021",
    "date_of_introduction": "2021-02-24",
    "date_of_assent": "2021-07-20",
    "act_name": "Act 8 of 2021",
    "status": {"id": 7, "name": "act-commenced", "description": "Act commenced"},
    "events": [
        {"date": "2021-02-24T02:02:00+00:00", "type": "bill-introduced", "title": "Bill introduced to the National Assembly"},
        {"date": "2021-05-04T07:50:00+00:00", "type": "committee-meeting", "title": "National Treasury briefing"},
    ],
}


def test_parse_pmg_api_bill_maps_fields():
    bill = parse_pmg_api_bill(PMG_API_BILL)
    assert bill["title"] == "Appropriation Bill"
    assert bill["bill_number"] == "B4-2021"
    assert bill["year"] == 2021
    assert bill["status"] == "assented"  # "act-commenced" contains "act"
    assert bill["introduced_date"] == date(2021, 2, 24)
    assert bill["assented_date"] == date(2021, 7, 20)
    assert bill["source_url"] == "https://pmg.org.za/bill/1000/"
    assert bill["source_type"] == "pmg-api"
    assert len(bill["events"]) == 2


def test_parse_pmg_api_bill_draft_has_no_bill_number():
    """Drafts share the placeholder code X-<year>; storing it as bill_number
    would collapse distinct drafts under uq_bill_number_year_house."""
    draft = {**PMG_API_BILL, "id": 1349, "number": None, "code": "X-2026", "year": 2026}
    bill = parse_pmg_api_bill(draft)
    assert bill["bill_number"] is None
    assert bill["source_url"] == "https://pmg.org.za/bill/1349/"


def test_parse_pmg_api_bills_listing():
    payload = {"count": 2, "next": None, "results": [PMG_API_BILL, {**PMG_API_BILL, "id": 1001, "status": None, "events": []}]}
    bills = parse_pmg_api_bills(payload)
    assert len(bills) == 2
    assert bills[1]["status"] == "unknown"
    assert bills[1]["source_url"] == "https://pmg.org.za/bill/1001/"


def test_parse_pmg_api_bill_events():
    events = parse_pmg_api_bill_events(PMG_API_BILL)
    assert len(events) == 2
    assert events[0]["event_type"] == "bill-introduced"
    assert events[0]["event_date"] == date(2021, 2, 24)
    assert all(e["source_url"] == "https://pmg.org.za/bill/1000/" for e in events)


def test_bill_detail_api_url():
    assert bill_detail_api_url("https://pmg.org.za/bill/1000/") == "https://api.pmg.org.za/bill/1000/"
    assert bill_detail_api_url("https://www.parliament.gov.za/bills") is None
    assert bill_detail_api_url(None) is None


def test_backfill_uses_api_for_pmg_bills(db):
    """Bills with pmg.org.za/bill/<id>/ source URLs fetch the JSON API detail."""
    import json

    bill = upsert_bill(
        db,
        {
            "title": "API Backfill Bill",
            "bill_number": "B4-2021",
            "year": 2021,
            "house": None,
            "status": "assented",
            "source_url": "https://pmg.org.za/bill/1000/",
            "source_type": "pmg-api",
            "events": [],
        },
    )
    db.commit()
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return json.dumps(PMG_API_BILL)

    summary = run_backfill(db, dry_run=False, sleep=0, fetch=fake_fetch)
    assert calls == ["https://api.pmg.org.za/bill/1000/"]
    assert summary["events_created"] == 2
    events = list(db.scalars(select(BillEvent).where(BillEvent.bill_id == bill.id)))
    assert {e.event_type for e in events} == {"bill-introduced", "committee-meeting"}
