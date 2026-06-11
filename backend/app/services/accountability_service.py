"""Upsert and list functions for the accountability data layer."""
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.bill_event import BillEvent
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.party import Party
from app.models.politician import Politician
from app.models.vote_event import VoteEvent
from app.models.vote_record import VoteRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

def upsert_bill(db: Session, data: dict[str, Any]) -> Bill:
    """Insert or update a bill identified by (bill_number, year, house)."""
    source_url: str | None = data.get("source_url")
    bill_number: str | None = data.get("bill_number")
    year: int | None = data.get("year")
    house: str | None = data.get("house")

    bill: Bill | None = None
    if source_url:
        bill = db.scalar(select(Bill).where(Bill.source_url == source_url))
    if bill is None and bill_number and year:
        stmt = select(Bill).where(Bill.bill_number == bill_number, Bill.year == year)
        if house:
            stmt = stmt.where(Bill.house == house)
        bill = db.scalar(stmt)

    if bill is None:
        bill = Bill(
            title=data["title"],
            short_title=data.get("short_title"),
            bill_number=bill_number,
            year=year,
            house=house,
            status=data.get("status", "unknown"),
            introduced_date=data.get("introduced_date"),
            passed_date=data.get("passed_date"),
            assented_date=data.get("assented_date"),
            act_number=data.get("act_number"),
            source_url=source_url,
            source_type=data.get("source_type"),
        )
        db.add(bill)
        db.flush()
        logger.info("Created bill: %s", bill.title)
    else:
        bill.title = data["title"]
        if data.get("short_title"):
            bill.short_title = data["short_title"]
        bill.status = data.get("status", bill.status)
        if data.get("introduced_date"):
            bill.introduced_date = data["introduced_date"]
        if data.get("passed_date"):
            bill.passed_date = data["passed_date"]
        if data.get("assented_date"):
            bill.assented_date = data["assented_date"]
        if data.get("act_number"):
            bill.act_number = data["act_number"]
        db.flush()

    for event_data in data.get("events", []):
        _upsert_bill_event(db, bill, event_data)

    return bill


def _upsert_bill_event(db: Session, bill: Bill, data: dict[str, Any]) -> BillEvent:
    stmt = select(BillEvent).where(
        BillEvent.bill_id == bill.id,
        BillEvent.event_type == data["event_type"],
        BillEvent.event_date == data.get("event_date"),
        BillEvent.source_url == data.get("source_url"),
    )
    event = db.scalar(stmt)
    if event is None:
        event = BillEvent(
            bill_id=bill.id,
            event_type=data["event_type"],
            event_date=data.get("event_date"),
            description=data.get("description"),
            committee_id=data.get("committee_id"),
            document_id=data.get("document_id"),
            source_url=data.get("source_url"),
        )
        db.add(event)
        db.flush()
    return event


def list_bills(
    db: Session,
    status: str | None = None,
    year: int | None = None,
    house: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Bill]:
    stmt = select(Bill)
    if status:
        stmt = stmt.where(Bill.status == status)
    if year:
        stmt = stmt.where(Bill.year == year)
    if house:
        stmt = stmt.where(Bill.house == house)
    stmt = stmt.order_by(Bill.year.desc().nullslast(), Bill.title).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def list_bill_events(db: Session, bill_id) -> list[BillEvent]:
    return list(db.scalars(select(BillEvent).where(BillEvent.bill_id == bill_id).order_by(BillEvent.event_date)))


# ---------------------------------------------------------------------------
# Vote events
# ---------------------------------------------------------------------------

def upsert_vote_event(db: Session, data: dict[str, Any]) -> VoteEvent:
    source_url: str | None = data.get("source_url")
    event: VoteEvent | None = None
    if source_url:
        event = db.scalar(select(VoteEvent).where(VoteEvent.source_url == source_url))

    if event is None:
        event = VoteEvent(
            title=data["title"],
            date=data.get("date"),
            chamber=data.get("chamber"),
            vote_type=data.get("vote_type", "unknown"),
            result=data.get("result"),
            bill_id=data.get("bill_id"),
            committee_id=data.get("committee_id"),
            source_url=source_url,
            source_type=data.get("source_type"),
        )
        db.add(event)
        db.flush()
        logger.info("Created vote event: %s", event.title)
    else:
        event.title = data["title"]
        event.result = data.get("result", event.result)
        db.flush()

    for record_data in data.get("vote_records", []):
        _upsert_vote_record(db, event, record_data)

    return event


def _resolve_party(db: Session, name: str | None) -> Party | None:
    if not name:
        return None
    return db.scalar(select(Party).where(Party.name == name))


