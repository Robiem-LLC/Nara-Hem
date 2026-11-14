"""alexa: account links and the skill's settings

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alexa_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("code_expires", sa.Float(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=300), nullable=False),
        sa.Column("access", sa.String(length=64), nullable=True),
        sa.Column("access_expires", sa.Float(), nullable=False),
        sa.Column("refresh", sa.String(length=64), nullable=True),
        sa.Column("password_mark", sa.String(length=64), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("last_used", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("access"),
        sa.UniqueConstraint("refresh"),
    )
    op.create_index("ix_alexa_links_account_id", "alexa_links", ["account_id"])
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("alexa", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("alexa")
    op.drop_index("ix_alexa_links_account_id", table_name="alexa_links")
    op.drop_table("alexa_links")
