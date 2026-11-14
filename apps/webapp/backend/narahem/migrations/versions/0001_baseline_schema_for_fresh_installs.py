"""Baseline schema for fresh installs

Revision ID: 0001
Revises: (none)
Created: 2026-10-26 04:55:45.506103
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("created", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_entries_created"), ["created"], unique=False)

    op.create_table(
        "diagnostic_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("device_id", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("diagnostic_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_diagnostic_entries_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_diagnostic_entries_category"), ["category"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_diagnostic_entries_created"), ["created"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_diagnostic_entries_device_id"), ["device_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_diagnostic_entries_outcome"), ["outcome"], unique=False
        )

    op.create_table(
        "encrypted_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=True),
        sa.Column("operation", sa.String(length=10), nullable=False),
        sa.Column("envelope", sa.Text(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "sequence"),
    )
    with op.batch_alter_table("encrypted_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_encrypted_records_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_encrypted_records_captured_at"), ["captured_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_encrypted_records_device_id"), ["device_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_encrypted_records_entity_id"), ["entity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_encrypted_records_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_encrypted_records_kind"), ["kind"], unique=False)
        batch_op.create_index("ix_record_history", ["kind", "captured_at", "id"], unique=False)
        batch_op.create_index(
            "ix_records_account_kind_time", ["account_id", "kind", "captured_at"], unique=False
        )
        batch_op.create_index(
            "ix_records_device_kind_time", ["device_id", "kind", "captured_at"], unique=False
        )
        batch_op.create_index(
            "ix_records_device_received", ["device_id", "received_at"], unique=False
        )

    op.create_table(
        "outbox",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_outbox_account_id"), ["account_id"], unique=False)

    op.create_table(
        "rate_limits",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("started", sa.Float(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "roster_revisions",
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("signature", sa.String(length=88), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("revision"),
    )
    op.create_table(
        "service_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.String(length=32), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("anchor", sa.String(length=44), nullable=True),
        sa.Column("bootstrap_hash", sa.String(length=64), nullable=True),
        sa.Column("last_cleanup", sa.Float(), nullable=False),
        sa.Column("push_config", sa.Text(), nullable=True),
        sa.Column("key_check", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household", sa.String(length=80), nullable=True),
        sa.Column("bootstrap_hash", sa.String(length=64), nullable=True),
        sa.Column("smtp", sa.Text(), nullable=True),
        sa.Column("mail_tested", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_approvals",
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=32), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("challenges", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_challenges_account_id"), ["account_id"], unique=False)

    op.create_table(
        "client_devices",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("signing_key", sa.String(length=44), nullable=False),
        sa.Column("box_key", sa.String(length=44), nullable=False),
        sa.Column("credential", sa.String(length=64), nullable=False),
        sa.Column("registration", sa.Text(), nullable=False),
        sa.Column("registration_signature", sa.String(length=88), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("sharing", sa.Boolean(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("seen", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("box_key"),
        sa.UniqueConstraint("credential"),
        sa.UniqueConstraint("signing_key"),
    )
    with op.batch_alter_table("client_devices", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_client_devices_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "enrollment_claims",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("enrollment_claims", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_enrollment_claims_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "indexed_trips",
        sa.Column("event_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("ended_at", sa.BigInteger(), nullable=False),
        sa.Column("trip_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("encrypted_trip", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["encrypted_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    with op.batch_alter_table("indexed_trips", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_indexed_trips_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            "ix_indexed_trips_member_date", ["account_id", "ended_at", "event_id"], unique=False
        )

    op.create_table(
        "latest_state",
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["encrypted_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("kind", "entity_id"),
        sa.UniqueConstraint("record_id"),
    )
    op.create_table(
        "native_refresh_retired",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("retired", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("native_refresh_retired", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_native_refresh_retired_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "native_refresh_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("native_refresh_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_native_refresh_sessions_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_password_resets_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "server_alerts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.BigInteger(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("server_alerts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_server_alerts_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_server_alerts_captured_at"), ["captured_at"], unique=False
        )
        batch_op.create_index("ix_server_alerts_ready_created", ["ready", "created"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("csrf", sa.String(length=64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_account_id"), ["account_id"], unique=False)

    op.create_table(
        "alert_memory",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "device_bootstrap_challenges",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    with op.batch_alter_table("device_bootstrap_challenges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_device_bootstrap_challenges_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "device_permission_snapshots",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("foreground_location", sa.Boolean(), nullable=False),
        sa.Column("background_location", sa.Boolean(), nullable=False),
        sa.Column("remote_alarm", sa.Boolean(), nullable=False),
        sa.Column("dnd_access", sa.Boolean(), nullable=False),
        sa.Column("notifications", sa.Boolean(), nullable=False),
        sa.Column("sharing", sa.Boolean(), nullable=False),
        sa.Column("reported_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "device_sharing_audiences",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("account_ids", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "find_phone_capabilities",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("seen", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "find_phone_commands",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("issuer_id", sa.String(length=32), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("envelope", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("reported_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("find_phone_commands", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_find_phone_commands_target_id"), ["target_id"], unique=False
        )

    op.create_table(
        "phone_challenges",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("proof", sa.String(length=64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    with op.batch_alter_table("phone_challenges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_phone_challenges_account_id"), ["account_id"], unique=False
        )

    op.create_table(
        "push_deliveries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("created", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("push_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_push_deliveries_device_id"), ["device_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_push_deliveries_record_id"), ["record_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_push_deliveries_retry_at"), ["retry_at"], unique=False)

    op.create_table(
        "push_subscriptions",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "record_recipients",
        sa.Column("record_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["client_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["record_id"], ["encrypted_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("record_id", "device_id"),
    )
    with op.batch_alter_table("record_recipients", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_recipients_device_id"), ["device_id"], unique=False
        )


def downgrade():
    with op.batch_alter_table("record_recipients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_recipients_device_id"))

    op.drop_table("record_recipients")
    op.drop_table("push_subscriptions")
    with op.batch_alter_table("push_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_push_deliveries_retry_at"))
        batch_op.drop_index(batch_op.f("ix_push_deliveries_record_id"))
        batch_op.drop_index(batch_op.f("ix_push_deliveries_device_id"))

    op.drop_table("push_deliveries")
    with op.batch_alter_table("phone_challenges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_phone_challenges_account_id"))

    op.drop_table("phone_challenges")
    with op.batch_alter_table("find_phone_commands", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_find_phone_commands_target_id"))

    op.drop_table("find_phone_commands")
    op.drop_table("find_phone_capabilities")
    op.drop_table("device_sharing_audiences")
    op.drop_table("device_permission_snapshots")
    with op.batch_alter_table("device_bootstrap_challenges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_device_bootstrap_challenges_account_id"))

    op.drop_table("device_bootstrap_challenges")
    op.drop_table("alert_memory")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_account_id"))

    op.drop_table("sessions")
    with op.batch_alter_table("server_alerts", schema=None) as batch_op:
        batch_op.drop_index("ix_server_alerts_ready_created")
        batch_op.drop_index(batch_op.f("ix_server_alerts_captured_at"))
        batch_op.drop_index(batch_op.f("ix_server_alerts_account_id"))

    op.drop_table("server_alerts")
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_password_resets_account_id"))

    op.drop_table("password_resets")
    with op.batch_alter_table("native_refresh_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_native_refresh_sessions_account_id"))

    op.drop_table("native_refresh_sessions")
    with op.batch_alter_table("native_refresh_retired", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_native_refresh_retired_account_id"))

    op.drop_table("native_refresh_retired")
    op.drop_table("latest_state")
    with op.batch_alter_table("indexed_trips", schema=None) as batch_op:
        batch_op.drop_index("ix_indexed_trips_member_date")
        batch_op.drop_index(batch_op.f("ix_indexed_trips_account_id"))

    op.drop_table("indexed_trips")
    with op.batch_alter_table("enrollment_claims", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_enrollment_claims_account_id"))

    op.drop_table("enrollment_claims")
    with op.batch_alter_table("client_devices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_client_devices_account_id"))

    op.drop_table("client_devices")
    with op.batch_alter_table("challenges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_challenges_account_id"))

    op.drop_table("challenges")
    op.drop_table("account_approvals")
    op.drop_table("settings")
    op.drop_table("service_state")
    op.drop_table("roster_revisions")
    op.drop_table("rate_limits")
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_outbox_account_id"))

    op.drop_table("outbox")
    with op.batch_alter_table("encrypted_records", schema=None) as batch_op:
        batch_op.drop_index("ix_records_device_received")
        batch_op.drop_index("ix_records_device_kind_time")
        batch_op.drop_index("ix_records_account_kind_time")
        batch_op.drop_index("ix_record_history")
        batch_op.drop_index(batch_op.f("ix_encrypted_records_kind"))
        batch_op.drop_index(batch_op.f("ix_encrypted_records_expires_at"))
        batch_op.drop_index(batch_op.f("ix_encrypted_records_entity_id"))
        batch_op.drop_index(batch_op.f("ix_encrypted_records_device_id"))
        batch_op.drop_index(batch_op.f("ix_encrypted_records_captured_at"))
        batch_op.drop_index(batch_op.f("ix_encrypted_records_account_id"))

    op.drop_table("encrypted_records")
    with op.batch_alter_table("diagnostic_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_diagnostic_entries_outcome"))
        batch_op.drop_index(batch_op.f("ix_diagnostic_entries_device_id"))
        batch_op.drop_index(batch_op.f("ix_diagnostic_entries_created"))
        batch_op.drop_index(batch_op.f("ix_diagnostic_entries_category"))
        batch_op.drop_index(batch_op.f("ix_diagnostic_entries_account_id"))

    op.drop_table("diagnostic_entries")
    with op.batch_alter_table("audit_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_entries_created"))

    op.drop_table("audit_entries")
    op.drop_table("accounts")
