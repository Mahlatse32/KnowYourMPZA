import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AiAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    refresh: bool = False


class AiSource(BaseModel):
    title: str
    source_url: str | None = None
    source_type: str
    record_id: str
    date: str | None = None
    excerpt: str | None = None
    asked_by: str | None = None
    department: str | None = None
    status: str | None = None


class AiAskResponse(BaseModel):
    id: uuid.UUID | None = None
    question: str
    answer: str
    intent: str
    sources: list[AiSource]
    coverage_notice: str
    data_snapshot: dict[str, int]
    model_used: str
    cached: bool
    generated_at: datetime
