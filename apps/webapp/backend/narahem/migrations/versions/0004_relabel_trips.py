"""relabel trips: work out saved trip start and end names again

Trip starts now look back further for the place someone set off from, so names saved with the
old rule are cleared and worked out again by the background job.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM trip_labels")


def downgrade():
    pass  # the names are worked out again either way
