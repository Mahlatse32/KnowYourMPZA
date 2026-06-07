from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import committees, documents, health, ingest, ingestion_runs, parties, politicians, quality, questions, search

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Verified South African MP data with source evidence.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(politicians.router)
app.include_router(committees.router)
app.include_router(documents.router)
app.include_router(parties.router)
app.include_router(questions.router)
app.include_router(search.router)
app.include_router(ingest.router)
app.include_router(ingestion_runs.router)
app.include_router(quality.router)
