from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.quality_service import archive_gaps, quality_duplicates, quality_issues, quality_summary

router = APIRouter(prefix="/quality", tags=["quality"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, int]:
    return quality_summary(db)


@router.get("/issues")
def issues(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    return quality_issues(db, limit=limit)


@router.get("/duplicates")
def duplicates(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    return quality_duplicates(db, limit=limit)


@router.get("/archive-gaps")
def archives(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    return archive_gaps(db, limit=limit)
