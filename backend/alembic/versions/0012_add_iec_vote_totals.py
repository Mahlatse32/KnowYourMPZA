"""add source-backed IEC vote totals

Revision ID: 0012_add_iec_vote_totals
Revises: 0011_add_iec_metadata_manifest
Create Date: 2026-06-13 16:00:00.000000

Vote totals only. This schema does not represent winners, office-bearers,
councillors, or mappings to internal party/candidate/geography entities.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_add_iec_vote_totals"
down_revision: Union[str, None] = "0011_add_iec_metadata_manifest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iec_vote_totals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_key", sa.String(length=100), nullable=False),
        sa.Column("manifest_key", sa.String(length=600), nullable=False),
        sa.Column("election_key", sa.String(length=255), nullable=True),
        sa.Column("election_type", sa.String(length=100), nullable=True),
        sa.Column("election_year", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_format", sa.String(length=50), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("source_contest_id", sa.String(length=255), nullable=False),
        sa.Column("source_contest_name", sa.String(length=500), nullable=True),
        sa.Column("geography_level", sa.String(length=100), nullable=True),
        sa.Column("source_geography_id", sa.String(length=255), nullable=True),
        sa.Column("source_geography_name", sa.String(length=500), nullable=True),
        sa.Column("source_party_id", sa.String(length=255), nullable=False),
        sa.Column("source_party_name", sa.String(length=500), nullable=True),
        sa.Column("source_candidate_id", sa.String(length=255), nullable=True),
        sa.Column("source_candidate_name", sa.String(length=500), nullable=True),
        sa.Column("vote_total", sa.Integer(), nullable=False),
        sa.Column("raw_row_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("row_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_key", name="uq_iec_vote_totals_result_key"),
    )
    for column in (
        "result_key", "manifest_key", "election_key", "election_type", "election_year",
        "source_url", "source_contest_id", "source_geography_id", "source_party_id",
        "source_candidate_id",
    ):
        op.create_index(op.f(f"ix_iec_vote_totals_{column}"), "iec_vote_totals", [column])
    op.create_index(
        "ix_iec_vote_totals_election_type_year",
        "iec_vote_totals",
        ["election_type", "election_year"],
    )
    op.create_index(
        "ix_iec_vote_totals_geography",
        "iec_vote_totals",
        ["geography_level", "source_geography_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_iec_vote_totals_geography", table_name="iec_vote_totals")
    op.drop_index("ix_iec_vote_totals_election_type_year", table_name="iec_vote_totals")
    for column in reversed((
        "result_key", "manifest_key", "election_key", "election_type", "election_year",
        "source_url", "source_contest_id", "source_geography_id", "source_party_id",
        "source_candidate_id",
    )):
        op.drop_index(op.f(f"ix_iec_vote_totals_{column}"), table_name="iec_vote_totals")
    op.drop_table("iec_vote_totals")
