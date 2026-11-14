"""Encrypted records, their recipients, retention, and location sharing choices."""

from typing import Literal

from pydantic import Field

from .base import MAX_DEVICES, CryptoInput, Input


class Recipient(Input):
    """A record encrypted for one device."""

    device_id: str = Field(pattern="^[a-f0-9]{32}$")
    box: str = Field(min_length=64, max_length=100000)


class RecordBody(CryptoInput):
    """The signed part of a record: kind, entity, recipients and encrypted copies."""

    domain: Literal["narahem.record.v1"]
    household: str = Field(pattern="^[a-f0-9]{32}$")
    revision: int = Field(ge=1)
    id: str = Field(pattern="^[a-f0-9]{32}$")
    sender: str = Field(pattern="^[a-f0-9]{32}$")
    sequence: int = Field(ge=1, le=9007199254740991)
    kind: str = Field(pattern="^(location|event|place|profile)$")
    entity_id: str = Field(pattern="^[a-f0-9]{32}$")
    operation: str = Field(pattern="^(upsert|delete)$")
    replaces: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    captured_at: int = Field(ge=0, le=9007199254740991)
    recipients: list[Recipient] = Field(min_length=1, max_length=MAX_DEVICES)
    # The record sealed for the server. Required for locations, trips, places and profiles; older
    # records may lack it.
    server_box: str | None = Field(default=None, min_length=64, max_length=24576)


class RecordInput(Input):
    """A record and its signature."""

    body: RecordBody
    signature: str = Field(max_length=88)


class SharingInput(Input):
    """Enables or disables location sharing."""

    enabled: bool


class AudienceInput(Input):
    """Account IDs allowed to see this device's location."""

    account_ids: list[str] = Field(max_length=32)


class RetentionInput(Input):
    """Number of days of history to keep."""

    days: int = Field(ge=1, le=14)
