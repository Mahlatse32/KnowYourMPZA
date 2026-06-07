from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas.ingest import IngestionSummary, UrlBatchRequest
from app.services.ingestion_service import (
    ingest_people_assembly_profiles,
    ingest_pmg_documents,
    seed_database,
    seed_sample_documents,
)
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run

router = APIRouter(prefix="/ingest", tags=["ingestion"])


def ensure_development() -> None:
    if not settings.is_development:
        raise HTTPException(status_code=403, detail="Ingestion endpoints are development-only.")


@router.post("/seed")
def seed(db: Session = Depends(get_db)) -> dict[str, int | str]:
    ensure_development()
    return seed_database(db)


@router.post("/sample-documents")
def sample_documents(db: Session = Depends(get_db)) -> dict[str, int | str]:
    ensure_development()
    return seed_sample_documents(db)


@router.post("/people-assembly", response_model=IngestionSummary)
def people_assembly(payload: UrlBatchRequest, db: Session = Depends(get_db)) -> dict:
    ensure_development()
    urls = [str(url) for url in payload.urls]
    run = start_ingestion_run(db, "People's Assembly", "api_people_assembly", len(urls))
    summary = ingest_people_assembly_profiles(db, urls)
    finish_ingestion_run(db, run, summary)
    return summary


@router.post("/pmg-documents", response_model=IngestionSummary)
def pmg_documents(payload: UrlBatchRequest, db: Session = Depends(get_db)) -> dict:
    ensure_development()
    urls = [str(url) for url in payload.urls]
    run = start_ingestion_run(db, "PMG", "api_pmg_documents", len(urls))
    summary = ingest_pmg_documents(db, urls)
    finish_ingestion_run(db, run, summary)
    return summary
