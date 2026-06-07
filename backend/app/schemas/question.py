import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.politician import PoliticianRead
from app.schemas.source import SourceRead


class QuestionMentionResponse(BaseModel):
    id: uuid.UUID
    snippet: str | None = None
    confidence_score: float | None = None
    match_reason: str | None = None
    politician: PoliticianRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParliamentaryQuestionResponse(BaseModel):
    id: uuid.UUID
    question_number: str | None = None
    title: str | None = None
    asked_by_name: str | None = None
    department: str | None = None
    minister: str | None = None
    question_text: str | None = None
    answer_text: str | None = None
    asked_date: date | None = None
    answered_date: date | None = None
    status: str | None = None
    source_url: str
    archive_path: str | None = None
    source_file_type: str | None = None
    extracted_text_available: bool = False
    parse_status: str | None = None
    parse_notes: str | None = None
    politician: PoliticianRead | None = None
    source: SourceRead | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParliamentaryQuestionDetailResponse(ParliamentaryQuestionResponse):
    mentions: list[QuestionMentionResponse] = []


class ParliamentaryQuestionListResponse(BaseModel):
    items: list[ParliamentaryQuestionResponse]
    limit: int
    offset: int
