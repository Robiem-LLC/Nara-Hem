"""Remember whether Textbelt has whitelisted this server's domain for texts.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column("sms_links", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("sms_links")
