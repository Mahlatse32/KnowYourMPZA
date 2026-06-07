"""add document archive path

Revision ID: 0002_add_document_archive_path
Revises: 0001_initial_schema
Create Date: 2026-06-07 13:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_document_archive_path"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("archive_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "archive_path")
