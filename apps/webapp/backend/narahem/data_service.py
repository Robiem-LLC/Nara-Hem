"""Authenticated opaque data relay. Private client keys never enter this module."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from sqlalchemy import (
    or_,
    select,
)
from sqlalchemy.orm import Session

from narahem.app import digest, secret_file
from narahem.models import (
    AlertMemory,
    AuditEntry,
    ClientDevice,
    DevicePermissionSnapshot,
    DiagnosticEntry,
    EncryptedRecord,
    FindPhoneCapability,
    FindPhoneCommand,
    IndexedTrip,
    LoginSession,
    PushDelivery,
    PushSubscription,
    RecordRecipient,
    RosterRevision,
    ServerAlert,
    ServiceState,
)

DAY = 86400


def canonical(value):
    """Serializes a value as JSON with sorted keys and no whitespace, matching what the apps
    sign.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def decode(value, length=None, minimum=None, maximum=None):
    """Decodes base64 and checks its length, raising a 422 if invalid."""
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise HTTPException(422, "Invalid base64 encoding") from error
    if (
        base64.b64encode(result).decode() != value
        or (length is not None and len(result) != length)
        or (minimum is not None and len(result) < minimum)
        or (maximum is not None and len(result) > maximum)
    ):
        raise HTTPException(422, "Invalid encoded payload length")
    return result


def verify_signature(key, body, signature):
    """Verifies an Ed25519 signature over the canonical JSON of body, raising a 422 if invalid."""
    try:
        VerifyKey(decode(key, 32)).verify(canonical(body), decode(signature, 64))
    except BadSignatureError as error:
        raise HTTPException(403, "Signature rejected") from error


def code_hash(directory, text):
    """Returns an HMAC of a short code and what it's for, keyed with a secret pepper kept beside
    the server key, so a database leak doesn't allow brute-forcing six-digit codes.
    """
    pepper = secret_file(directory / "device-email-pepper", lambda: secrets.token_hex(32))
    return hmac.new(bytes.fromhex(pepper), text.encode(), hashlib.sha256).hexdigest()


def bootstrap_email_hash(directory, device_id, code):
    """Returns the stored form of a first-device email code."""
    return code_hash(directory, f"{device_id}:{code}")


def diagnostic(db, category, action, account=None, device=None, outcome="ok", **details):
    """Adds a diagnostics log entry and prunes entries older than 14 days or beyond the row
    limit.
    """
    now = time.time()
    db.query(DiagnosticEntry).filter(DiagnosticEntry.created < now - 14 * DAY).delete(
        synchronize_session=False
    )
    overflow = list(
        db.scalars(
            select(DiagnosticEntry.id)
            .order_by(DiagnosticEntry.created.desc(), DiagnosticEntry.id.desc())
            .offset(19999)
        )
    )
    if overflow:
        db.query(DiagnosticEntry).filter(DiagnosticEntry.id.in_(overflow)).delete(
            synchronize_session=False
        )
    db.add(
        DiagnosticEntry(
            id=secrets.token_hex(16),
            category=category,
            action=action,
            account_id=account,
            device_id=device,
            outcome=outcome,
            created=now,
            details=canonical(details).decode(),
        )
    )


def identity(device):
    """Returns a device's public roster entry."""
    return {
        "id": device.id,
        "account_id": device.account_id,
        "signing_key": device.signing_key,
        "box_key": device.box_key,
    }


def audit(db, action, actor, target=None, **details):
    """Adds an audit log entry."""
    ident = secrets.token_hex(16)
    db.add(
        AuditEntry(id=ident, action=action, actor_id=actor, target_id=target, created=time.time())
    )
    diagnostic(
        db,
        "administration",
        action,
        actor,
        target,
        audit_id=ident,
        target_id=target,
        source="server audit",
        **details,
    )


def initialize_service(engine, directory, cipher):
    """Creates the household identity on the first run."""
    with Session(engine) as db:
        state = db.get(ServiceState, 1)
        if state is None:
            token = secret_file(
                directory / "device-bootstrap-token", lambda: secrets.token_urlsafe(32)
            )
            db.add(
                ServiceState(
                    id=1,
                    household_id=secrets.token_hex(16),
                    bootstrap_hash=digest(token),
                    key_check=cipher.encrypt(b"narahem.storage.v1").decode(),
                )
            )
            db.commit()
        elif cipher.decrypt(state.key_check.encode()) != b"narahem.storage.v1":
            raise RuntimeError("Server storage key check failed")
        elif state.anchor:
            (directory / "device-bootstrap-token").unlink(missing_ok=True)
        elif not (directory / "device-bootstrap-token").exists():
            raise RuntimeError("Device bootstrap token missing; restore matching server data")


