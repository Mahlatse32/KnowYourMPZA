import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.committee_meeting import CommitteeMeeting
from app.schemas.accountability import CommitteeAttendanceRead, CommitteeMeetingRead
from app.services.accountability_service import list_committee_meetings

router = APIRouter(prefix="/committee-meetings", tags=["meetings"])


@router.get("", response_model=list[CommitteeMeetingRead])
def get_meetings(
    committee_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_committee_meetings(db, committee_id=committee_id, limit=limit, offset=offset)


@router.get("/{meeting_id}", response_model=CommitteeMeetingRead)
def get_meeting(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = db.scalar(select(CommitteeMeeting).where(CommitteeMeeting.id == meeting_id))
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.get("/{meeting_id}/attendance", response_model=list[CommitteeAttendanceRead])
def get_meeting_attendance(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.models.committee_attendance import CommitteeAttendance
    meeting = db.scalar(select(CommitteeMeeting).where(CommitteeMeeting.id == meeting_id))
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    records = db.scalars(
        select(CommitteeAttendance).where(CommitteeAttendance.meeting_id == meeting_id)
    ).all()
    return list(records)
