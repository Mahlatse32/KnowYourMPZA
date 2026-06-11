import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VoteEvent(Base):
    __tablename__ = "vote_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    chamber: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # bill_vote | motion | amendment | committee_decision | unknown
    vote_type: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown", index=True)
    # agreed_to | negatived | adopted | tied | withdrawn | unknown
    result: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bills.id"), nullable=True, index=True
    )
    committee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committees.id"), nullable=True, index=True
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    bill = relationship("Bill", back_populates="vote_events")
    committee = relationship("Committee")
    vote_records = relationship("VoteRecord", back_populates="vote_event", cascade="all, delete-orphan")
