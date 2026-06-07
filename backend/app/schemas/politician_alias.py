import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PoliticianAliasRead(BaseModel):
    id: uuid.UUID
    alias: str
    alias_type: str
    source_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
