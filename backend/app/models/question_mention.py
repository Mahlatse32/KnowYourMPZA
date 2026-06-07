import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class QuestionMention(Base):
    __tablename__ = "question_mentions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parliamentary_questions.id"), nullable=False, index=True
    )
    politician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("politicians.id"), nullable=False, index=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    question = relationship("ParliamentaryQuestion", back_populates="mentions")
    politician = relationship("Politician", back_populates="question_mentions")
