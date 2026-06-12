import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestionSweepState(Base):
    """Durable pagination/cursor progress for incremental source sweeps.

    One row per (source_name, stream_name). page_number always holds the NEXT
    page/batch to process; it advances only after a successful bounded run
    (unless explicitly overridden). When the source end is reached the cursor
    wraps to 0 so subsequent runs refresh from the newest data.

    cursor_type values: "page" (API page numbers) | "offset" (DB batch offset).
    """

    __tablename__ = "ingestion_sweep_states"
    __table_args__ = (
        UniqueConstraint("source_name", "stream_name", name="uq_sweep_source_stream"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stream_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    cursor_type: Mapped[str] = mapped_column(String(50), nullable=False, default="page")
    cursor_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_pages_per_run: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sweeps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
