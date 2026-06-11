"""add accountability layer: bills, votes, committee meetings and attendance

Revision ID: 0009_add_accountability_layer
Revises: 0008_add_document_metadata
Create Date: 2026-06-11 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_add_accountability_layer"
down_revision: Union[str, None] = "0008_add_document_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # bills
    # -----------------------------------------------------------------------
    op.create_table(
        "bills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("short_title", sa.String(length=255), nullable=True),
        sa.Column("bill_number", sa.String(length=50), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("house", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("introduced_date", sa.Date(), nullable=True),
        sa.Column("passed_date", sa.Date(), nullable=True),
        sa.Column("assented_date", sa.Date(), nullable=True),
        sa.Column("act_number", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_number", "year", "house", name="uq_bill_number_year_house"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index(op.f("ix_bills_bill_number"), "bills", ["bill_number"])
    op.create_index(op.f("ix_bills_house"), "bills", ["house"])
    op.create_index(op.f("ix_bills_source_url"), "bills", ["source_url"], unique=True)
    op.create_index(op.f("ix_bills_status"), "bills", ["status"])
    op.create_index(op.f("ix_bills_title"), "bills", ["title"])
    op.create_index(op.f("ix_bills_year"), "bills", ["year"])

    # -----------------------------------------------------------------------
    # bill_events
    # -----------------------------------------------------------------------
    op.create_table(
        "bill_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("committee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"]),
        sa.ForeignKeyConstraint(["committee_id"], ["committees.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_id", "event_type", "event_date", "source_url", name="uq_bill_event"),
    )
    op.create_index(op.f("ix_bill_events_bill_id"), "bill_events", ["bill_id"])
    op.create_index(op.f("ix_bill_events_committee_id"), "bill_events", ["committee_id"])
    op.create_index(op.f("ix_bill_events_document_id"), "bill_events", ["document_id"])
    op.create_index(op.f("ix_bill_events_event_type"), "bill_events", ["event_type"])
    op.create_index(op.f("ix_bill_events_source_url"), "bill_events", ["source_url"])

    # -----------------------------------------------------------------------
    # vote_events
    # -----------------------------------------------------------------------
    op.create_table(
        "vote_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("chamber", sa.String(length=100), nullable=True),
        sa.Column("vote_type", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("result", sa.String(length=100), nullable=True),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("committee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"]),
        sa.ForeignKeyConstraint(["committee_id"], ["committees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index(op.f("ix_vote_events_bill_id"), "vote_events", ["bill_id"])
    op.create_index(op.f("ix_vote_events_chamber"), "vote_events", ["chamber"])
    op.create_index(op.f("ix_vote_events_committee_id"), "vote_events", ["committee_id"])
    op.create_index(op.f("ix_vote_events_date"), "vote_events", ["date"])
    op.create_index(op.f("ix_vote_events_result"), "vote_events", ["result"])
    op.create_index(op.f("ix_vote_events_source_url"), "vote_events", ["source_url"], unique=True)
    op.create_index(op.f("ix_vote_events_title"), "vote_events", ["title"])
    op.create_index(op.f("ix_vote_events_vote_type"), "vote_events", ["vote_type"])

    # -----------------------------------------------------------------------
    # vote_records
    # -----------------------------------------------------------------------
    op.create_table(
        "vote_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vote_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vote_value", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("record_level", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(length=50), nullable=False, server_default="medium"),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.ForeignKeyConstraint(["vote_event_id"], ["vote_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vote_event_id", "politician_id", "party_id", "record_level", name="uq_vote_record"),
    )
    op.create_index(op.f("ix_vote_records_party_id"), "vote_records", ["party_id"])
    op.create_index(op.f("ix_vote_records_politician_id"), "vote_records", ["politician_id"])
    op.create_index(op.f("ix_vote_records_record_level"), "vote_records", ["record_level"])
    op.create_index(op.f("ix_vote_records_source_url"), "vote_records", ["source_url"])
    op.create_index(op.f("ix_vote_records_vote_event_id"), "vote_records", ["vote_event_id"])
    op.create_index(op.f("ix_vote_records_vote_value"), "vote_records", ["vote_value"])

    # -----------------------------------------------------------------------
    # committee_meetings
    # -----------------------------------------------------------------------
    op.create_table(
        "committee_meetings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("committee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("pmg_url", sa.String(length=500), nullable=True),
        sa.Column("summary_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["committee_id"], ["committees.id"]),
        sa.ForeignKeyConstraint(["summary_document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index(op.f("ix_committee_meetings_committee_id"), "committee_meetings", ["committee_id"])
    op.create_index(op.f("ix_committee_meetings_date"), "committee_meetings", ["date"])
    op.create_index(op.f("ix_committee_meetings_source_url"), "committee_meetings", ["source_url"], unique=True)
    op.create_index(op.f("ix_committee_meetings_title"), "committee_meetings", ["title"])

    # -----------------------------------------------------------------------
    # committee_attendance
    # -----------------------------------------------------------------------
    op.create_table(
        "committee_attendance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name_raw", sa.String(length=255), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attendance_status", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["committee_meetings.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "name_raw", name="uq_committee_attendance"),
    )
    op.create_index(op.f("ix_committee_attendance_attendance_status"), "committee_attendance", ["attendance_status"])
    op.create_index(op.f("ix_committee_attendance_meeting_id"), "committee_attendance", ["meeting_id"])
    op.create_index(op.f("ix_committee_attendance_name_raw"), "committee_attendance", ["name_raw"])
    op.create_index(op.f("ix_committee_attendance_party_id"), "committee_attendance", ["party_id"])
    op.create_index(op.f("ix_committee_attendance_politician_id"), "committee_attendance", ["politician_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_committee_attendance_politician_id"), table_name="committee_attendance")
    op.drop_index(op.f("ix_committee_attendance_party_id"), table_name="committee_attendance")
    op.drop_index(op.f("ix_committee_attendance_name_raw"), table_name="committee_attendance")
    op.drop_index(op.f("ix_committee_attendance_meeting_id"), table_name="committee_attendance")
    op.drop_index(op.f("ix_committee_attendance_attendance_status"), table_name="committee_attendance")
    op.drop_table("committee_attendance")

    op.drop_index(op.f("ix_committee_meetings_title"), table_name="committee_meetings")
    op.drop_index(op.f("ix_committee_meetings_source_url"), table_name="committee_meetings")
    op.drop_index(op.f("ix_committee_meetings_date"), table_name="committee_meetings")
    op.drop_index(op.f("ix_committee_meetings_committee_id"), table_name="committee_meetings")
    op.drop_table("committee_meetings")

    op.drop_index(op.f("ix_vote_records_vote_value"), table_name="vote_records")
    op.drop_index(op.f("ix_vote_records_vote_event_id"), table_name="vote_records")
    op.drop_index(op.f("ix_vote_records_source_url"), table_name="vote_records")
    op.drop_index(op.f("ix_vote_records_record_level"), table_name="vote_records")
    op.drop_index(op.f("ix_vote_records_politician_id"), table_name="vote_records")
    op.drop_index(op.f("ix_vote_records_party_id"), table_name="vote_records")
    op.drop_table("vote_records")

    op.drop_index(op.f("ix_vote_events_vote_type"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_title"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_source_url"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_result"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_date"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_committee_id"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_chamber"), table_name="vote_events")
    op.drop_index(op.f("ix_vote_events_bill_id"), table_name="vote_events")
    op.drop_table("vote_events")

    op.drop_index(op.f("ix_bill_events_source_url"), table_name="bill_events")
    op.drop_index(op.f("ix_bill_events_event_type"), table_name="bill_events")
    op.drop_index(op.f("ix_bill_events_document_id"), table_name="bill_events")
    op.drop_index(op.f("ix_bill_events_committee_id"), table_name="bill_events")
    op.drop_index(op.f("ix_bill_events_bill_id"), table_name="bill_events")
    op.drop_table("bill_events")

    op.drop_index(op.f("ix_bills_year"), table_name="bills")
    op.drop_index(op.f("ix_bills_title"), table_name="bills")
    op.drop_index(op.f("ix_bills_status"), table_name="bills")
    op.drop_index(op.f("ix_bills_source_url"), table_name="bills")
    op.drop_index(op.f("ix_bills_house"), table_name="bills")
    op.drop_index(op.f("ix_bills_bill_number"), table_name="bills")
    op.drop_table("bills")
