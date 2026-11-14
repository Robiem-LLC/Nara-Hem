"""Invitation-authorized phone enrollment for fresh household installations.

Email verification delegates signed membership changes to a service identity
that the first approved administrator browser explicitly signs into the roster.
The service has no X25519 private key and cannot decrypt private GPS records.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException, Request
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem import review_mode
from narahem.app import digest, secret_file
from narahem.data_service import audit, canonical, identity
from narahem.models import (
    Account,
    ClientDevice,
    NativeRefreshSession,
    PhoneChallenge,
    PushDelivery,
    PushSubscription,
    RosterRevision,
    ServiceState,
)
from narahem.schemas import Input

SERVICE_ID = "0" * 32
CODE_LIFETIME_SECONDS = 600
PENDING_MAX_AGE_SECONDS = 3600
_last_cleanup = 0.0


def platform(device):
    """Returns "ios", "android" or "web" from the device's signed registration."""
    try:
        return json.loads(device.registration).get("platform", "legacy")
    except (ValueError, TypeError):
        return "legacy"


def mobile_slot(db, account_id, exclude=None):
    """Returns the account's approved phone, if any. Each member may have one phone."""
    return next(
        (
            device
            for device in db.scalars(
                select(ClientDevice).where(
                    ClientDevice.account_id == account_id, ClientDevice.status == "approved"
                )
            )
            if device.id != exclude and platform(device) in ("ios", "android", "legacy")
        ),
        None,
    )


