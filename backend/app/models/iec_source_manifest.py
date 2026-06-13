import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IECSourceManifest(Base):
    """Reproducible manifest of an official IEC source file/endpoint/page.

    Records what official IEC source was discovered and its fetch metadata so a
    later result-parsing PR can start from evidence. No vote totals or result
    rows are stored here. `election_key` is a soft reference to
    `iec_elections.election_key` (no hard FK, so manifest rows never depend on
    election-row insertion order and stay idempotent on their own key).
    """

    __tablename__ = "iec_source_manifests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manifest_key: Mapped[str] = mapped_column(String(600), nullable=False, unique=True, index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    election_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    election_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    election_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    geography_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    parser_readiness: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
