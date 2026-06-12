"""Tests for legislative history backfill and dry-run network isolation."""
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.ingestion.bills import parse_bill_history
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
