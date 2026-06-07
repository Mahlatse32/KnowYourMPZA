import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.ingestion_run import IngestionRunDetailRead, IngestionRunRead
from app.services.ingestion_run_service import get_ingestion_run, list_ingestion_runs

router = APIRouter(prefix="/ingestion/runs", tags=["ingestion-runs"])


@router.get("", response_model=list[IngestionRunRead])
def runs(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list:
    return list_ingestion_runs(db, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=IngestionRunDetailRead)
def run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = get_ingestion_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    return run
