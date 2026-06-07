"""add parliamentary questions

Revision ID: 0005_add_parliamentary_questions
Revises: 0004_status_and_ingestion_runs
Create Date: 2026-06-07 15:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_add_parliamentary_questions"
down_revision: Union[str, None] = "0004_status_and_ingestion_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parliamentary_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_number", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asked_by_name", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("minister", sa.String(length=255), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("asked_date", sa.Date(), nullable=True),
        sa.Column("answered_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("archive_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index(op.f("ix_parliamentary_questions_asked_by_name"), "parliamentary_questions", ["asked_by_name"])
    op.create_index(op.f("ix_parliamentary_questions_department"), "parliamentary_questions", ["department"])
    op.create_index(op.f("ix_parliamentary_questions_minister"), "parliamentary_questions", ["minister"])
    op.create_index(op.f("ix_parliamentary_questions_politician_id"), "parliamentary_questions", ["politician_id"])
    op.create_index(op.f("ix_parliamentary_questions_question_number"), "parliamentary_questions", ["question_number"])
    op.create_index(op.f("ix_parliamentary_questions_source_id"), "parliamentary_questions", ["source_id"])
    op.create_index(op.f("ix_parliamentary_questions_source_url"), "parliamentary_questions", ["source_url"], unique=True)
    op.create_index(op.f("ix_parliamentary_questions_status"), "parliamentary_questions", ["status"])

    op.create_table(
        "question_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("match_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["parliamentary_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_question_mentions_politician_id"), "question_mentions", ["politician_id"])
    op.create_index(op.f("ix_question_mentions_question_id"), "question_mentions", ["question_id"])

    op.create_table(
        "unresolved_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("raw_value", sa.String(length=500), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_unresolved_entities_entity_type"), "unresolved_entities", ["entity_type"])
    op.create_index(op.f("ix_unresolved_entities_raw_value"), "unresolved_entities", ["raw_value"])
    op.create_index(op.f("ix_unresolved_entities_source_name"), "unresolved_entities", ["source_name"])
    op.create_index(op.f("ix_unresolved_entities_source_url"), "unresolved_entities", ["source_url"])


def downgrade() -> None:
    op.drop_index(op.f("ix_unresolved_entities_source_url"), table_name="unresolved_entities")
    op.drop_index(op.f("ix_unresolved_entities_source_name"), table_name="unresolved_entities")
    op.drop_index(op.f("ix_unresolved_entities_raw_value"), table_name="unresolved_entities")
    op.drop_index(op.f("ix_unresolved_entities_entity_type"), table_name="unresolved_entities")
    op.drop_table("unresolved_entities")
    op.drop_index(op.f("ix_question_mentions_question_id"), table_name="question_mentions")
    op.drop_index(op.f("ix_question_mentions_politician_id"), table_name="question_mentions")
    op.drop_table("question_mentions")
    op.drop_index(op.f("ix_parliamentary_questions_status"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_source_url"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_source_id"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_question_number"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_politician_id"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_minister"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_department"), table_name="parliamentary_questions")
    op.drop_index(op.f("ix_parliamentary_questions_asked_by_name"), table_name="parliamentary_questions")
    op.drop_table("parliamentary_questions")
