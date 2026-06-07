import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.committee import CommitteeRead
from app.schemas.politician import PoliticianRead
from app.services.browse_service import committee_politicians, get_committee, list_committees

router = APIRouter(prefix="/committees", tags=["committees"])


@router.get("", response_model=list[CommitteeRead])
def committees(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return list_committees(db, limit, offset)


@router.get("/{committee_id}", response_model=CommitteeRead)
def committee_detail(committee_id: uuid.UUID, db: Session = Depends(get_db)):
    committee = get_committee(db, committee_id)
    if committee is None:
        raise HTTPException(status_code=404, detail="Committee not found.")
    return committee


@router.get("/{committee_id}/politicians", response_model=list[PoliticianRead])
def politicians_for_committee(
    committee_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if get_committee(db, committee_id) is None:
        raise HTTPException(status_code=404, detail="Committee not found.")
    return committee_politicians(db, committee_id, limit, offset)
