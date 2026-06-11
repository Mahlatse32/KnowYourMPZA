import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.bill import Bill
from app.schemas.accountability import BillEventRead, BillRead
from app.services.accountability_service import list_bill_events, list_bills

router = APIRouter(prefix="/bills", tags=["bills"])


@router.get("", response_model=list[BillRead])
def get_bills(
    status: str | None = None,
    year: int | None = None,
    house: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_bills(db, status=status, year=year, house=house, limit=limit, offset=offset)


@router.get("/{bill_id}", response_model=BillRead)
def get_bill(bill_id: uuid.UUID, db: Session = Depends(get_db)):
    bill = db.scalar(select(Bill).where(Bill.id == bill_id))
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.get("/{bill_id}/events", response_model=list[BillEventRead])
def get_bill_events(bill_id: uuid.UUID, db: Session = Depends(get_db)):
    bill = db.scalar(select(Bill).where(Bill.id == bill_id))
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return list_bill_events(db, bill_id=bill_id)
