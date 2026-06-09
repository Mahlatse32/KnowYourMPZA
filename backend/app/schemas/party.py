import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PartyRead(BaseModel):
    id: uuid.UUID
    name: str
    short_name: str
    logo_url: str | None = None
    website_url: str | None = None
    source_url: str | None = None
    source_last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