def cleanup(engine):
    """Deletes expired phone codes and abandoned phone registrations, at most once a minute."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 240:
        return
    _last_cleanup = now
    with Session(engine) as db:
        stale = list(
            db.scalars(
                select(ClientDevice).where(
                    ClientDevice.status == "pending",
                    ClientDevice.created < now - PENDING_MAX_AGE_SECONDS,
                )
            )
        )
        for device in stale:
            if platform(device) not in ("ios", "android"):
                continue
            db.query(PhoneChallenge).filter_by(device_id=device.id).delete()
            db.delete(device)
        for challenge in list(
            db.scalars(select(PhoneChallenge).where(PhoneChallenge.expires < now))
        ):
            device = db.get(ClientDevice, challenge.device_id)
            if device and device.status == "pending":
                db.delete(device)
            db.delete(challenge)
        db.commit()


def install(
    app,
    directory,
    cipher,
    database,
    current,
    admin,
    rate,
    notify,
    send_now,
    settings_provider,
):
    """Registers the phone enrollment routes: emailed codes, the enrollment signer and phone
    revocation.
    """
    seed = bytes.fromhex(
        secret_file(directory / "enrollment-signing-seed", lambda: secrets.token_hex(32))
    )
    signer = SigningKey(seed)
    # Alexa signs its rings with this key too (alexa_api.py).
    app.state.enrollment_signer = signer
    pub = base64.b64encode(bytes(signer.verify_key)).decode()
    pepper = bytes.fromhex(
        secret_file(directory / "phone-code-pepper", lambda: secrets.token_hex(32))
    )

    def otp_digest(device, code):
        """Returns an HMAC of the code bound to this device's registration, so a code can't be
        used for another device.
        """
        commitment = hashlib.sha256(device.registration.encode()).hexdigest()
        message = f"{device.account_id}:{device.id}:{commitment}:{code}".encode()
        return hmac.new(pepper, message, hashlib.sha256).hexdigest()

    def forget_pending(db, device):
        """Deletes a pending phone and its code."""
        db.query(PhoneChallenge).filter_by(device_id=device.id).delete()
        if device.status == "pending":
            db.delete(device)

    def active_service(db, state):
        """Returns the latest roster revision after checking that the enrollment signer is in it
        and still valid.
        """
        record = db.get(ClientDevice, SERVICE_ID)
        if not record or record.status != "approved" or record.signing_key != pub:
            raise HTTPException(
                409, "An approved admin browser must activate email enrollment first"
            )
        last = db.get(RosterRevision, state.revision)
        if not last or not any(
            d["id"] == SERVICE_ID and d["signing_key"] == pub
            for d in json.loads(last.payload)["devices"]
        ):
            raise HTTPException(409, "Enrollment signer is not in the signed roster")
        return last

    def change_roster(db, state, *, add=None, revoke=None, actor):
        """Signs a new roster revision with the enrollment signer to add or revoke a phone."""
        previous = active_service(db, state)
        roster = json.loads(previous.payload)["devices"]
        if add and any(d["id"] == add.id for d in roster):
            raise HTTPException(409, "Phone is already registered in the signed roster")
        # Drop devices revoked in the database from the new revision, so clients stop encrypting for
        # them. Restoring an account never revives old phone keys, and the signed history stays
        # intact.
        records = []
        for entry in roster:
            if entry["id"] == revoke:
                continue
            registered = db.get(ClientDevice, entry["id"])
            owner = db.get(Account, registered.account_id) if registered else None
            if registered and registered.status != "revoked" and owner and owner.status == "active":
                records.append(entry)
        if add:
            records.append(identity(add))
        records.sort(key=lambda d: d["id"])
        if not any(d["id"] == SERVICE_ID for d in records):
            raise HTTPException(409, "Cannot remove the enrollment signer")
        body = {
            "domain": "narahem.roster.v1",
            "household": state.household_id,
            "revision": state.revision + 1,
            "previous": previous.hash,
            "signer": SERVICE_ID,
            "devices": records,
            "issued_at": int(time.time()),
        }
        if add:
            body["pairing_target"] = add.id
            body["pairing_hash"] = hashlib.sha256(add.registration.encode()).hexdigest()
        signature = base64.b64encode(signer.sign(canonical(body)).signature).decode()
        snapshot = {"body": body, "signature": signature}
        next_hash = hashlib.sha256(canonical(snapshot)).hexdigest()
        db.add(
            RosterRevision(
                revision=state.revision + 1,
                payload=canonical(body).decode(),
                signature=signature,
                hash=next_hash,
            )
        )
        state.revision += 1
        if add:
            add.status = "approved"
        if revoke:
            target = db.get(ClientDevice, revoke)
            if target:
                target.status = "revoked"
            db.query(PushSubscription).filter_by(device_id=revoke).delete()
            db.query(PushDelivery).filter_by(device_id=revoke).delete()
        audit(
            db,
            "enrollment.roster",
            actor,
            add.id if add else revoke,
            revision=state.revision,
            added=bool(add),
            revoked=bool(revoke),
        )
        return state.revision

    @app.post("/api/enrollment/signer")
    def signer_identity(auth=Depends(admin), db: Session = Depends(database)):
        """Returns the enrollment signer's public identity, which the admin's browser adds to the
        roster once.
        """
        state = db.get(ServiceState, 1)
        if not state.anchor or not state.revision:
            raise HTTPException(409, "First administrator browser is not yet trusted")
        existing = db.get(ClientDevice, SERVICE_ID)
        if existing and existing.signing_key != pub:
            raise HTTPException(
                409, "Enrollment signer key mismatch; do not regenerate this server data key"
            )
        if not existing:
            # Deliberately discard the private key: service gets signing authority
            # but never a recipient decryption key for household locations.
            box = base64.b64encode(bytes(PrivateKey.generate().public_key)).decode()
            registration = {
                "domain": "narahem.device.v1",
                "household": state.household_id,
                "id": SERVICE_ID,
                "account_id": auth[0].id,
                "signing_key": pub,
                "box_key": box,
                "platform": "server",
            }
            registration_signature = base64.b64encode(
                signer.sign(canonical(registration)).signature
            ).decode()
            existing = ClientDevice(
                id=SERVICE_ID,
                account_id=auth[0].id,
                name="Enrollment service",
                signing_key=pub,
                box_key=box,
                credential=digest(secrets.token_urlsafe(32)),
                registration=canonical(registration).decode(),
                registration_signature=registration_signature,
                status="pending",
                created=time.time(),
            )
            db.add(existing)
            db.commit()
        return {
            **identity(existing),
            "status": existing.status,
            "registration": json.loads(existing.registration),
            "registration_signature": existing.registration_signature,
        }

    class PhoneRequest(Input):
        """Identifies a pending phone."""

        device_id: str = Field(pattern=r"^[a-f0-9]{32}$")

    class PhoneVerify(PhoneRequest):
        """A pending phone and the emailed code."""

        code: str = Field(pattern=r"^[0-9]{6}$")

    @app.post("/api/phones/code", status_code=202)
    def send_code(
        body: PhoneRequest, request: Request, auth=Depends(current), db: Session = Depends(database)
    ):
        """Sends a six-digit approval code for a new phone, by email and text where the account
        has them.
        """
        rate(request, "phone-code:" + auth[0].id, 3, shared=True)
        rate(request, "phone-code-global", 45, shared=True)
        device = db.get(ClientDevice, body.device_id)
        if (
            not auth[0].verified
            or not device
            or device.account_id != auth[0].id
            or device.status != "pending"
            or platform(device) not in ("ios", "android")
        ):
            raise HTTPException(403, "No eligible pending phone")
        if mobile_slot(db, auth[0].id):
            forget_pending(db, device)
            db.commit()
            raise HTTPException(
                409, "Another phone is registered. Ask the administrator to revoke it"
            )
        active_service(db, db.get(ServiceState, 1))
        # A demo server for App Store review gives its listed accounts a fixed code instead.
        code = review_mode.fixed_code(auth[0])
        if not code:
            code = f"{secrets.randbelow(1000000):06d}"
            send_now(
                db,
                auth[0],
                "Nära Hem: confirm your phone",
                f"Enter {code} in the Nära Hem app to register this phone.\n"
                "It expires in 10 minutes. If you didn't request this, "
                "change your password and contact your administrator.",
                f"Nära Hem code: {code}. Enter it in the app to register this phone. "
                "It expires in 10 minutes.",
            )
        challenge = db.get(PhoneChallenge, device.id)
        if not challenge:
            challenge = PhoneChallenge(
                device_id=device.id,
                account_id=device.account_id,
                proof="",
                created=time.time(),
                expires=0,
                attempts=0,
            )
            db.add(challenge)
        challenge.proof = otp_digest(device, code)
        challenge.expires, challenge.created, challenge.attempts = time.time() + 600, time.time(), 0
        db.commit()
        return {"sent": True, "expires_in": CODE_LIFETIME_SECONDS}

    @app.post("/api/phones/verify")
    def verify_code(body: PhoneVerify, auth=Depends(current), db: Session = Depends(database)):
        """Checks the code and, if correct, adds the phone to the signed roster."""
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        device = db.get(ClientDevice, body.device_id)
        if not auth[0].verified or not device or device.account_id != auth[0].id:
            raise HTTPException(403, "Pending phone not found")
        if device.status != "pending" or platform(device) not in ("ios", "android"):
            raise HTTPException(409, "Phone is not awaiting verification")
        challenge = db.get(PhoneChallenge, device.id)
        if mobile_slot(db, auth[0].id):
            forget_pending(db, device)
            db.commit()
            raise HTTPException(409, "Another phone is already registered")
        if not challenge or challenge.expires <= time.time() or challenge.attempts >= 5:
            forget_pending(db, device)
            db.commit()
            raise HTTPException(403, "Verification expired or exhausted; start again")
        challenge.attempts += 1
        if not hmac.compare_digest(otp_digest(device, body.code), challenge.proof):
            remaining = 5 - challenge.attempts
            if remaining <= 0:
                forget_pending(db, device)
            db.commit()
            raise HTTPException(
                403,
                (
                    "Code rejected. Registration discarded."
                    if remaining <= 0
                    else "Code rejected. Try again."
                ),
            )
        change_roster(db, state, add=device, actor=auth[0].id)
        db.delete(challenge)
        # The account now has its phone, so its other pending phone registrations can never
        # complete; delete them.
        for abandoned in list(
            db.scalars(
                select(ClientDevice).where(
                    ClientDevice.account_id == auth[0].id,
                    ClientDevice.status == "pending",
                    ClientDevice.id != device.id,
                )
            )
        ):
            if platform(abandoned) in ("ios", "android"):
                forget_pending(db, abandoned)
        db.commit()
        return {"approved": True, "revision": state.revision}

    @app.delete("/api/phones/pending")
    def cancel_pending(body: PhoneRequest, auth=Depends(current), db: Session = Depends(database)):
        """Cancels an unfinished phone registration."""
        device = db.get(ClientDevice, body.device_id)
        if not device or device.account_id != auth[0].id or device.status != "pending":
            raise HTTPException(404, "Pending phone not found")
        forget_pending(db, device)
        db.commit()
        return {"discarded": True}

    def queue_revocation_email(db, account, admin_action):
        """Queues an email and text telling the member a phone was revoked."""
        message = (
            ("Your administrator" if admin_action else "You")
            + " revoked a phone from your Nära Hem account. "
            "It no longer receives new household updates. "
            "To use a replacement, sign in and verify the code you're sent."
        )
        if not notify(db, account, "p:" + account.id, "Nära Hem: phone revoked", message, message):
            audit(db, "phone.revoke.email_unavailable", account.id)
            return False
        return True

    def revoke_phone(db, device, actor):
        """Permanently revokes a phone and removes it from the signed roster."""
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        db.refresh(device)
        if device.status != "approved" or platform(device) not in ("ios", "android"):
            raise HTTPException(409, "Registered phone required")
        change_roster(db, state, revoke=device.id, actor=actor)
        db.query(NativeRefreshSession).filter_by(account_id=device.account_id).delete()

    @app.post("/api/phones/self-revoke")
    def self_revoke(request: Request, db: Session = Depends(database)):
        """Revokes the requesting phone, authenticated by its device token."""
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 200:
            raise HTTPException(401, "Registered phone credential required")
        device = db.scalar(
            select(ClientDevice).where(
                ClientDevice.credential == digest(header[7:]), ClientDevice.status == "approved"
            )
        )
        if not device or platform(device) not in ("ios", "android"):
            raise HTTPException(403, "Approved phone credential required")
        revoke_phone(db, device, device.account_id)
        queued = queue_revocation_email(db, db.get(Account, device.account_id), False)
        db.commit()
        return {"revoked": True, "notification_queued": queued}

    @app.post("/api/phones/{device_id}/revoke")
    def admin_revoke(device_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Revokes a member's phone at the admin's request."""
        device = db.get(ClientDevice, device_id)
        if not device or platform(device) not in ("ios", "android"):
            raise HTTPException(404, "Registered phone not found")
        account = db.get(Account, device.account_id)
        if not account or account.role == "admin":
            raise HTTPException(403, "Only a member phone may be revoked here")
        revoke_phone(db, device, auth[0].id)
        queued = queue_revocation_email(db, account, True)
        db.commit()
        return {"revoked": True, "notification_queued": queued}
