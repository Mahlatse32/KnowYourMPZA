"""add committee_name to committee_meetings

Revision ID: 0014_committee_names
Revises: 0013_expected_universe
Create Date: 2026-06-26 00:00:00.000000

Stores the raw committee name string from the PMG API on each meeting row so
the identity bootstrap can resolve committee_id retroactively — even when the
committee did not exist yet at ingest time.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_committee_names"
down_revision: Union[str, None] = "0013_expected_universe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "committee_meetings",
        sa.Column("committee_name", sa.String(length=500), nullable=True),
    )
    op.create_index(
        op.f("ix_committee_meetings_committee_name"),
        "committee_meetings",
        ["committee_name"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_committee_meetings_committee_name"),
        table_name="committee_meetings",
    )
    op.drop_column("committee_meetings", "committee_name")
