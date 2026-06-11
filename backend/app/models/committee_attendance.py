import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CommitteeAttendance(Base):
    """
    One row per (meeting, name_raw). If the name resolves to a politician,
    politician_id is set. Unresolved names are left as name_raw only and
    should also be written to unresolved_entities for review.

    attendance_status values:
      present | absent | apology | unknown
    """

    __tablename__ = "committee_attendance"
    __table_args__ = (
        UniqueConstraint("meeting_id", "name_raw", name="uq_committee_attendance"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committee_meetings.id"), nullable=False, index=True
    )
    politician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("politicians.id"), nullable=True, index=True
    )
    name_raw: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id"), nullable=True, index=True
    )
    attendance_status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    meeting = relationship("CommitteeMeeting", back_populates="attendance_records")
    politician = relationship("Politician")
    party = relationship("Party")
