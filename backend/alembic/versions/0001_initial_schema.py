"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=50), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_parties_short_name"), "parties", ["short_name"], unique=True)

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_name"), "sources", ["name"], unique=True)

    op.create_table(
        "committees",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_committees_slug"), "committees", ["slug"], unique=True)

    op.create_table(
        "politicians",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_url", sa.String(length=500), nullable=True),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_politicians_display_name"), "politicians", ["display_name"], unique=False)
    op.create_index(op.f("ix_politicians_full_name"), "politicians", ["full_name"], unique=False)
    op.create_index(op.f("ix_politicians_party_id"), "politicians", ["party_id"], unique=False)
    op.create_index(op.f("ix_politicians_slug"), "politicians", ["slug"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_source_id"), "documents", ["source_id"], unique=False)
    op.create_index(op.f("ix_documents_source_url"), "documents", ["source_url"], unique=True)

    op.create_table(
        "committee_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("committee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["committee_id"], ["committees.id"]),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("politician_id", "committee_id", "role", name="uq_committee_membership"),
    )
    op.create_index(op.f("ix_committee_memberships_committee_id"), "committee_memberships", ["committee_id"], unique=False)
    op.create_index(op.f("ix_committee_memberships_politician_id"), "committee_memberships", ["politician_id"], unique=False)

    op.create_table(
        "document_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "politician_id", name="uq_document_mention"),
    )
    op.create_index(op.f("ix_document_mentions_document_id"), "document_mentions", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_mentions_politician_id"), "document_mentions", ["politician_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_mentions_politician_id"), table_name="document_mentions")
    op.drop_index(op.f("ix_document_mentions_document_id"), table_name="document_mentions")
    op.drop_table("document_mentions")
    op.drop_index(op.f("ix_committee_memberships_politician_id"), table_name="committee_memberships")
    op.drop_index(op.f("ix_committee_memberships_committee_id"), table_name="committee_memberships")
    op.drop_table("committee_memberships")
    op.drop_index(op.f("ix_documents_source_url"), table_name="documents")
    op.drop_index(op.f("ix_documents_source_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_politicians_slug"), table_name="politicians")
    op.drop_index(op.f("ix_politicians_party_id"), table_name="politicians")
    op.drop_index(op.f("ix_politicians_full_name"), table_name="politicians")
    op.drop_index(op.f("ix_politicians_display_name"), table_name="politicians")
    op.drop_table("politicians")
    op.drop_index(op.f("ix_committees_slug"), table_name="committees")
    op.drop_table("committees")
    op.drop_index(op.f("ix_sources_name"), table_name="sources")
    op.drop_table("sources")
    op.drop_index(op.f("ix_parties_short_name"), table_name="parties")
    op.drop_table("parties")
