"""add politician aliases

Revision ID: 0003_add_politician_aliases
Revises: 0002_add_document_archive_path
Create Date: 2026-06-07 14:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_add_politician_aliases"
down_revision: Union[str, None] = "0002_add_document_archive_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "politician_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("politician_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("alias_type", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("politician_id", "alias", name="uq_politician_alias"),
    )
    op.create_index(op.f("ix_politician_aliases_alias"), "politician_aliases", ["alias"], unique=False)
    op.create_index(op.f("ix_politician_aliases_politician_id"), "politician_aliases", ["politician_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_politician_aliases_politician_id"), table_name="politician_aliases")
    op.drop_index(op.f("ix_politician_aliases_alias"), table_name="politician_aliases")
    op.drop_table("politician_aliases")
