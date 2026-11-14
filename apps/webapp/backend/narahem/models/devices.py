"""Trusted devices, their sharing audiences, enrollment and reported permissions."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ClientDevice(Base):
    """A phone or browser: public keys, owner, approval status and last contact."""

    __tablename__ = "client_devices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    signing_key: Mapped[str] = mapped_column(String(44), unique=True)
    box_key: Mapped[str] = mapped_column(String(44), unique=True)
    credential: Mapped[str] = mapped_column(String(64), unique=True)
    registration: Mapped[str] = mapped_column(Text)
    registration_signature: Mapped[str] = mapped_column(String(88))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    sharing: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    created: Mapped[float] = mapped_column(Float)
    seen: Mapped[float] = mapped_column(Float, default=0)


class DeviceSharingAudience(Base):
    """The accounts allowed to see a device's location. No row means every approved member."""

    __tablename__ = "device_sharing_audiences"
    device_id: Mapped[str] = mapped_column(
        ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    account_ids: Mapped[str] = mapped_column(Text)


class DeviceBootstrapChallenge(Base):
    """One-time email code for registering the first admin device."""

    __tablename__ = "device_bootstrap_challenges"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class RosterRevision(Base):
    """One signed version of the household device list, linked to the previous version."""

    __tablename__ = "roster_revisions"
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(88))
    hash: Mapped[str] = mapped_column(String(64))


class DevicePermissionSnapshot(Base):
    """The OS permission state a device last reported. Self-reported; not proof the device is
    reachable.
    """

    __tablename__ = "device_permission_snapshots"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    foreground_location: Mapped[bool] = mapped_column(Boolean)
    background_location: Mapped[bool] = mapped_column(Boolean)
    remote_alarm: Mapped[bool] = mapped_column(Boolean)
    dnd_access: Mapped[bool] = mapped_column(Boolean)
    notifications: Mapped[bool] = mapped_column(Boolean)
    sharing: Mapped[bool] = mapped_column(Boolean)
    reported_at: Mapped[float] = mapped_column(Float)
