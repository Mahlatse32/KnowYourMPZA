import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import SessionLocal
from app.main import app
from app.models import Base
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.party import Party
from app.models.politician import Politician
from app.services.politician_service import get_politician_attendance_summary


client = TestClient(app)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _politician(db, slug_suffix: str = "") -> Politician:
    party = Party(name="Test Party", short_name=f"TP{slug_suffix or '1'}", source_url="https://pmg.org.za/")
    db.add(party)
    db.flush()
    politician = Politician(
        full_name="A Tester",
        display_name="A Tester",
        slug=f"a-tester{slug_suffix}",
        party=party,
    )
    db.add(politician)
    db.flush()
    return politician


def _meeting(db, title: str, url: str, meeting_date: date | None, committee: Committee | None = None, committee_name: str | None = None) -> CommitteeMeeting:
    meeting = CommitteeMeeting(
        committee_id=committee.id if committee else None,
        committee_name=committee_name,
        title=title,
        date=meeting_date,
        source_url=url,
    )
    db.add(meeting)
    db.flush()
    return meeting


def _attend(db, meeting: CommitteeMeeting, politician: Politician, status: str) -> None:
    db.add(
        CommitteeAttendance(
            meeting_id=meeting.id,
            politician_id=politician.id,
            name_raw="Tester, Ms A",
            attendance_status=status,
            source_url=meeting.source_url,
        )
    )
    db.flush()


def test_attendance_summary_aggregates_by_status_and_committee(db):
    politician = _politician(db)
    committee = Committee(name="Basic Education", slug="basic-education", source_url="https://pmg.org.za/committee/1/")
    db.add(committee)
    db.flush()

    m1 = _meeting(db, "Budget briefing", "https://pmg.org.za/committee-meeting/a1/", date(2026, 6, 1), committee=committee)
    m2 = _meeting(db, "Oversight visit report", "https://pmg.org.za/committee-meeting/a2/", date(2026, 6, 10), committee=committee)
    m3 = _meeting(db, "Unlinked committee meeting", "https://pmg.org.za/committee-meeting/a3/", date(2026, 5, 1), committee_name="Portfolio Committee on Health")
    _attend(db, m1, politician, "present")
    _attend(db, m2, politician, "apology")
    _attend(db, m3, politician, "present")

    summary = get_politician_attendance_summary(db, politician.id)

    assert summary["recorded_meetings"] == 3
    assert summary["totals"] == {"present": 2, "absent": 0, "apology": 1, "unknown": 0}

    by_name = {row["committee_name"]: row for row in summary["by_committee"]}
    assert by_name["Basic Education"]["present"] == 1
    assert by_name["Basic Education"]["apology"] == 1
    assert by_name["Basic Education"]["total"] == 2
    # Unlinked committees fall back to the meeting's source-supplied name.
    assert by_name["Portfolio Committee on Health"]["present"] == 1
    assert by_name["Portfolio Committee on Health"]["committee_id"] is None

    # Recent list is newest-first and carries evidence links.
    assert [r["meeting_title"] for r in summary["recent"]] == [
        "Oversight visit report",
        "Budget briefing",
        "Unlinked committee meeting",
    ]
    assert all(r["source_url"] for r in summary["recent"])


def test_attendance_summary_counts_only_linked_rows(db):
    politician = _politician(db)
    meeting = _meeting(db, "Meeting", "https://pmg.org.za/committee-meeting/b1/", date(2026, 6, 1))
    # An unlinked attendance row for someone else must not count.
    db.add(
        CommitteeAttendance(
            meeting_id=meeting.id,
            politician_id=None,
            name_raw="Someone Else",
            attendance_status="present",
            source_url=meeting.source_url,
        )
    )
    db.flush()

    summary = get_politician_attendance_summary(db, politician.id)
    assert summary["recorded_meetings"] == 0
    assert summary["by_committee"] == []
    assert summary["recent"] == []


def test_attendance_endpoint_returns_404_for_unknown_politician():
    response = client.get(f"/politicians/{uuid.uuid4()}/attendance")
    assert response.status_code == 404


def test_attendance_endpoint_end_to_end():
    suffix = uuid.uuid4().hex[:10]
    with SessionLocal() as session:
        party = Party(name=f"Party {suffix}", short_name=f"P{suffix}", source_url="https://pmg.org.za/")
        session.add(party)
        session.flush()
        politician = Politician(
            full_name=f"E2E Tester {suffix}",
            display_name=f"E2E Tester {suffix}",
            slug=f"e2e-tester-{suffix}",
            party=party,
        )
        session.add(politician)
        session.flush()
        meeting = CommitteeMeeting(
            title="E2E meeting",
            date=date(2026, 6, 15),
            source_url=f"https://pmg.org.za/committee-meeting/e2e-{suffix}/",
            committee_name="Portfolio Committee on Testing",
        )
        session.add(meeting)
        session.flush()
        session.add(
            CommitteeAttendance(
                meeting_id=meeting.id,
                politician_id=politician.id,
                name_raw="Tester, Mr E",
                attendance_status="present",
                source_url=meeting.source_url,
            )
        )
        session.commit()
        politician_id = politician.id

    response = client.get(f"/politicians/{politician_id}/attendance")
    assert response.status_code == 200
    body = response.json()
    assert body["recorded_meetings"] == 1
    assert body["totals"]["present"] == 1
    assert body["by_committee"][0]["committee_name"] == "Portfolio Committee on Testing"
    assert body["recent"][0]["meeting_title"] == "E2E meeting"
    assert body["recent"][0]["attendance_status"] == "present"
    assert body["recent"][0]["source_url"]
