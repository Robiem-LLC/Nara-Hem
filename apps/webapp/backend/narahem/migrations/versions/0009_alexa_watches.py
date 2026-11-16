"""alexa: one-time "let me know when someone gets home / leaves" watches

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alexa_watches",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("link_id", sa.String(length=32), nullable=False),
        sa.Column("member_id", sa.String(length=32), nullable=False),
        sa.Column("place_id", sa.String(length=64), nullable=False),
        sa.Column("place_name", sa.String(length=80), nullable=False),
        sa.Column("event", sa.String(length=10), nullable=False),
        sa.Column("alexa_user", sa.String(length=300), nullable=False),
        sa.Column("api_endpoint", sa.String(length=100), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("happened", sa.Float(), nullable=True),
        sa.Column("notified", sa.Float(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["alexa_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alexa_watches_link_id", "alexa_watches", ["link_id"])
    op.create_index("ix_alexa_watches_member_id", "alexa_watches", ["member_id"])


def downgrade():
    op.drop_index("ix_alexa_watches_member_id", table_name="alexa_watches")
    op.drop_index("ix_alexa_watches_link_id", table_name="alexa_watches")
    op.drop_table("alexa_watches")
