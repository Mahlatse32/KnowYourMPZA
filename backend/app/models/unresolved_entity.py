import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UnresolvedEntity(Base):
    __tablename__ = "unresolved_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    raw_value: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OPEN", index=True)
    resolved_politician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("politicians.id"), nullable=True, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
