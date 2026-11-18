"""Persist Alexa reminder IDs and cancellation state.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("alexa_watches") as batch:
        batch.add_column(sa.Column("alert_token", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Old watch rows have no persisted Amazon ID and cannot safely be delivered.
    op.execute("DELETE FROM alexa_watches WHERE alert_token IS NULL")


def downgrade():
    # The old version cannot manage reminders, so discard queued watches.
    op.execute("DELETE FROM alexa_watches")
    with op.batch_alter_table("alexa_watches") as batch:
        batch.drop_column("cancel_requested")
        batch.drop_column("alert_token")
