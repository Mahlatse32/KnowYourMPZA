import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.vote_event import VoteEvent
from app.schemas.accountability import VoteEventRead, VoteRecordRead
from app.services.accountability_service import list_vote_events

router = APIRouter(prefix="/votes", tags=["votes"])


@router.get("", response_model=list[VoteEventRead])
def get_vote_events(
    chamber: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_vote_events(db, chamber=chamber, limit=limit, offset=offset)


@router.get("/{vote_id}", response_model=VoteEventRead)
def get_vote_event(vote_id: uuid.UUID, db: Session = Depends(get_db)):
    event = db.scalar(select(VoteEvent).where(VoteEvent.id == vote_id))
    if not event:
        raise HTTPException(status_code=404, detail="Vote event not found")
    return event


@router.get("/{vote_id}/records", response_model=list[VoteRecordRead])
def get_vote_records(vote_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.models.vote_record import VoteRecord
    event = db.scalar(select(VoteEvent).where(VoteEvent.id == vote_id))
    if not event:
        raise HTTPException(status_code=404, detail="Vote event not found")
    records = db.scalars(select(VoteRecord).where(VoteRecord.vote_event_id == vote_id)).all()
    return list(records)
