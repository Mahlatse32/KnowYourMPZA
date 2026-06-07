import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ParliamentaryQuestion(Base):
    __tablename__ = "parliamentary_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    politician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("politicians.id"), nullable=True, index=True
    )
    asked_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    minister: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    asked_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    answered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    archive_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_file_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    extracted_text_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parse_status: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    parse_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    politician = relationship("Politician", back_populates="parliamentary_questions")
    source = relationship("Source", back_populates="parliamentary_questions")
    mentions = relationship("QuestionMention", back_populates="question", cascade="all, delete-orphan")
