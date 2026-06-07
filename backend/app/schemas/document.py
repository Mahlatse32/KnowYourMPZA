import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.source import SourceRead
from app.schemas.politician import PoliticianRead


class DocumentRead(BaseModel):
    id: uuid.UUID
    title: str
    document_type: str
    source_url: str
    archive_path: str | None = None
    publication_date: date | None = None
    raw_text: str | None = None
    source: SourceRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentMentionRead(BaseModel):
    id: uuid.UUID
    snippet: str
    source_url: str
    confidence_score: float
    document: DocumentRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentMentionWithPoliticianRead(BaseModel):
    id: uuid.UUID
    snippet: str
    source_url: str
    confidence_score: float
    politician: PoliticianRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDetailRead(DocumentRead):
    mentions: list[DocumentMentionWithPoliticianRead] = []
