"""add ingestion_sweep_states for incremental accountability sweeps

Revision ID: 0010_add_ingestion_sweep_states
Revises: 0009_add_accountability_layer
Create Date: 2026-06-12 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_add_ingestion_sweep_states"
down_revision: Union[str, None] = "0009_add_accountability_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_sweep_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("stream_name", sa.String(length=100), nullable=False),
        sa.Column("cursor_type", sa.String(length=50), nullable=False, server_default="page"),
        sa.Column("cursor_value", sa.String(length=255), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_size", sa.Integer(), nullable=True),
        sa.Column("max_pages_per_run", sa.Integer(), nullable=True),
        sa.Column("total_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_total", sa.Integer(), nullable=True),
        sa.Column("sweeps_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=50), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_name", "stream_name", name="uq_sweep_source_stream"),
    )
    op.create_index(op.f("ix_ingestion_sweep_states_source_name"), "ingestion_sweep_states", ["source_name"])
    op.create_index(op.f("ix_ingestion_sweep_states_stream_name"), "ingestion_sweep_states", ["stream_name"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_sweep_states_stream_name"), table_name="ingestion_sweep_states")
    op.drop_index(op.f("ix_ingestion_sweep_states_source_name"), table_name="ingestion_sweep_states")
    op.drop_table("ingestion_sweep_states")
