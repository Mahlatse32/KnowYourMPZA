"""add question parse metadata

Revision ID: 0006_add_question_parse_metadata
Revises: 0005_add_parliamentary_questions
Create Date: 2026-06-07 20:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_add_question_parse_metadata"
down_revision: Union[str, None] = "0005_add_parliamentary_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parliamentary_questions", sa.Column("source_file_type", sa.String(length=50), nullable=True))
    op.add_column("parliamentary_questions", sa.Column("extracted_text_available", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("parliamentary_questions", sa.Column("parse_status", sa.String(length=100), nullable=True))
    op.add_column("parliamentary_questions", sa.Column("parse_notes", sa.Text(), nullable=True))
    op.create_index(op.f("ix_parliamentary_questions_source_file_type"), "parliamentary_questions", ["source_file_type"])
    op.create_index(op.f("ix_parliamentary_questions_parse_status"), "parliamentary_questions", ["parse_status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_parliamentary_questions_parse_status"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_source_file_type"), table_name="parliamentary_questions")
    op.drop_column("parliamentary_questions", "parse_notes")
    op.drop_column("parliamentary_questions", "parse_status")
    op.drop_column("parliamentary_questions", "extracted_text_available")
    op.drop_column("parliamentary_questions", "source_file_type")
