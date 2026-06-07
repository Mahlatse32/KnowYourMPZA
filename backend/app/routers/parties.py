import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.party import PartyRead
from app.schemas.politician import PoliticianRead
from app.services.browse_service import get_party, list_parties, party_politicians

router = APIRouter(prefix="/parties", tags=["parties"])


@router.get("", response_model=list[PartyRead])
def parties(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return list_parties(db, limit, offset)


@router.get("/{party_id}", response_model=PartyRead)
def party_detail(party_id: uuid.UUID, db: Session = Depends(get_db)):
    party = get_party(db, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found.")
    return party


@router.get("/{party_id}/politicians", response_model=list[PoliticianRead])
def politicians_for_party(
    party_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if get_party(db, party_id) is None:
        raise HTTPException(status_code=404, detail="Party not found.")
    return party_politicians(db, party_id, limit, offset)