def prune(db):
    """Deletes records past the retention period and expired codes, sessions and deliveries."""
    now = time.time()
    state = db.execute(
        select(ServiceState).where(ServiceState.id == 1).with_for_update()
    ).scalar_one()
    cutoff = int((now - state.retention_days * DAY) * 1000)
    db.query(EncryptedRecord).filter(
        EncryptedRecord.kind.in_(["location", "event"]),
        or_(EncryptedRecord.captured_at <= cutoff, EncryptedRecord.expires_at <= now),
    ).delete(synchronize_session=False)
    db.query(IndexedTrip).filter(~IndexedTrip.event_id.in_(select(EncryptedRecord.id))).delete(
        synchronize_session=False
    )
    db.query(PushDelivery).filter(PushDelivery.expires_at <= now).delete(synchronize_session=False)
    db.query(ServerAlert).filter(ServerAlert.created <= now - DAY).delete(synchronize_session=False)
    db.query(AuditEntry).filter(AuditEntry.created <= now - 14 * DAY).delete(
        synchronize_session=False
    )
    db.query(DiagnosticEntry).filter(DiagnosticEntry.created <= now - 14 * DAY).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.expires <= now).delete(synchronize_session=False)
    db.query(FindPhoneCommand).filter(FindPhoneCommand.created < now - 14 * DAY).delete(
        synchronize_session=False
    )
    state.last_cleanup = now
    db.commit()


def revoke_account_data(db, account_id, actor_id):
    """Revokes all of an account's devices and deletes their push subscriptions and sessions."""
    ids = list(db.scalars(select(ClientDevice.id).where(ClientDevice.account_id == account_id)))
    db.query(ClientDevice).filter_by(account_id=account_id).update({ClientDevice.status: "revoked"})
    if ids:
        db.query(DevicePermissionSnapshot).filter(
            DevicePermissionSnapshot.device_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(FindPhoneCapability).filter(FindPhoneCapability.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(FindPhoneCommand).filter(
            or_(FindPhoneCommand.target_id.in_(ids), FindPhoneCommand.issuer_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(PushSubscription).filter(PushSubscription.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(PushDelivery).filter(PushDelivery.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(AlertMemory).filter(AlertMemory.device_id.in_(ids)).delete(
            synchronize_session=False
        )
    audit(db, "account.revoked", actor_id, account_id)


def purge_account_data(db, account_id, actor_id):
    """Deletes an account and its data. The caller must hold the household lock so access removal
    and deletion commit together.
    """
    ids = list(db.scalars(select(ClientDevice.id).where(ClientDevice.account_id == account_id)))
    records = select(EncryptedRecord.id).where(
        EncryptedRecord.account_id == account_id, EncryptedRecord.kind != "place"
    )
    db.query(PushDelivery).filter(PushDelivery.record_id.in_(records)).delete(
        synchronize_session=False
    )
    alerts = select(ServerAlert.id).where(ServerAlert.account_id == account_id)
    db.query(PushDelivery).filter(PushDelivery.record_id.in_(alerts)).delete(
        synchronize_session=False
    )
    db.query(ServerAlert).filter(ServerAlert.account_id == account_id).delete(
        synchronize_session=False
    )
    if ids:
        db.query(DevicePermissionSnapshot).filter(
            DevicePermissionSnapshot.device_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(FindPhoneCapability).filter(FindPhoneCapability.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(FindPhoneCommand).filter(
            or_(FindPhoneCommand.target_id.in_(ids), FindPhoneCommand.issuer_id.in_(ids))
        ).delete(synchronize_session=False)
        db.query(PushSubscription).filter(PushSubscription.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(PushDelivery).filter(PushDelivery.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(RecordRecipient).filter(RecordRecipient.device_id.in_(ids)).delete(
            synchronize_session=False
        )
        db.query(AlertMemory).filter(AlertMemory.device_id.in_(ids)).delete(
            synchronize_session=False
        )
    count = (
        db.query(EncryptedRecord)
        .filter(EncryptedRecord.account_id == account_id, EncryptedRecord.kind != "place")
        .delete(synchronize_session=False)
    )
    db.query(ClientDevice).filter_by(account_id=account_id).delete(synchronize_session=False)
    db.query(AuditEntry).filter(
        or_(AuditEntry.actor_id == account_id, AuditEntry.target_id.in_([account_id, *ids]))
    ).delete(synchronize_session=False)
    state = db.get(ServiceState, 1)
    current = db.get(RosterRevision, state.revision)
    reconcile = bool(
        current
        and any(d["account_id"] == account_id for d in json.loads(current.payload)["devices"])
    )
    # The audit entry doesn't name the deleted account. Old roster signatures keep the IDs and
    # public keys needed to verify remaining records.
    db.query(DiagnosticEntry).filter(DiagnosticEntry.account_id == account_id).delete(
        synchronize_session=False
    )
    audit(db, "account.deleted", actor_id)
    return {"records_deleted": count, "membership_reconciliation_required": reconcile}
