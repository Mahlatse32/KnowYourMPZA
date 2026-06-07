import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CommitteeRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommitteeMembershipRead(BaseModel):
    id: uuid.UUID
    role: str | None = None
    source_url: str
    start_date: date | None = None
    end_date: date | None = None
    committee: CommitteeRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
