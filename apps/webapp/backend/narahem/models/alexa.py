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
    # "store": linked through the Nära Hem relay, the only way to link.
    kind: Mapped[str] = mapped_column(String(10), default="store", server_default="store")
    # The relay's PKCE challenge, checked when it swaps the code.
    challenge: Mapped[str | None] = mapped_column(String(64))
    access: Mapped[str | None] = mapped_column(String(64), unique=True)
    access_expires: Mapped[float] = mapped_column(Float, default=0)
    refresh: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_mark: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float)
    last_used: Mapped[float | None] = mapped_column(Float)


class AlexaWatch(Base):
    """A one-time "let me know when Maya gets home" (or "leaves school") asked through Alexa.
    When the member's phone is next inside (or clearly away from) the place, the server has the
    relay wake the skill, which then has Alexa speak a reminder. Lasts a day at most.
    """

    __tablename__ = "alexa_watches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    link_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("alexa_links.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[str] = mapped_column(String(64))
    place_name: Mapped[str] = mapped_column(String(80))
    # "arrive" or "leave".
    event: Mapped[str] = mapped_column(String(10), default="arrive")
    # Who asked, as Amazon names them to this skill, and the Alexa API region to reach them.
    alexa_user: Mapped[str] = mapped_column(String(300))
    api_endpoint: Mapped[str] = mapped_column(String(100))
    created: Mapped[float] = mapped_column(Float)
    expires: Mapped[float] = mapped_column(Float)
    # When the member arrived or left, and when the relay was asked to wake the skill; the watch
    # is removed once the skill has set the reminder.
    happened: Mapped[float | None] = mapped_column(Float)
    notified: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(default=0)
