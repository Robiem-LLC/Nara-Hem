"""trip labels

Revision ID: 0002
Revises: 0001
Created: 2026-10-26 17:10:42.446077
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trip_labels",
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("labels", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["indexed_trips.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade():
    op.drop_table("trip_labels")
