"""Find My Phone: device permissions, capability, signed commands and reports."""

import json
import secrets
import time

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem.data_service import DAY, audit, canonical, diagnostic, verify_signature
from narahem.models import (
    Account,
    ClientDevice,
    DevicePermissionSnapshot,
    FindPhoneCapability,
    FindPhoneCommand,
    PushSubscription,
    ServiceState,
)
from narahem.push_service import PushRelayFailure, available_config, deliver
from narahem.schemas import (
    DevicePermissionInput,
    FindCapabilityInput,
    FindCommandInput,
    FindReportInput,
)


def install(app, *, admin, approved, cipher, database, engine, notifier, rate):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install(). Returns store_command, which Alexa uses to ring a phone.
    """

    @app.put("/api/device/permissions")
    def report_device_permissions(
        body: DevicePermissionInput, device=Depends(approved), db: Session = Depends(database)
    ):
        """Stores the permission flags a phone reports about itself."""
        # A device can only report its own permissions.
        values = body.model_dump()
        snapshot = db.get(DevicePermissionSnapshot, device.id)
        if snapshot is None:
            snapshot = DevicePermissionSnapshot(
                device_id=device.id, **values, reported_at=time.time()
            )
            db.add(snapshot)
        else:
            for name, value in values.items():
                setattr(snapshot, name, value)
            snapshot.reported_at = time.time()
        db.commit()
        return {"recorded": True}

    @app.put("/api/find-phone/capability")
    def set_find_capability(
        body: FindCapabilityInput, device=Depends(approved), db: Session = Depends(database)
    ):
        """Stores whether Find My Phone is enabled on the requesting phone."""
        row = db.get(FindPhoneCapability, device.id)
        if row is None:
            row = FindPhoneCapability(
                device_id=device.id, enabled=body.enabled, platform=body.platform, seen=time.time()
            )
            db.add(row)
        else:
            row.enabled, row.platform, row.seen = body.enabled, body.platform, time.time()
        if not body.enabled:
            db.query(FindPhoneCommand).filter_by(target_id=device.id).filter(
                FindPhoneCommand.status.in_(["pending", "received"])
            ).update({FindPhoneCommand.status: "cancelled"}, synchronize_session=False)
        audit(
            db,
            "phone.find.enabled" if body.enabled else "phone.find.disabled",
            device.account_id,
            device.id,
        )
        db.commit()
        return {"enabled": row.enabled}

    def push_find_phone_nudge(provider, token, config, action, account_id, device_id):
        """Sends a push so the phone checks for the command immediately. Failures are logged
        without tokens or response bodies.
        """
        outcome = "failed"
        reason = "provider_error"
        safe_relay_details = {}
        try:
            if notifier:
                result = notifier(provider, token, "0" * 32, secrets.token_hex(16), config)
            else:
                result = deliver(
                    provider,
                    token,
                    "0" * 32,
                    secrets.token_hex(16),
                    config,
                    kind="find-phone" if action == "ring" or provider == "fcm" else "update",
                )
            if result == "sent":
                outcome, reason = "accepted", "provider_accepted_not_device_confirmed"
            elif result == "invalid":
                outcome, reason = "invalid", "push_registration_invalid"
            else:
                outcome, reason = "unknown", "provider_delivery_unconfirmed"
        except PushRelayFailure as error:
            reason = "relay_or_provider_request_failed"
            safe_relay_details = {
                "stage": error.stage,
                "relay_http_status": error.relay_status,
                "apns_http_status": error.apns_status,
                "error_code": error.error_code,
                "apns_reason": error.apns_reason,
            }
        except Exception:
            # Never log exception messages or provider responses; they can contain credentials or
            # tokens.
            reason = "relay_or_provider_request_failed"
        try:
            with Session(engine) as log_db:
                diagnostic(
                    log_db,
                    "notification",
                    "find-phone.push.result",
                    account_id,
                    device_id,
                    outcome,
                    provider=provider,
                    action_type=action,
                    reason=reason,
                    source="server push relay",
                    confirmed_delivery=False,
                    **safe_relay_details,
                )
                log_db.commit()
        except Exception:
            pass

    def store_command(db, body, actor, target, background_tasks):
        """Stores a checked, signed ring or stop command, replacing any still waiting for the
        phone, and pushes the phone so it fetches it straight away. actor is the account that
        asked for it.
        """
        value, now = body.body.model_dump(), time.time()
        envelope = canonical(body.model_dump()).decode()
        old = db.get(FindPhoneCommand, value["id"])
        if old:
            if old.envelope != envelope:
                raise HTTPException(409, "Command ID collision")
            return {"id": old.id, "status": old.status}
        db.query(FindPhoneCommand).filter_by(target_id=target.id).filter(
            FindPhoneCommand.status.in_(["pending", "received", "ringing"])
        ).update({FindPhoneCommand.status: "superseded"}, synchronize_session=False)
        db.query(FindPhoneCommand).filter(FindPhoneCommand.created < now - 14 * DAY).delete(
            synchronize_session=False
        )
        if db.query(FindPhoneCommand).count() >= 5000:
            raise HTTPException(429, "Alarm command history limit reached")
        db.add(
            FindPhoneCommand(
                id=value["id"],
                target_id=target.id,
                issuer_id=value["issuer"],
                created=now,
                expires=value["expires_at"],
                envelope=envelope,
                status="pending",
                reason="",
            )
        )
        audit(
            db,
            "phone." + value["action"] + ".requested",
            actor,
            target.id,
            command_id=value["id"],
            expires_at=value["expires_at"],
        )
        db.commit()
        sub = db.get(PushSubscription, target.id)
        if sub:
            try:
                config = available_config(db.get(ServiceState, 1), cipher)
                if config.get(sub.provider):
                    token = cipher.decrypt(sub.token.encode()).decode()
                    background_tasks.add_task(
                        push_find_phone_nudge,
                        sub.provider,
                        token,
                        config,
                        value["action"],
                        target.account_id,
                        target.id,
                    )
            except (ValueError, TypeError, KeyError):
                # A push failure must not undo the stored command, but it is logged.
                diagnostic(
                    db,
                    "notification",
                    "find-phone.push.result",
                    target.account_id,
                    target.id,
                    "failed",
                    provider=sub.provider,
                    action_type=value["action"],
                    reason="push_registration_or_configuration_unavailable",
                    source="server push relay",
                    confirmed_delivery=False,
                )
                db.commit()
        return {"id": value["id"], "status": "pending"}

    @app.post("/api/find-phone/commands", status_code=201)
    def request_phone_alarm(
        body: FindCommandInput,
        request: Request,
        background_tasks: BackgroundTasks,
        device=Depends(approved),
        db: Session = Depends(database),
    ):
        """Accepts a signed ring or stop command from the admin's browser and pushes the target
        phone.
        """
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        db.refresh(device)
        if device.status != "approved" or db.get(Account, device.account_id).role != "admin":
            raise HTTPException(403, "An approved administrator device is required")
        rate(request, "find-phone-command", 20)
        value = body.body.model_dump()
        now = time.time()
        if value["issuer"] != device.id or value["household"] != state.household_id:
            raise HTTPException(403, "Command identity mismatch")
        verify_signature(device.signing_key, value, body.signature)
        if (
            value["issued_at"] > now + 30
            or value["issued_at"] < now - 30
            or value["expires_at"] <= now
            or not 1 <= value["expires_at"] - value["issued_at"] <= 120
        ):
            raise HTTPException(422, "Command time is invalid or expired")
        target = db.get(ClientDevice, value["target"])
        cap = db.get(FindPhoneCapability, value["target"])
        if not target or target.status != "approved" or not cap or not cap.enabled:
            raise HTTPException(409, "The target phone has not enabled Find my phone")
        return store_command(db, body, device.account_id, target, background_tasks)

    def last_phone_command(db, target):
        """Returns the newest command for a device."""
        return db.scalar(
            select(FindPhoneCommand)
            .where(FindPhoneCommand.target_id == target)
            .order_by(FindPhoneCommand.created.desc(), FindPhoneCommand.id.desc())
            .limit(1)
        )

    @app.get("/api/find-phone/command")
    def poll_phone_alarm(device=Depends(approved), db: Session = Depends(database)):
        """Returns the pending signed command for the requesting phone, which verifies it itself."""
        cap = db.get(FindPhoneCapability, device.id)
        if not cap or not cap.enabled:
            return {"command": None}
        cap.seen = time.time()
        row = last_phone_command(db, device.id)
        if row and row.expires <= time.time() and row.status in ("pending", "received", "ringing"):
            row.status = "expired"
        result = (
            json.loads(row.envelope)
            if row
            and row.expires > time.time()
            and row.status in ("pending", "received", "ringing")
            else None
        )
        db.commit()
        return {"command": result}

    @app.post("/api/find-phone/report")
    def report_phone_alarm(
        body: FindReportInput, device=Depends(approved), db: Session = Depends(database)
    ):
        """Stores a phone's status report for a command."""
        row = db.get(FindPhoneCommand, body.command_id)
        if not row or row.target_id != device.id:
            raise HTTPException(404, "Command not found for this device")
        if row.status == "superseded" or (
            row.status in ("stopped", "failed", "blocked", "expired", "cancelled")
            and body.status in ("received", "ringing")
        ):
            return {"recorded": False}
        if row.expires <= time.time() and body.status in ("received", "ringing"):
            row.status = "expired"
        else:
            row.status = body.status
        row.reason, row.reported_at = body.reason, time.time()
        audit(
            db,
            "phone.alarm." + row.status,
            device.account_id,
            device.id,
            command_id=row.id,
            report_source="device report",
            reason=body.reason,
        )
        db.commit()
        return {"recorded": True}

    @app.get("/api/find-phone/status/{device_id}")
    def phone_alarm_status(device_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Returns a phone's last contact time and its latest command status, for the admin."""
        device = db.get(ClientDevice, device_id)
        if not device or device.status != "approved":
            raise HTTPException(404, "Approved device not found")
        cap = db.get(FindPhoneCapability, device_id)
        row = last_phone_command(db, device_id)
        if row and row.expires <= time.time() and row.status in ("pending", "received", "ringing"):
            row.status = "expired"
            db.commit()
        return {
            "enabled": bool(cap and cap.enabled),
            "platform": cap.platform if cap else None,
            "last_poll": cap.seen if cap else None,
            "status": row.status if row else "idle",
            "reason": row.reason if row else "",
            "reported_at": row.reported_at if row else None,
            "action": json.loads(row.envelope)["body"]["action"] if row else None,
        }

    return store_command
