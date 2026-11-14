"""alexa store skill: links made through the Nära Hem relay

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("alexa_links") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=10), nullable=False, server_default="own")
        )
        batch.add_column(sa.Column("challenge", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("alexa_links") as batch:
        batch.drop_column("challenge")
        batch.drop_column("kind")
