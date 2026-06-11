import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VoteRecord(Base):
    """
    One row per (vote_event, record_level, politician_or_party).

    record_level values:
      individual  — a named MP's vote
      party       — party-level aggregate (count of yes/no/abstain per party)
      aggregate   — whole-house totals only, no party/individual breakdown
      unknown     — source present but level unclear

    confidence values:
      high    — directly stated in source (e.g. named MP in division list)
      medium  — inferred from party position with reasonable certainty
      low     — estimated from context, fragile

    vote_value values:
      yes | no | abstain | absent | present | unknown
    """

    __tablename__ = "vote_records"
    __table_args__ = (
        UniqueConstraint(
            "vote_event_id", "politician_id", "party_id", "record_level",
            name="uq_vote_record",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vote_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vote_events.id"), nullable=False, index=True
    )
    politician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("politicians.id"), nullable=True, index=True
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id"), nullable=True, index=True
    )
    vote_value: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    record_level: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    vote_event = relationship("VoteEvent", back_populates="vote_records")
    politician = relationship("Politician")
    party = relationship("Party")
