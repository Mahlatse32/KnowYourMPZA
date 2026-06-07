"""status and ingestion runs

Revision ID: 0004_status_and_ingestion_runs
Revises: 0003_add_politician_aliases
Create Date: 2026-06-07 15:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_status_and_ingestion_runs"
down_revision: Union[str, None] = "0003_add_politician_aliases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("politicians", sa.Column("source_last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("politicians", sa.Column("source_status", sa.String(length=100), nullable=True))
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("run_type", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempted_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_runs_run_type"), "ingestion_runs", ["run_type"], unique=False)
    op.create_index(op.f("ix_ingestion_runs_source_name"), "ingestion_runs", ["source_name"], unique=False)
    op.create_table(
        "ingestion_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_errors_ingestion_run_id"), "ingestion_errors", ["ingestion_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_errors_ingestion_run_id"), table_name="ingestion_errors")
    op.drop_table("ingestion_errors")
    op.drop_index(op.f("ix_ingestion_runs_source_name"), table_name="ingestion_runs")
    op.drop_index(op.f("ix_ingestion_runs_run_type"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_column("politicians", "source_status")
    op.drop_column("politicians", "source_last_seen_at")
