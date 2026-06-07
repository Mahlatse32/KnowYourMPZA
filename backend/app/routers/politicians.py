import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.committee import CommitteeMembershipRead
from app.schemas.document import DocumentMentionRead
from app.schemas.politician import PoliticianDetailRead, PoliticianRead
from app.services.politician_service import (
    get_politician,
    list_politician_committee_memberships,
    list_politician_document_mentions,
    list_politicians,
)

router = APIRouter(prefix="/politicians", tags=["politicians"])


@router.get("", response_model=list[PoliticianRead])
def get_politicians(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list:
    return list_politicians(db, limit=limit, offset=offset)


@router.get("/{politician_id}", response_model=PoliticianDetailRead)
def get_politician_detail(politician_id: uuid.UUID, db: Session = Depends(get_db)):
    politician = get_politician(db, politician_id)
    if politician is None:
        raise HTTPException(status_code=404, detail="Politician not found.")
    return politician


@router.get("/{politician_id}/committees", response_model=list[CommitteeMembershipRead])
def get_politician_committees(politician_id: uuid.UUID, db: Session = Depends(get_db)) -> list:
    if get_politician(db, politician_id) is None:
        raise HTTPException(status_code=404, detail="Politician not found.")
    return list_politician_committee_memberships(db, politician_id)


@router.get("/{politician_id}/documents", response_model=list[DocumentMentionRead])
def get_politician_documents(
    politician_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list:
    if get_politician(db, politician_id) is None:
        raise HTTPException(status_code=404, detail="Politician not found.")
    return list_politician_document_mentions(db, politician_id, limit=limit, offset=offset)
