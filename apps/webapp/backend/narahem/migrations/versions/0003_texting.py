"""texting: phone numbers on accounts and the Textbelt key

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("phone", sa.String(length=16), nullable=True))
        batch.alter_column("email", existing_type=sa.String(length=254), nullable=True)
        batch.create_unique_constraint("uq_accounts_phone", ["phone"])
    # Older servers stored phone-number accounts in the email column.
    op.execute(
        "UPDATE accounts SET phone = email, email = NULL "
        "WHERE email NOT LIKE '%@%' AND email LIKE '+%'"
    )
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column("sms", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sms_checked_key", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("sms_valid", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("sms_quota", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sms_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sms_checked", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("settings") as batch:
        for column in ("sms_checked", "sms_error", "sms_quota", "sms_valid", "sms_checked_key"):
            batch.drop_column(column)
        batch.drop_column("sms")
    op.execute("UPDATE accounts SET email = phone WHERE email IS NULL")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("uq_accounts_phone", type_="unique")
        batch.alter_column("email", existing_type=sa.String(length=254), nullable=False)
        batch.drop_column("phone")
