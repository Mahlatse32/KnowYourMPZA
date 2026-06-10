"""add document metadata

Revision ID: 0008_add_document_metadata
Revises: 0007_expand_coverage_metadata
Create Date: 2026-06-09 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_add_document_metadata"
down_revision: Union[str, None] = "0007_expand_coverage_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("committee_name", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_documents_committee_name"), "documents", ["committee_name"], unique=False)
    op.add_column("document_mentions", sa.Column("match_reason", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("document_mentions", "match_reason")
    op.drop_index(op.f("ix_documents_committee_name"), table_name="documents")
    op.drop_column("documents", "committee_name")
