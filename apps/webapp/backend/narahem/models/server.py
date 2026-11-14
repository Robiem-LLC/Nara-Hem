"""Server settings and bookkeeping: rate limits, outgoing mail, audit and diagnostics."""

from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Settings(Base):
    """Server settings: household name, mail, texting and setup state. Single row."""

    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    household: Mapped[str | None] = mapped_column(String(80))
    bootstrap_hash: Mapped[str | None] = mapped_column(String(64))
    smtp: Mapped[str | None] = mapped_column(Text)
    mail_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    # The Textbelt key saved in Admin settings, encrypted. NARAHEM_TEXTBELT_KEY overrides it.
    sms: Mapped[str | None] = mapped_column(Text)
    # The last key check: which key (a digest), whether it worked, credit left and any error.
    sms_checked_key: Mapped[str | None] = mapped_column(String(64))
    sms_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_quota: Mapped[int | None] = mapped_column(Integer)
    sms_error: Mapped[str | None] = mapped_column(Text)
    sms_checked: Mapped[float | None] = mapped_column(Float)
    # Alexa skill ID and client secret, encrypted with the server key.
    alexa: Mapped[str | None] = mapped_column(Text)


class Outbox(Base):
    """Queued email."""

    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # An account ID, or a prefixed key ("req-", "r:", "p:") for mail before an account exists.
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[float] = mapped_column(Float, default=0)


class Rate(Base):
    """A rate-limit counter."""

    __tablename__ = "rate_limits"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started: Mapped[float] = mapped_column(Float)
    count: Mapped[int] = mapped_column(Integer)


class ServiceState(Base):
    """The household's identity, roster revision and retention. Single row, locked while
    publishing.
    """

    __tablename__ = "service_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[str] = mapped_column(String(32))
    retention_days: Mapped[int] = mapped_column(Integer, default=14)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    anchor: Mapped[str | None] = mapped_column(String(44))
    bootstrap_hash: Mapped[str | None] = mapped_column(String(64))
    last_cleanup: Mapped[float] = mapped_column(Float, default=0)
    push_config: Mapped[str | None] = mapped_column(Text)
    key_check: Mapped[str] = mapped_column(Text)


class AuditEntry(Base):
    """An audit log entry."""

    __tablename__ = "audit_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(36))
    target_id: Mapped[str | None] = mapped_column(String(36))
    created: Mapped[float] = mapped_column(Float, index=True)


class DiagnosticEntry(Base):
    """A diagnostics log entry (push, mail, trips and so on)."""

    __tablename__ = "diagnostic_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    action: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[str | None] = mapped_column(String(32), index=True)
    device_id: Mapped[str | None] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    created: Mapped[float] = mapped_column(Float, index=True)
    details: Mapped[str] = mapped_column(Text)
