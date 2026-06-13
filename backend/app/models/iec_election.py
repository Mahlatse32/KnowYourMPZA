import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IECElection(Base):
    """Official IEC election/event metadata only.

    This stores *metadata* about an election as labelled by an official IEC
    source — never vote totals, candidates, winners, or geography mappings.
    Election dates and names are not invented: fields are populated only when
    explicitly present in curated/discovered source metadata.
    """

    __tablename__ = "iec_elections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    election_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    election_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    election_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    geography_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
