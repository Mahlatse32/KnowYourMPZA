import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def make_universe_key(
    *,
    source_name: str,
    source_url: str,
    chamber: str,
    term_label: str | None,
    source_identifier: str | None,
    full_name: str,
) -> str:
    """Build a stable evidence-row key without linking to an internal person."""

    identity = source_identifier or full_name
    values = [source_name, source_url, chamber, term_label or "", identity]
    normalized = [" ".join(value.strip().lower().split()) for value in values]
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ExpectedRepresentativeUniverse(Base):
    """One expected representative row supported by explicit source evidence."""

    __tablename__ = "expected_representative_universe"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    universe_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_identifier: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    term_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chamber: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    representative_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    party_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    role_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="expected", index=True)
    profile_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_source_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
