"""Browser sign-in sessions and the native apps' rotating refresh grants."""

from sqlalchemy import (
    Float,
    ForeignKey,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LoginSession(Base):
    """A browser login session."""

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class NativeRefreshSession(Base):
    """A phone app's rotating refresh token. Independent of the device's encryption keys."""

    __tablename__ = "native_refresh_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    expires: Mapped[float] = mapped_column(Float)


class RetiredNativeRefresh(Base):
    """Digest of a rotated refresh token, kept to detect reuse of a stolen copy."""

    __tablename__ = "native_refresh_retired"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    retired: Mapped[float] = mapped_column(Float)
    expires: Mapped[float] = mapped_column(Float)
