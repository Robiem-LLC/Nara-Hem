"""Household summary, device registration and the device list."""

import json
import secrets
import time

from fastapi import Depends, HTTPException, Request
from nacl.bindings import crypto_scalarmult
from nacl.exceptions import CryptoError
from sqlalchemy import (
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from narahem.app import account_trusted, digest
from narahem.data_service import audit, canonical, decode, identity, verify_signature
from narahem.mobile_enrollment import mobile_slot
from narahem.models import (
    Account,
    ClientDevice,
    DevicePermissionSnapshot,
    DeviceSharingAudience,
    EncryptedRecord,
    RosterRevision,
    ServiceState,
)
from narahem.schemas import (
    RegisterInput,
)


def install(app, *, credential, current, database, own_credential, rate, trip_processor, verified):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.get("/api/household")
    def household(auth=Depends(current), db: Session = Depends(database)):
        """Returns the household ID, name and current roster revision."""
        s = db.get(ServiceState, 1)
        return {
            "id": s.household_id,
            "revision": s.revision,
            "anchor": s.anchor,
            "retention_days": s.retention_days,
            "transport": "https",
            "protocol": "sealed-box-ed25519-v1",
        }

    @app.post("/api/devices/register", status_code=201)
    def register(
        body: RegisterInput,
        request: Request,
        auth=Depends(current),
        db: Session = Depends(database),
    ):
        """Registers a new device's public keys. Phones must then confirm an emailed code;
        nothing is approved here. A phone may register for an account not yet confirmed, since
        that code is what confirms it; a browser needs a confirmed account.
        """
        if body.platform not in ("ios", "android"):
            verified(auth, db)
        rate(request, "register", 10)
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        if body.id == "0" * 32:
            raise HTTPException(422, "Reserved device identity")
        if (
            db.query(ClientDevice)
            .filter_by(account_id=auth[0].id)
            .filter(ClientDevice.status != "revoked")
            .count()
            >= 8
            or db.query(ClientDevice).filter(ClientDevice.status != "revoked").count() >= 64
        ):
            raise HTTPException(409, "Device limit reached; remove an unused device")
        retired = db.scalar(
            select(RosterRevision.revision)
            .where(
                or_(
                    RosterRevision.payload.contains(f'"id":"{body.id}"'),
                    RosterRevision.payload.contains(f'"signing_key":"{body.signing_key}"'),
                    RosterRevision.payload.contains(f'"box_key":"{body.box_key}"'),
                )
            )
            .limit(1)
        )
        if retired is not None:
            raise HTTPException(409, "Device identity already used; create a new device identity")
        if db.get(ClientDevice, body.id) or db.scalar(
            select(ClientDevice).where(
                (ClientDevice.signing_key == body.signing_key)
                | (ClientDevice.box_key == body.box_key)
            )
        ):
            raise HTTPException(409, "Device identity already registered")
        try:
            crypto_scalarmult(secrets.token_bytes(32), decode(body.box_key, 32))
        except CryptoError as error:
            raise HTTPException(422, "Invalid X25519 public key") from error
        registration = {
            "domain": "narahem.device.v1",
            "household": state.household_id,
            "id": body.id,
            "account_id": auth[0].id,
            "signing_key": body.signing_key,
            "box_key": body.box_key,
        }
        if body.platform:
            registration["platform"] = body.platform
        verify_signature(body.signing_key, registration, body.signature)
        token = secrets.token_urlsafe(32)
        db.add(
            ClientDevice(
                id=body.id,
                account_id=auth[0].id,
                name=body.name.strip(),
                signing_key=body.signing_key,
                box_key=body.box_key,
                credential=digest(token),
                registration=canonical(registration).decode(),
                registration_signature=body.signature,
                created=time.time(),
            )
        )
        audit(db, "device.registered", auth[0].id, body.id)
        db.commit()
        return {"id": body.id, "credential": token, "status": "pending"}

    @app.get("/api/devices")
    def devices(auth=Depends(current), db: Session = Depends(database)):
        """Returns the device list. Members see approved devices only; activity times are only
        shown to the owner, the admin and the device's audience.
        """
        query = select(ClientDevice).order_by(ClientDevice.created)
        if not account_trusted(auth[0], db):
            query = query.where(ClientDevice.account_id == auth[0].id)
        # Members only see approved devices. Pending phone registrations are email-code challenges,
        # not approval requests, so they are never listed, even to the admin.
        if auth[0].role != "admin":
            query = query.where(ClientDevice.status != "pending")
        devices = [
            d
            for d in db.scalars(query).all()
            if not (
                d.status == "pending"
                and json.loads(d.registration).get("platform") in ("ios", "android")
            )
        ]
        owners = {
            a.id: a
            for a in db.scalars(
                select(Account).where(Account.id.in_([d.account_id for d in devices]))
            )
        }
        permissions = {
            p.device_id: p
            for p in db.scalars(
                select(DevicePermissionSnapshot).where(
                    DevicePermissionSnapshot.device_id.in_([d.id for d in devices])
                )
            )
        }
        audiences = {
            row.device_id: set(json.loads(row.account_ids))
            for row in db.scalars(
                select(DeviceSharingAudience).where(
                    DeviceSharingAudience.device_id.in_([d.id for d in devices])
                )
            )
        }

        def activity_visible(d):
            """Returns True if the viewer may see when device d was last active."""
            if auth[0].role == "admin" or d.account_id == auth[0].id:
                return True
            return d.id not in audiences or auth[0].id in audiences[d.id]

        last_location = {
            device_id: received
            for device_id, received in db.execute(
                select(EncryptedRecord.device_id, func.max(EncryptedRecord.received_at))
                .where(
                    EncryptedRecord.kind == "location",
                    EncryptedRecord.device_id.in_([d.id for d in devices]),
                )
                .group_by(EncryptedRecord.device_id)
            )
        }
        return {
            "pairing_available": auth[0].role == "admin",
            "devices": [
                {
                    **identity(d),
                    "name": (
                        "Admin"
                        if d.name == "My browser"
                        and d.account_id in owners
                        and owners[d.account_id].role == "admin"
                        else d.name
                    ),
                    "status": d.status,
                    "sharing": d.sharing,
                    "created": d.created,
                    "activity_visible": activity_visible(d),
                    **(
                        {
                            "sequence": d.last_sequence,
                            "seen": d.seen,
                            "last_location": last_location.get(d.id),
                        }
                        if activity_visible(d)
                        else {"sequence": None, "seen": None, "last_location": None}
                    ),
                    "platform": json.loads(d.registration).get("platform", "legacy"),
                    "permissions": (
                        {
                            "foreground_location": permissions[d.id].foreground_location,
                            "background_location": permissions[d.id].background_location,
                            "remote_alarm": permissions[d.id].remote_alarm,
                            "dnd_access": permissions[d.id].dnd_access,
                            "notifications": permissions[d.id].notifications,
                            "sharing": permissions[d.id].sharing,
                            "reported_at": permissions[d.id].reported_at,
                        }
                        if d.id in permissions
                        and (auth[0].role == "admin" or d.account_id == auth[0].id)
                        else None
                    ),
                    "owner_name": (owners[d.account_id].username or "Member")
                    if d.account_id in owners
                    else "Former member",
                    "owner_email": (
                        (owners[d.account_id].email or owners[d.account_id].phone)
                        if d.account_id in owners
                        else None
                    )
                    if auth[0].role == "admin"
                    else None,
                    "registration": json.loads(d.registration),
                    "registration_signature": d.registration_signature,
                }
                for d in devices
            ],
        }

    @app.get("/api/device")
    def own_device(device=Depends(own_credential), db: Session = Depends(database)):
        """Returns the requesting device's status, including its phone enrollment state."""
        slot = mobile_slot(db, device.account_id, exclude=device.id)
        return {
            **identity(device),
            "name": device.name,
            "status": device.status,
            "replacement_required": (
                device.status == "pending"
                and json.loads(device.registration).get("platform") in ("ios", "android")
                and bool(slot)
            ),
            "sharing": device.sharing,
            "sequence": device.last_sequence,
            "trip_processing_key": trip_processor.public_key,
        }
