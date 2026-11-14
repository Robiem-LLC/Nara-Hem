"""Arrival and departure alerts and the push notifications that deliver them."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PushSubscription(Base):
    """A device's push token (APNs or FCM), encrypted."""

    __tablename__ = "push_subscriptions"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(10))
    token: Mapped[str] = mapped_column(Text)


class AlertMemory(Base):
    """Per-device alert state: last saved place, parked position and trip, used to detect
    arrivals and departures. Encrypted.
    """

    __tablename__ = "alert_memory"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(Text)


class ServerAlert(Base):
    """An arrival or departure alert decided by the server. Not ready until its address lookup
    finishes. The payload is encrypted.
    """

    __tablename__ = "server_alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[int] = mapped_column(BigInteger, index=True)
    created: Mapped[float] = mapped_column(Float)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_server_alerts_ready_created", "ready", "created"),)


class PushDelivery(Base):
    """A queued or sent push, used to avoid sending the same push twice."""

    __tablename__ = "push_deliveries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # A record or a server alert.
    record_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), index=True
    )
    created: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[float] = mapped_column(Float, default=0, index=True)
