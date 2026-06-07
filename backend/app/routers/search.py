from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.politician import PoliticianRead
from app.services.politician_service import search_politicians

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[PoliticianRead])
def search(name: str = Query(min_length=1), db: Session = Depends(get_db)) -> list:
    return search_politicians(db, name)
