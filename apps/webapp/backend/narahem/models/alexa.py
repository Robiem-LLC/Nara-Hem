"""Alexa account links: the admin's sign-in from the Alexa app, revocable from the server."""

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AlexaLink(Base):
    """One Alexa account linked to the admin. Starts as a one-time code from the sign-in page,
    which Amazon exchanges for tokens. Only digests of the code and tokens are stored, and the
    link ends if the admin's password changes.
    """

    __tablename__ = "alexa_links"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    code_expires: Mapped[float] = mapped_column(Float, default=0)
    redirect_uri: Mapped[str] = mapped_column(String(300))
    # "store" for the published skill through the Nära Hem relay, "own" for a private skill.
    kind: Mapped[str] = mapped_column(String(10), default="own", server_default="own")
    # The relay's PKCE challenge, checked when it swaps the code.
    challenge: Mapped[str | None] = mapped_column(String(64))
    access: Mapped[str | None] = mapped_column(String(64), unique=True)
    access_expires: Mapped[float] = mapped_column(Float, default=0)
    refresh: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_mark: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float)
    last_used: Mapped[float | None] = mapped_column(Float)
