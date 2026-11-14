"""Find my phone: capabilities, commands and reports."""

from typing import Literal

from pydantic import Field

from .base import Input


class FindCapabilityInput(Input):
    """A phone's Find My Phone setting and platform."""

    enabled: bool
    platform: Literal["android", "ios"]


class FindCommandBody(Input):
    """The signed part of a ring or stop command."""

    domain: Literal["narahem.find-phone.v1"]
    household: str = Field(pattern=r"^[a-f0-9]{32}$")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    issuer: str = Field(pattern=r"^[a-f0-9]{32}$")
    target: str = Field(pattern=r"^[a-f0-9]{32}$")
    action: Literal["ring", "stop"]
    issued_at: int
    expires_at: int


class FindCommandInput(Input):
    """A ring or stop command and its signature."""

    body: FindCommandBody
    signature: str = Field(max_length=88)


class FindReportInput(Input):
    """A phone's status report for a command: received, ringing, stopped, failed and so on."""

    command_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: Literal["received", "ringing", "stopped", "failed", "blocked", "expired"]
    reason: Literal[
        "",
        "audio_error",
        "audio_focus",
        "dnd",
        "dnd_unknown",
        "disabled",
        "timeout",
        "user_stopped",
        "remote_stop",
        "service_stopped",
    ] = ""
