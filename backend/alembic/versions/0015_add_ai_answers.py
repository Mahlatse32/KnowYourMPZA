"""add ai answers cache

Revision ID: 0015_ai_answers
Revises: 0014_committee_names
Create Date: 2026-07-25 00:00:00.000000

Stores source-backed AI answers keyed by a normalized question. The table is
additive and does not alter ingestion records or production source data.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_ai_answers"
down_revision: Union[str, None] = "0014_committee_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=100), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("data_snapshot", sa.JSON(), nullable=False),
        sa.Column("model_used", sa.String(length=100), nullable=False),
        sa.Column("coverage_notice", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_answers_normalized_question"), "ai_answers", ["normalized_question"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_answers_normalized_question"), table_name="ai_answers")
    op.drop_table("ai_answers")
