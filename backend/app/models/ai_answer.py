import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AiAnswer(Base):
    __tablename__ = "ai_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    sources: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    data_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    coverage_notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
