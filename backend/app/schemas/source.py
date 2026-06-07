import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceRead(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str
    source_type: str
    reliability_score: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
