"""add source-backed expected representative universe

Revision ID: 0013_expected_universe
Revises: 0012_add_iec_vote_totals
Create Date: 2026-06-14 14:00:00.000000

Expected-universe rows are source evidence, not confirmed mappings to internal
politician records. This migration creates no representative rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_expected_universe"
down_revision: Union[str, None] = "0012_add_iec_vote_totals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expected_representative_universe",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("universe_key", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_owner", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("source_identifier", sa.String(length=500), nullable=True),
        sa.Column("term_label", sa.String(length=255), nullable=True),
        sa.Column("chamber", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=100), nullable=True),
        sa.Column("representative_type", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=500), nullable=False),
        sa.Column("party_name", sa.String(length=500), nullable=True),
        sa.Column("role_title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="expected", nullable=False),
        sa.Column("profile_url", sa.String(length=1000), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_source_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("universe_key", name="uq_expected_representative_universe_key"),
    )
    for column in (
        "chamber",
        "party_name",
        "province",
        "representative_type",
        "status",
        "source_name",
        "source_identifier",
        "full_name",
    ):
        op.create_index(
            op.f(f"ix_expected_representative_universe_{column}"),
            "expected_representative_universe",
            [column],
        )


def downgrade() -> None:
    for column in reversed(
        (
            "chamber",
            "party_name",
            "province",
            "representative_type",
            "status",
            "source_name",
            "source_identifier",
            "full_name",
        )
    ):
        op.drop_index(
            op.f(f"ix_expected_representative_universe_{column}"),
            table_name="expected_representative_universe",
        )
    op.drop_table("expected_representative_universe")
