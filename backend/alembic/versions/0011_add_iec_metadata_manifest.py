"""add IEC election metadata and source manifest tables

Revision ID: 0011_add_iec_metadata_manifest
Revises: 0010_add_ingestion_sweep_states
Create Date: 2026-06-13 13:30:00.000000

Metadata/manifest only — no vote totals, candidates, winners, office-bearers,
or geography mappings are stored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_add_iec_metadata_manifest"
down_revision: Union[str, None] = "0010_add_ingestion_sweep_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iec_elections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("election_key", sa.String(length=255), nullable=False),
        sa.Column("election_type", sa.String(length=100), nullable=False),
        sa.Column("election_year", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("geography_level", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_identifier", sa.String(length=255), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_metadata_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("election_key", name="uq_iec_elections_election_key"),
    )
    op.create_index(op.f("ix_iec_elections_election_key"), "iec_elections", ["election_key"])
    op.create_index(op.f("ix_iec_elections_election_type"), "iec_elections", ["election_type"])
    op.create_index(op.f("ix_iec_elections_election_year"), "iec_elections", ["election_year"])

    op.create_table(
        "iec_source_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_key", sa.String(length=600), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("election_key", sa.String(length=255), nullable=True),
        sa.Column("election_type", sa.String(length=100), nullable=True),
        sa.Column("election_year", sa.Integer(), nullable=True),
        sa.Column("geography_level", sa.String(length=100), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("reachable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("parser_readiness", sa.String(length=50), server_default="unknown", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("revision_hint", sa.String(length=255), nullable=True),
        sa.Column("raw_manifest_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_key", name="uq_iec_source_manifests_manifest_key"),
    )
    op.create_index(op.f("ix_iec_source_manifests_manifest_key"), "iec_source_manifests", ["manifest_key"])
    op.create_index(op.f("ix_iec_source_manifests_source_url"), "iec_source_manifests", ["source_url"])
    op.create_index(op.f("ix_iec_source_manifests_election_key"), "iec_source_manifests", ["election_key"])
    op.create_index(op.f("ix_iec_source_manifests_election_type"), "iec_source_manifests", ["election_type"])
    op.create_index(op.f("ix_iec_source_manifests_election_year"), "iec_source_manifests", ["election_year"])
    op.create_index(op.f("ix_iec_source_manifests_reachable"), "iec_source_manifests", ["reachable"])
    op.create_index(op.f("ix_iec_source_manifests_parser_readiness"), "iec_source_manifests", ["parser_readiness"])


def downgrade() -> None:
    op.drop_index(op.f("ix_iec_source_manifests_parser_readiness"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_reachable"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_election_year"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_election_type"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_election_key"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_source_url"), table_name="iec_source_manifests")
    op.drop_index(op.f("ix_iec_source_manifests_manifest_key"), table_name="iec_source_manifests")
    op.drop_table("iec_source_manifests")

    op.drop_index(op.f("ix_iec_elections_election_year"), table_name="iec_elections")
    op.drop_index(op.f("ix_iec_elections_election_type"), table_name="iec_elections")
    op.drop_index(op.f("ix_iec_elections_election_key"), table_name="iec_elections")
    op.drop_table("iec_elections")
