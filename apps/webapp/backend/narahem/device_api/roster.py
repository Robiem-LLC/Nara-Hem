"""The signed household roster (membership chain)."""

import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem.app import account_trusted, digest
from narahem.data_service import (
    audit,
    bootstrap_email_hash,
    canonical,
    identity,
    verify_signature,
)
from narahem.models import (
    Account,
    ClientDevice,
    DeviceBootstrapChallenge,
    PushDelivery,
    PushSubscription,
    RosterRevision,
    ServiceState,
)
from narahem.schemas import (
    RosterInput,
)


def install(app, *, active_devices, credential, database, directory):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.get("/api/roster")
    def roster(after: int = 0, device=Depends(credential), db: Session = Depends(database)):
        """Returns a page of signed roster revisions after the given one. Clients verify each
        revision.
        """
        if after < 0:
            raise HTTPException(422, "Invalid revision")
        state = db.get(ServiceState, 1)
        rows = list(
            db.scalars(
                select(RosterRevision)
                .where(RosterRevision.revision > after)
                .order_by(RosterRevision.revision)
                .limit(100)
            )
        )
        return {
            "household": state.household_id,
            "revision": state.revision,
            "anchor": state.anchor,
            "changes": [
                {"body": json.loads(r.payload), "signature": r.signature, "hash": r.hash}
                for r in rows
            ],
        }

    @app.post("/api/roster")
    def change_roster(
        body: RosterInput, device=Depends(credential), db: Session = Depends(database)
    ):
        """Accepts a new signed roster revision from a trusted device after checking its
        continuity and the signer's permissions.
        """
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        actual = []
        db.refresh(device)
        # Leave out unset pairing fields so older signed rosters still verify.
        value = body.body.model_dump(exclude_unset=True)
        if (
            value["household"] != state.household_id
            or value["signer"] != device.id
            or value["revision"] != state.revision + 1
            or abs(value["issued_at"] - int(time.time())) > 300
        ):
            raise HTTPException(409, "Roster revision or identity mismatch")
        previous = db.get(RosterRevision, state.revision)
        if value["previous"] != (previous.hash if previous else ""):
            raise HTTPException(409, "Roster chain mismatch")
        ids = [d["id"] for d in value["devices"]]
        if ids != sorted(set(ids)):
            raise HTTPException(422, "Roster identities must be sorted and unique")
        for ident in value["devices"]:
            d = db.get(ClientDevice, ident["id"])
            a = db.get(Account, d.account_id) if d else None
            if (
                not d
                or d.status == "revoked"
                or not a
                or a.status != "active"
                or not account_trusted(a, db)
                or identity(d) != ident
            ):
                raise HTTPException(403, "Device identity is ineligible")
            actual.append(d)
        # The pairing proof is part of the signed revision; the server only checks it and never
        # approves a device itself.
        target_id = value.get("pairing_target")
        target_hash = value.get("pairing_hash")
        if target_id is not None or target_hash is not None:
            if state.revision == 0 or target_id is None or target_hash is None:
                raise HTTPException(422, "Pairing requires a complete existing trusted roster")
            prior_ids = {item["id"] for item in json.loads(previous.payload)["devices"]}
            new_ids = set(ids) - prior_ids
            target = db.get(ClientDevice, target_id)
            if (
                new_ids != {target_id}
                or not target
                or target.status != "pending"
                or device.id == target_id
            ):
                raise HTTPException(422, "Pairing must approve exactly one pending device")
            if not hmac.compare_digest(
                target_hash, hashlib.sha256(target.registration.encode()).hexdigest()
            ):
                raise HTTPException(422, "Pairing registration commitment does not match")
        # Only the enrollment signer may add phones. Trusted browsers may add browsers and the
        # one-time enrollment signer.
        if state.revision > 0:
            known = {entry["id"] for entry in json.loads(previous.payload)["devices"]}
            incoming = set(ids) - known
            for new_id in incoming:
                fresh = db.get(ClientDevice, new_id)
                if fresh and json.loads(fresh.registration).get("platform") in ("ios", "android"):
                    raise HTTPException(
                        403, "Phones must complete their own emailed verification code"
                    )
                if new_id == "0" * 32 and db.get(Account, device.account_id).role != "admin":
                    raise HTTPException(403, "Only an admin browser may enable enrollment")
        verify_signature(device.signing_key, value, body.signature)
        account = db.get(Account, device.account_id)
        if state.revision == 0:
            allowed = bool(
                body.bootstrap_token
                and hmac.compare_digest(digest(body.bootstrap_token), state.bootstrap_hash or "")
            )
            if not allowed and body.bootstrap_email_code and account.role == "admin":
                challenge = db.execute(
                    select(DeviceBootstrapChallenge)
                    .where(DeviceBootstrapChallenge.device_id == device.id)
                    .with_for_update()
                ).scalar_one_or_none()
                if (
                    challenge
                    and challenge.account_id == account.id
                    and challenge.expires > time.time()
                    and challenge.attempts < 5
                ):
                    challenge.attempts += 1
                    allowed = hmac.compare_digest(
                        challenge.code_hash,
                        bootstrap_email_hash(directory, device.id, body.bootstrap_email_code),
                    )
                    if not allowed:
                        db.commit()  # Persist failed attempts even on rejection.
            if account.role != "admin" or ids != [device.id] or not allowed:
                raise HTTPException(
                    403,
                    "First device requires the local bootstrap token or a valid emailed "
                    "administrator code",
                )
            db.query(DeviceBootstrapChallenge).delete()
            state.anchor, state.bootstrap_hash = device.signing_key, None
        else:
            if device.status != "approved":
                raise HTTPException(403, "An existing trusted device must approve membership")
            old = json.loads(previous.payload)["devices"]
            if account.role != "admin":
                # Any trusted device may add an invited, verified device. Only the admin may revoke
                # someone else's device.
                if any(d["account_id"] != device.account_id for d in old if d["id"] not in ids):
                    raise HTTPException(403, "Only an owner device can revoke other members")
        for d in active_devices(db):
            if d.id not in ids:
                d.status = "revoked"
                db.query(PushSubscription).filter_by(device_id=d.id).delete()
                db.query(PushDelivery).filter_by(device_id=d.id).delete()
        for d in actual:
            d.status = "approved"
        snapshot = {"body": value, "signature": body.signature}
        hash_value = hashlib.sha256(canonical(snapshot)).hexdigest()
        db.add(
            RosterRevision(
                revision=value["revision"],
                payload=canonical(value).decode(),
                signature=body.signature,
                hash=hash_value,
            )
        )
        state.revision = value["revision"]
        audit(
            db,
            "roster.changed",
            device.account_id,
            device.id,
            revision=state.revision,
            approved_devices=ids,
            previous_devices=[d["id"] for d in json.loads(previous.payload)["devices"]]
            if previous
            else [],
        )
        db.commit()
        (directory / "device-bootstrap-token").unlink(missing_ok=True)
        return {"revision": state.revision, "hash": hash_value}
