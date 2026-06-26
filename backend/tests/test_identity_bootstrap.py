from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.politician import Politician
from app.models.question_mention import QuestionMention
from app.models.source import Source
from app.models.vote_event import VoteEvent
from app.ingestion.parliament_questions import upsert_parliamentary_question
from app.services.identity_bootstrap_service import (
    bootstrap_identities_from_pmg,
    estimate_pmg_identity_bootstrap_attempts,
    normalize_pmg_person_name,
)


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


def _pmg_source(db) -> Source:
    source = Source(
        name="PMG",
        base_url="https://pmg.org.za/",
        source_type="parliamentary_monitoring",
        reliability_score=0.9,
    )
    db.add(source)
    db.flush()
    return source


def test_normalize_pmg_person_name_handles_pmg_attendance_formats():
    assert normalize_pmg_person_name("Dlamini, Ms A") == "A Dlamini"
    assert normalize_pmg_person_name("Mr Julius Malema") == "Julius Malema"
    assert normalize_pmg_person_name("Portfolio Committee Staff") is None


def test_pmg_identity_bootstrap_creates_and_links_identities_idempotently(db):
    source = _pmg_source(db)
    document = Document(
        title="Portfolio Committee on Energy meeting",
        document_type="PMG_COMMITTEE_MEETING",
        source=source,
        source_url="https://pmg.org.za/committee-meeting/bootstrap-doc/",
        committee_name="Portfolio Committee on Energy",
        raw_text="A Dlamini attended.",
    )
    db.add(document)
    db.flush()
    meeting = CommitteeMeeting(
        title="Portfolio Committee on Energy: briefing",
        date=date(2026, 1, 20),
        summary_document_id=document.id,
        source_url="https://pmg.org.za/committee-meeting/bootstrap-meeting/",
    )
    db.add(meeting)
    db.flush()
    db.add(
        CommitteeAttendance(
            meeting_id=meeting.id,
            name_raw="Dlamini, Ms A",
            attendance_status="present",
            source_url=meeting.source_url,
        )
    )
    db.add(
        ParliamentaryQuestion(
            question_number="NW1",
            title="Energy question",
            asked_by_name="Dlamini, Ms A",
            question_text="Question text",
            source_url="https://www.parliament.gov.za/question/bootstrap-nw1",
        )
    )
    db.add(
        VoteEvent(
            title="Portfolio Committee on Energy adopted report",
            date=date(2026, 1, 21),
            vote_type="committee_decision",
            source_url="https://pmg.org.za/vote/bootstrap-energy",
        )
    )
    db.commit()

    assert estimate_pmg_identity_bootstrap_attempts(db) == 3

    first = bootstrap_identities_from_pmg(db)
    second = bootstrap_identities_from_pmg(db)

    politician = db.scalar(select(Politician).where(Politician.slug == "a-dlamini"))
    committee = db.scalar(select(Committee).where(Committee.slug == "energy"))
    attendance = db.scalar(select(CommitteeAttendance).where(CommitteeAttendance.name_raw == "Dlamini, Ms A"))
    question = db.scalar(select(ParliamentaryQuestion).where(ParliamentaryQuestion.question_number == "NW1"))
    vote_event = db.scalar(select(VoteEvent).where(VoteEvent.source_url == "https://pmg.org.za/vote/bootstrap-energy"))

    assert first["politicians_created"] == 1
    assert first["committees_created"] == 1
    assert first["attendance_linked"] == 1
    assert first["questions_linked"] == 1
    assert first["vote_events_linked"] == 1
    assert first["memberships_created"] == 1
    assert second["politicians_created"] == 0
    assert second["committees_created"] == 0
    assert politician is not None
    assert politician.source_status == "PMG_DERIVED"
    assert committee is not None
    assert meeting.committee_id == committee.id
    assert attendance.politician_id == politician.id
    assert question.politician_id == politician.id
    assert vote_event.committee_id == committee.id

    assert db.scalar(select(Politician).where(Politician.slug == "a-dlamini")).id == politician.id
    assert len(list(db.scalars(select(Committee).where(Committee.slug == "energy")))) == 1
    assert len(list(db.scalars(select(CommitteeMembership).where(CommitteeMembership.politician_id == politician.id)))) == 1
    assert len(list(db.scalars(select(QuestionMention).where(QuestionMention.politician_id == politician.id)))) == 1


def test_link_meetings_via_committee_name_column(db):
    """Strategy 3: meetings with committee_name stored resolve without a Document."""
    source = _pmg_source(db)
    # A committee exists (bootstrapped from a document elsewhere).
    from app.models.document import Document as Doc
    doc = Doc(
        title="Finance committee meeting",
        document_type="PMG_COMMITTEE_MEETING",
        source=source,
        source_url="https://pmg.org.za/committee-meeting/finance-doc/",
        committee_name="Portfolio Committee on Finance",
        raw_text="Finance briefing.",
    )
    db.add(doc)
    db.flush()
    db.commit()

    # Bootstrap creates the committee from the document.
    first = bootstrap_identities_from_pmg(db)
    committee = db.scalar(select(Committee).where(Committee.slug == "finance"))
    assert committee is not None, "Committee must be bootstrapped from document"

    # Create two meetings that have committee_name stored (as would happen after
    # the fix is deployed and the sweep re-processes meetings from the API).
    m1 = CommitteeMeeting(
        title="Annual budget briefing",
        date=date(2026,