"""Find my phone: what each phone can do and the commands sent to it."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FindPhoneCapability(Base):
    """Whether Find My Phone is enabled on a device, and its platform."""

    __tablename__ = "find_phone_capabilities"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    platform: Mapped[str] = mapped_column(String(16))
    seen: Mapped[float] = mapped_column(Float)


class FindPhoneCommand(Base):
    """A signed ring or stop command for a device and its status."""

    __tablename__ = "find_phone_commands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), index=True
    )
    issuer_id: Mapped[str] = mapped_column(String(32))
    created: Mapped[float] = mapped_column(Float)
    expires: Mapped[float] = mapped_column(Float)
    envelope: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    reason: Mapped[str] = mapped_column(String(32), default="")
    reported_at: Mapped[float | None] = mapped_column(Float)
