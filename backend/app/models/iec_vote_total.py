import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IECVoteTotal(Base):
    """One source-backed vote-total row from an official IEC manifest."""

    __tablename__ = "iec_vote_totals"
    __table_args__ = (
        Index("ix_iec_vote_totals_election_type_year", "election_type", "election_year"),
        Index("ix_iec_vote_totals_geography", "geography_level", "source_geography_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    manifest_key: Mapped[str] = mapped_column(String(600), nullable=False, index=True)
    election_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    election_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    election_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    source_format: Mapped[str] = mapped_column(String(50), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_contest_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_contest_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    geography_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_geography_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_geography_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_party_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_party_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_candidate_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_candidate_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vote_total: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_row_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    row_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
