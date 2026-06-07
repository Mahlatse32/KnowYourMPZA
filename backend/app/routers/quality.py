from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.quality_service import quality_summary

router = APIRouter(prefix="/quality", tags=["quality"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, int]:
    return quality_summary(db)
