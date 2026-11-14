"""Device registration, the trusted-device roster, permissions and push subscriptions."""

from typing import Literal

from pydantic import Field

from .base import MAX_DEVICES, CryptoInput, Input


class DevicePermissionInput(Input):
    """Permission flags reported by a phone."""

    foreground_location: bool
    background_location: bool
    remote_alarm: bool
    dnd_access: bool
    notifications: bool
    sharing: bool


class RegisterInput(CryptoInput):
    """A new device's public keys and signed registration."""

    id: str = Field(pattern="^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=64)
    signing_key: str = Field(max_length=44)
    box_key: str = Field(max_length=44)
    signature: str = Field(max_length=88)
    platform: Literal["web", "ios", "android"] | None = None


class Identity(CryptoInput):
    """One device entry in a signed roster."""

    id: str = Field(pattern="^[a-f0-9]{32}$")
    account_id: str = Field(pattern="^[a-f0-9]{32}$")
    signing_key: str = Field(max_length=44)
    box_key: str = Field(max_length=44)


class RosterBody(CryptoInput):
    """The signed part of a roster change: the full device list and the hash of the previous
    revision.
    """

    domain: Literal["narahem.roster.v1"]
    household: str = Field(pattern="^[a-f0-9]{32}$")
    revision: int = Field(ge=1, le=2147483647)
    previous: str = Field(pattern="^([a-f0-9]{64})?$")
    signer: str = Field(pattern="^[a-f0-9]{32}$")
    devices: list[Identity] = Field(min_length=1, max_length=MAX_DEVICES)
    issued_at: int = Field(ge=0)
    pairing_target: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    pairing_hash: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")


class RosterInput(Input):
    """A roster change, its signature, and for the first roster a proof of admin identity."""

    body: RosterBody
    signature: str = Field(max_length=88)
    bootstrap_token: str | None = Field(default=None, max_length=128)
    bootstrap_email_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class SubscribeInput(Input):
    """A device's push token and provider."""

    provider: str = Field(pattern="^(apns|fcm)$")
    token: str = Field(min_length=16, max_length=4096)
    # The build's APNs entitlement determines the environment, not the server.
    environment: Literal["sandbox", "production"] | None = None
