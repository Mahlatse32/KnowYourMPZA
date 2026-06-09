import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UnresolvedEntityRead(BaseModel):
    id: uuid.UUID
    source_name: str
    source_url: str | None = None
    raw_value: str
    entity_type: str
    confidence: float | None = None
    status: str
    resolved_politician_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UnresolvedResolveRequest(BaseModel):
    politician_id: uuid.UUID
    create_alias: bool = True
    alias_type: str = "SOURCE_VARIANT"
    notes: str | None = None


class UnresolvedIgnoreRequest(BaseModel):
    notes: str | None = None
