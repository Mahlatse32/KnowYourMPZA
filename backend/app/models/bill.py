import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (UniqueConstraint("bill_number", "year", "house", name="uq_bill_number_year_house"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    short_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bill_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(nullable=True, index=True)
    house: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown", index=True)
    introduced_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    passed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assented_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    act_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events = relationship("BillEvent", back_populates="bill", cascade="all, delete-orphan")
    vote_events = relationship("VoteEvent", back_populates="bill")
