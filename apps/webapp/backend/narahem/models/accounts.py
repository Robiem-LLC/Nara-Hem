"""Household accounts, approvals, enrollment, password resets, email challenges and contact
changes.
"""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Account(Base):
    """A user account: email and/or phone number, password hash, role, status and verification
    state. Phone numbers are E.164 and only used while texting is set up.
    """

    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(16), unique=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10), default="member")
    status: Mapped[str] = mapped_column(String(10), default="pending")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class AccountApproval(Base):
    """Records that the admin approved an account, separate from email verification."""

    __tablename__ = "account_approvals"
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    approved_by: Mapped[str] = mapped_column(String(32))
    created: Mapped[float] = mapped_column(Float)


class EnrollmentClaim(Base):
    """A pending request to join the household, awaiting the admin."""

    __tablename__ = "enrollment_claims"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)
    expires: Mapped[float] = mapped_column(Float)


class PasswordReset(Base):
    """A single-use password reset token, valid for 30 minutes. Only its digest is stored."""

    __tablename__ = "password_resets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    expires: Mapped[float] = mapped_column(Float)


class Challenge(Base):
    """A one-time emailed verification token for an account."""

    __tablename__ = "challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    expires: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class PhoneChallenge(Base):
    """The emailed six-digit code a new phone must enter before it is approved."""

    __tablename__ = "phone_challenges"
    device_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("client_devices.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    proof: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[float] = mapped_column(Float)


class ContactChange(Base):
    """A requested new email address or phone number, waiting for the code sent to it."""

    __tablename__ = "contact_changes"
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(String(254))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
