"""Account, sign-in and setup requests."""

from pydantic import Field

from .base import Input


class SetupInput(Input):
    """First-run setup: setup token, household name and admin credentials."""

    token: str = Field(min_length=8, max_length=256)
    household: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    # Accept older clients' extra username, but admin always authenticates by email.
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str = Field(min_length=15, max_length=128)


class LoginInput(Input):
    """Email and password. native is true for the phone apps, which receive a refresh token."""

    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    native: bool = False


class ChangePasswordInput(Input):
    """Current and new password."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class ResetPasswordInput(Input):
    """Password reset token and new password."""

    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class NativeRefreshInput(Input):
    """A phone app's refresh token."""

    refresh_token: str = Field(min_length=32, max_length=128)


class EmailInput(Input):
    """An email address, or a phone number where the route accepts one."""

    email: str = Field(min_length=3, max_length=254)


class InvitationInput(Input):
    """Who to invite: an email address or phone number, and optionally a phone number to also
    text the invitation to.
    """

    email: str = Field(min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=32)


class InvitationRequestInput(Input):
    """A request for the admin to invite someone."""

    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=80)
    relationship: str = Field(min_length=1, max_length=500)


class ClaimInput(Input):
    """Legacy invitation claim: email, username and password."""

    email: str = Field(min_length=3, max_length=254)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=15, max_length=128)


class VerifyInput(Input):
    """Email verification token, or the invited email address or phone number with the six-digit
    code texted to it, with an optional username and password for new members.
    """

    token: str | None = Field(default=None, min_length=20, max_length=128)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=15, max_length=128)


class ChangeUsernameInput(Input):
    """New display name."""

    username: str = Field(min_length=3, max_length=64)
