import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.politician_alias import PoliticianAlias
from app.models.politician import Politician

ATTENDANCE_STATUSES = ("present", "absent", "apology", "unknown")


def list_politicians(db: Session, limit: int = 50, offset: int = 0) -> list[Politician]:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party))
        .order_by(Politician.display_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())


def get_politician(db: Session, politician_id: uuid.UUID) -> Politician | None:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party), joinedload(Politician.aliases))
        .where(Politician.id == politician_id)
    )
    return db.scalars(statement).first()


def search_politicians(db: Session, name: str) -> list[Politician]:
    pattern = f"%{name.strip()}%"
    statement = (
        select(Politician)
        .outerjoin(PoliticianAlias)
        .options(joinedload(Politician.party))
        .where(
            or_(
                Politician.full_name.ilike(pattern),
                Politician.display_name.ilike(pattern),
                Politician.slug.ilike(pattern),
                PoliticianAlias.alias.ilike(pattern),
            )
        )
        .order_by(Politician.display_name)
    )
    return list(db.scalars(statement).unique())


def list_politician_committee_memberships(db: Session, politician_id: uuid.UUID) -> list[CommitteeMembership]:
    statement = (
        select(CommitteeMembership)
        .options(joinedload(CommitteeMembership.committee))
        .where(CommitteeMembership.politician_id == politician_id)
        .order_by(CommitteeMembership.role, CommitteeMembership.id)
    )
    return list(db.scalars(statement).unique())


def get_politician_attendance_summary(
    db: Session, politician_id: uuid.UUID, recent_limit: int = 10
) -> dict:
    """Aggregate explicit attendance records linked to a politician.

    Only rows already resolved to this politician are counted — nothing is
    inferred from unlinked name_raw rows. Committee names fall back to the
    meeting's source-supplied committee_name when the committee identity is
    not linked yet.
    """
    committee_name = func.coalesce(Committee.name, CommitteeMeeting.committee_name)

    totals = {status: 0 for status in ATTENDANCE_STATUSES}
    for status, count in db.execute(
        select(CommitteeAttendance.attendance_status, func.count())
        .where(CommitteeAttendance.politician_id == politician_id)
        .group_by(CommitteeAttendance.attendance_status)
    ):
        totals[status if status in totals else "unknown"] = (
            totals.get(status if status in totals else "unknown", 0) + count
        )
    recorded = sum(totals.values())

    breakdown: dict[tuple, dict] = {}
    for committee_id, name, status, count in db.execute(
        select(
            CommitteeMeeting.committee_id,
            committee_name,
            CommitteeAttendance.attendance_status,
            func.count(),
        )
        .join(CommitteeMeeting, CommitteeAttendance.meeting_id == CommitteeMeeting.id)
        .outerjoin(Committee, CommitteeMeeting.committee_id == Committee.id)
        .where(CommitteeAttendance.politician_id == politician_id)
        .group_by(CommitteeMeeting.committee_id, committee_name, CommitteeAttendance.attendance_status)
    ):
        entry = breakdown.setdefault(
            (committee_id, name),
            {
                "committee_id": committee_id,
                "committee_name": name,
                **{s: 0 for s in ATTENDANCE_STATUSES},
                "total": 0,
            },
        )
        entry[status if status in ATTENDANCE_STATUSES else "unknown"] += count
        entry["total"] += count

    recent = [
        {
            "meeting_id": meeting.id,
            "meeting_title": meeting.title,
            "meeting_date": meeting.date,
            "committee_name": name,
            "attendance_status": record.attendance_status,
            "source_url": record.source_url or meeting.source_url,
        }
        for record, meeting, name in db.execute(
            select(CommitteeAttendance, CommitteeMeeting, committee_name)
            .join(CommitteeMeeting, CommitteeAttendance.meeting_id == CommitteeMeeting.id)
            .outerjoin(Committee, CommitteeMeeting.committee_id == Committee.id)
            .where(CommitteeAttendance.politician_id == politician_id)
            .order_by(CommitteeMeeting.date.desc().nullslast(), CommitteeMeeting.created_at.desc())
            .limit(recent_limit)
        )
    ]

    return {
        "totals": totals,
        "recorded_meetings": recorded,
        "by_committee": sorted(breakdown.values(), key=lambda e: e["total"], reverse=True),
        "recent": recent,
    }


def list_politician_document_mentions(db: Session, politician_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[DocumentMention]:
    statement = (
        select(DocumentMention)
        .options(joinedload(DocumentMention.document).joinedload(Document.source))
        .where(DocumentMention.politician_id == politician_id)
        .order_by(DocumentMention.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())
