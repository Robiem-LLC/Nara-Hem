"""alexa: the store skill only; drop the private skill's links and settings

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM alexa_links WHERE kind <> 'store'")
    with op.batch_alter_table("alexa_links") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=10),
            existing_nullable=False,
            server_default="store",
        )
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("alexa")


def downgrade():
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("alexa", sa.Text(), nullable=True))
    with op.batch_alter_table("alexa_links") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=10),
            existing_nullable=False,
            server_default="own",
        )
