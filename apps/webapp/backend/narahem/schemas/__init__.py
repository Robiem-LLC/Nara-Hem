"""Request bodies the API accepts, validated by Pydantic."""

from .accounts import (
    ChangePasswordInput,
    ChangeUsernameInput,
    ClaimInput,
    EmailInput,
    InvitationInput,
    InvitationRequestInput,
    LoginInput,
    NativeRefreshInput,
    ResetPasswordInput,
    SetupInput,
    VerifyInput,
)
from .base import MAX_DEVICES, CryptoInput, Input
from .devices import (
    DevicePermissionInput,
    Identity,
    RegisterInput,
    RosterBody,
    RosterInput,
    SubscribeInput,
)
from .find_phone import FindCapabilityInput, FindCommandBody, FindCommandInput, FindReportInput
from .records import AudienceInput, Recipient, RecordBody, RecordInput, RetentionInput, SharingInput
from .settings import APNsConfig, MailInput, PushConfig, PushTestInput

__all__ = [
    "MAX_DEVICES",
    "Input",
    "CryptoInput",
    "SetupInput",
    "LoginInput",
    "ChangePasswordInput",
    "ResetPasswordInput",
    "NativeRefreshInput",
    "EmailInput",
    "InvitationInput",
    "InvitationRequestInput",
    "ClaimInput",
    "VerifyInput",
    "ChangeUsernameInput",
    "MailInput",
    "APNsConfig",
    "PushConfig",
    "PushTestInput",
    "DevicePermissionInput",
    "RegisterInput",
    "Identity",
    "RosterBody",
    "RosterInput",
    "SubscribeInput",
    "FindCapabilityInput",
    "FindCommandBody",
    "FindCommandInput",
    "FindReportInput",
    "Recipient",
    "RecordBody",
    "RecordInput",
    "SharingInput",
    "AudienceInput",
    "RetentionInput",
]
