"""expand coverage metadata

Revision ID: 0007_expand_coverage_metadata
Revises: 0006_add_question_parse_metadata
Create Date: 2026-06-07 22:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_expand_coverage_metadata"
down_revision: Union[str, None] = "0006_add_question_parse_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parties", sa.Column("source_url", sa.String(length=500), nullable=True))
    op.add_column("parties", sa.Column("source_last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("committees", sa.Column("source_url", sa.String(length=500), nullable=True))
    op.add_column("committees", sa.Column("source_last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("committee_memberships", sa.Column("source_last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("committee_memberships", sa.Column("source_status", sa.String(length=100), nullable=True))
    op.add_column("unresolved_entities", sa.Column("status", sa.String(length=50), nullable=False, server_default="OPEN"))
    op.add_column("unresolved_entities", sa.Column("resolved_politician_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("unresolved_entities", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("unresolved_entities", sa.Column("resolution_notes", sa.Text(), nullable=True))
    op.create_index(op.f("ix_unresolved_entities_status"), "unresolved_entities", ["status"], unique=False)
    op.create_index(
        op.f("ix_unresolved_entities_resolved_politician_id"),
        "unresolved_entities",
        ["resolved_politician_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_unresolved_entities_resolved_politician_id",
        "unresolved_entities",
        "politicians",
        ["resolved_politician_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_unresolved_entities_resolved_politician_id", "unresolved_entities", type_="foreignkey")
    op.drop_index(op.f("ix_unresolved_entities_resolved_politician_id"), table_name="unresolved_entities")
    op.drop_index(op.f("ix_unresolved_entities_status"), table_name="unresolved_entities")
    op.drop_column("unresolved_entities", "resolution_notes")
    op.drop_column("unresolved_entities", "resolved_at")
    op.drop_column("unresolved_entities", "resolved_politician_id")
    op.drop_column("unresolved_entities", "status")
    op.drop_column("committee_memberships", "source_status")
    op.drop_column("committee_memberships", "source_last_seen_at")
    op.drop_column("committees", "source_last_seen_at")
    op.drop_column("committees", "source_url")
    op.drop_column("parties", "source_last_seen_at")
    op.drop_column("parties", "source_url")
