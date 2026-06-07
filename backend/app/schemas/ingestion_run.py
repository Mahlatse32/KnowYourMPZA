import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestionErrorRead(BaseModel):
    id: uuid.UUID
    source_url: str
    error_message: str
    error_type: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionRunRead(BaseModel):
    id: uuid.UUID
    source_name: str
    run_type: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    attempted_count: int
    processed_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionRunDetailRead(IngestionRunRead):
    errors: list[IngestionErrorRead] = []
