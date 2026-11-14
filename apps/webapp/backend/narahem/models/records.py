"""Encrypted household records, who may read them, and each device's latest state."""

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EncryptedRecord(Base):
    """An encrypted, signed record published by a device: location, trip, place, profile or
    event.
    """

    __tablename__ = "encrypted_records"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # No foreign keys: saved places outlive the member and device that wrote them.
    account_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[int] = mapped_column(BigInteger, index=True)
    received_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float | None] = mapped_column(Float, index=True)
    operation: Mapped[str] = mapped_column(String(10))
    envelope: Mapped[str] = mapped_column(Text)
    bytes: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("device_id", "sequence"),
        Index("ix_records_device_received", "device_id", "received_at"),
        Index("ix_record_history", "kind", "captured_at", "id"),
        Index("ix_records_account_kind_time", "account_id", "kind", "captured_at"),
        Index("ix_records_device_kind_time", "device_id", "kind", "captured_at"),
    )


class RecordRecipient(Base):
    """A device a record was encrypted for, and so may fetch."""

    __tablename__ = "record_recipients"
    record_id: Mapped[str] = mapped_column(
        ForeignKey("encrypted_records.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("client_devices.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )


class LatestState(Base):
    """Points to the newest record for each location, place and profile."""

    __tablename__ = "latest_state"
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("encrypted_records.id", ondelete="CASCADE"), unique=True
    )
    captured_at: Mapped[int] = mapped_column(BigInteger)
