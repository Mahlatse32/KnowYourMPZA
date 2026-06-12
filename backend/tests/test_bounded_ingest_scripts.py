"""Tests for bounded votes / committee-activity ingestion scripts:
dry-run network isolation, limits, idempotency, and correct run tracking."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
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


VOTES_INDEX_HTML = """
<html><body>
<a href="/vote/100">Vote 100</a>
<a href="/vote/101">Vote 101</a>
<a href="/vote/102">Vote 102</a>
</body></html>
"""

VOTE_EVENT_HTML = """
<html><body>
<h1>Test Bill: Second Reading Vote</h1>
<span class="date">15 October 2025</span>
<p>The bill was agreed to.</p>
<table>
<tr><th>Party</th><th>Yes</th><th>No</th></tr>
<tr><td>ANC</td><td>150</td><td>0</td></tr>
<tr><td>DA</td><td>0</td><td>80</td></tr>
</table>
</body></html>
"""

MEETINGS_INDEX_HTML = """
<html><body>
<a href="/committee-meeting/1001">Meeting 1</a>
<a href="/committee-meeting/1002">Meeting 2</a>
<a href="/committee-meeting/1003">Meeting 3</a>
</body></html>
"""

MEETING_HTML = """
<html><body>
<h1>Portfolio Committee on Testing: Briefing</h1>
<span class="date">3 March 2025</span>
<p>Members present:</p>
<ul><li>Ms Tester (ANC)</li></ul>
</body></html>
"""


def _network_forbidden(url):
    raise AssertionError(f"unexpected network call to {url}")


def _fake_fetch(index_html, page_html):
    def fetch(url):
        if url.rstrip("/").endswith(("votes", "committee-meetings")):
            return index_html
        return page_html

    return fetch


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

def test_votes_dry_run_makes_no_network_calls(db):
    summary = run_votes_ingest(db, dry_run=True, discover=False, sleep=0, fetch=_network_forbidden)
    assert summary["pages_fetched"] == 0
    assert summary["failed"] == 0


def test_votes_dry_run_discover_makes_no_db_writes(db):
    fetch = _fake_fetch(VOTES_INDEX_HTML, VOTE_EVENT_HTML)
    summary = run_votes_ingest(db, dry_run=True, discover=True, sleep=0, fetch=fetch)
    db.commit()
    assert summary["processed"] == 3
    assert db.scalar(select(VoteEvent).limit(1)) is None


def test_votes_discover_respects_limit_and_max_pages(db):
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return VOTES_INDEX_HTML if "votes" in url else VOTE_EVENT_HTML

    summary = run_votes_ingest(db, dry_run=True, discover=True, limit=2, sleep=0, fetch=counting_fetch)
    assert summary["processed"] == 2
    assert len(calls) == 3  # 1 index + 2 vote pages

    calls.clear()
    summary = run_votes_ingest(db, dry_run=True, discover=True, limit=10, max_pages=1, sleep=0, fetch=counting_fetch)
    assert summary["pages_fetched"] == 2  # index + 1 vote page


def test_votes_real_run_writes_and_is_idempotent(db):
    fetch = _fake_fetch(VOTES_INDEX_HTML, VOTE_EVENT_HTML)
    first = run_votes_ingest(db, dry_run=False, sleep=0, fetch=fetch)
    assert first["created"] == 3
    assert first["failed"] == 0
    events = list(db.scalars(select(VoteEvent)))
    assert len(events) == 3
    assert all(e.source_url for e in events)
    records = list(db.scalars(select(VoteRecord)))
    assert len(records) > 0
    assert all(r.record_level == "party" for r in records)

    second = run_votes_ingest(db, dry_run=False, sleep=0, fetch=fetch)
    assert second["created"] == 0
    assert second["updated"] == 3
    assert len(list(db.scalars(select(VoteEvent)))) == 3


def test_votes_failure_is_not_fatal(db):
    def broken_fetch(url):
        if "votes" in url:
            return VOTES_INDEX_HTML
        raise ConnectionError("boom")

    summary = run_votes_ingest(db, dry_run=False, sleep=0, fetch=broken_fetch)
    assert summary["failed"] == 3
    assert summary["created"] == 0
    assert all(e["type"] == "ConnectionError" for e in summary["errors"])


# ---------------------------------------------------------------------------
# Committee activity
# ---------------------------------------------------------------------------

def test_meetings_dry_run_makes_no_network_calls(db):
    summary = run_committee_activity_ingest(db, dry_run=True, discover=False, sleep=0, fetch=_network_forbidden)
    assert summary["pages_fetched"] == 0
    assert summary["failed"] == 0


def test_meetings_dry_run_discover_makes_no_db_writes(db):
    fetch = _fake_fetch(MEETINGS_INDEX_HTML, MEETING_HTML)
    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, sleep=0, fetch=fetch)
    db.commit()
    assert summary["processed"] == 3
    assert db.scalar(select(CommitteeMeeting).limit(1)) is None


def test_meetings_discover_respects_limit_and_max_pages(db):
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return MEETINGS_INDEX_HTML if url.rstrip("/").endswith("committee-meetings") else MEETING_HTML

    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, limit=2, sleep=0, fetch=counting_fetch)
    assert summary["processed"] == 2
    assert len(calls) == 3  # 1 index + 2 meeting pages

    calls.clear()
    summary = run_committee_activity_ingest(db, dry_run=True, discover=True, limit=10, max_pages=1, sleep=0, fetch=counting_fetch)
    assert summary["pages_fetched"] == 2  # index + 1 meeting page


def test_meetings_real_run_writes_and_is_idempotent(db):
    fetch = _fake_fetch(MEETINGS_INDEX_HTML, MEETING_HTML)
    first = run_committee_activity_ingest(db, dry_run=False, sleep=0, fetch=fetch)
    assert first["created"] == 3
    assert first["failed"] == 0
    meetings = list(db.scalars(select(CommitteeMeeting)))
    assert len(meetings) == 3
    assert all(m.source_url for m in meetings)
    attendance = list(db.scalars(select(CommitteeAttendance)))
    assert len(attendance) == 3
    assert all(a.name_raw for a in attendance)

    second = run_committee_activity_ingest(db, dry_run=False, sleep=0, fetch=fetch)
    assert second["created"] == 0
    assert second["updated"] == 3
    assert len(list(db.scalars(select(CommitteeMeeting)))) == 3


def test_meetings_failure_is_not_fatal(db):
    def broken_fetch(url):
        if url.rstrip("/").endswith("committee-meetings"):
            return MEETINGS_INDEX_HTML
        raise ConnectionError("boom")

    summary = run_committee_activity_ingest(db, dry_run=False, sleep=0, fetch=broken_fetch)
    assert summary["failed"] == 3
    assert summary["created"] == 0
