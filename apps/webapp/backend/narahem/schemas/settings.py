"""Server settings an administrator changes: outgoing mail and push providers."""

from pydantic import Field

from .base import Input


class MailInput(Input):
    """SMTP settings."""

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    mode: str = Field(pattern="^(starttls|tls)$")
    username: str = Field(max_length=254)
    password: str | None = Field(default=None, max_length=1024)
    sender: str = Field(min_length=3, max_length=254)


class APNsConfig(Input):
    """Apple push settings."""

    team_id: str = Field(pattern="^[A-Z0-9]{10}$")
    key_id: str = Field(pattern="^[A-Z0-9]{10}$")
    topic: str = Field(pattern="^[A-Za-z0-9.-]{3,200}$")
    sandbox: bool = True
    private_key: str = Field(min_length=50, max_length=10000)


class PushConfig(Input):
    """Push settings for APNs and FCM."""

    apns: APNsConfig | None = None
    fcm: dict | None = None


class PushTestInput(Input):
    """Test push target. Without device_id, the admin's own devices are used."""

    device_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