def _resolve_politician(db: Session, name: str | None) -> Politician | None:
    if not name:
        return None
    return db.scalar(select(Politician).where(Politician.name == name))


def _upsert_vote_record(db: Session, event: VoteEvent, data: dict[str, Any]) -> VoteRecord:
    politician = _resolve_politician(db, data.get("politician_name"))
    party = _resolve_party(db, data.get("party_name"))
    politician_id = politician.id if politician else None
    party_id = party.id if party else None
    record_level = data.get("record_level", "unknown")

    stmt = select(VoteRecord).where(
        VoteRecord.vote_event_id == event.id,
        VoteRecord.record_level == record_level,
    )
    if politician_id is not None:
        stmt = stmt.where(VoteRecord.politician_id == politician_id)
    else:
        stmt = stmt.where(VoteRecord.politician_id.is_(None))
    if party_id is not None:
        stmt = stmt.where(VoteRecord.party_id == party_id)
    else:
        stmt = stmt.where(VoteRecord.party_id.is_(None))

    record = db.scalar(stmt)
    if record is None:
        record = VoteRecord(
            vote_event_id=event.id,
            politician_id=politician_id,
            party_id=party_id,
            vote_value=data.get("vote_value", "unknown"),
            record_level=record_level,
            count=data.get("count"),
            confidence=data.get("confidence", "medium"),
            source_url=data.get("source_url"),
        )
        db.add(record)
        db.flush()
    else:
        record.vote_value = data.get("vote_value", record.vote_value)
        record.count = data.get("count", record.count)
        db.flush()
    return record


def list_vote_events(
    db: Session,
    chamber: str | None = None,
    bill_id=None,
    limit: int = 50,
    offset: int = 0,
) -> list[VoteEvent]:
    stmt = select(VoteEvent)
    if chamber:
        stmt = stmt.where(VoteEvent.chamber == chamber)
    if bill_id:
        stmt = stmt.where(VoteEvent.bill_id == bill_id)
    stmt = stmt.order_by(VoteEvent.date.desc().nullslast()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


# ---------------------------------------------------------------------------
# Committee meetings
# ---------------------------------------------------------------------------

def upsert_committee_meeting(db: Session, data: dict[str, Any], committee: Committee | None = None) -> CommitteeMeeting:
    source_url: str | None = data.get("source_url")
    meeting: CommitteeMeeting | None = None
    if source_url:
        meeting = db.scalar(select(CommitteeMeeting).where(CommitteeMeeting.source_url == source_url))

    if meeting is None:
        meeting = CommitteeMeeting(
            committee_id=committee.id if committee else data.get("committee_id"),
            title=data["title"],
            date=data.get("date"),
            summary=data.get("summary"),
            source_url=source_url,
            pmg_url=data.get("pmg_url"),
            summary_document_id=data.get("summary_document_id"),
        )
        db.add(meeting)
        db.flush()
        logger.info("Created committee meeting: %s", meeting.title)
    else:
        if data.get("summary"):
            meeting.summary = data["summary"]
        db.flush()

    for attendance_data in data.get("attendance", []):
        _upsert_committee_attendance(db, meeting, attendance_data)

    return meeting


def _upsert_committee_attendance(db: Session, meeting: CommitteeMeeting, data: dict[str, Any]) -> CommitteeAttendance:
    name_raw = data["name_raw"]
    stmt = select(CommitteeAttendance).where(
        CommitteeAttendance.meeting_id == meeting.id,
        CommitteeAttendance.name_raw == name_raw,
    )
    record = db.scalar(stmt)

    politician = _resolve_politician(db, name_raw)
    party = _resolve_party(db, data.get("party_name"))

    if record is None:
        record = CommitteeAttendance(
            meeting_id=meeting.id,
            politician_id=politician.id if politician else None,
            name_raw=name_raw,
            party_id=party.id if party else None,
            attendance_status=data.get("attendance_status", "unknown"),
            confidence=data.get("confidence"),
            source_url=data.get("source_url"),
        )
        db.add(record)
        db.flush()
    else:
        record.attendance_status = data.get("attendance_status", record.attendance_status)
        if politician and not record.politician_id:
            record.politician_id = politician.id
        db.flush()
    return record


def list_committee_meetings(
    db: Session,
    committee_id=None,
    limit: int = 50,
    offset: int = 0,
) -> list[CommitteeMeeting]:
    stmt = select(CommitteeMeeting)
    if committee_id:
        stmt = stmt.where(CommitteeMeeting.committee_id == committee_id)
    stmt = stmt.order_by(CommitteeMeeting.date.desc().nullslast()).limit(limit).offset(offset)
    return list(db.scalars(stmt))
