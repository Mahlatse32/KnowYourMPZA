import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.party import PartyRead
from app.schemas.politician_alias import PoliticianAliasRead


class PoliticianRead(BaseModel):
    id: uuid.UUID
    full_name: str
    display_name: str
    slug: str
    party: PartyRead
    profile_url: str | None = None
    photo_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PoliticianDetailRead(PoliticianRead):
    aliases: list[PoliticianAliasRead] = []
