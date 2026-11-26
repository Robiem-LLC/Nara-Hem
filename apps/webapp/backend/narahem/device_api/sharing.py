"""Location sharing on/off and each phone's audience."""

import json
import re

from fastapi import Depends, HTTPException
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem import review_mode
from narahem.app import trusted_accounts
from narahem.data_service import audit, canonical
from narahem.models import (
    Account,
    DeviceSharingAudience,
    EncryptedRecord,
    RecordRecipient,
    ServiceState,
)
from narahem.schemas import (
    AudienceInput,
    SharingInput,
)


def install(app, *, active_devices, approved, database):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.put("/api/sharing")
    def sharing(body: SharingInput, device=Depends(approved), db: Session = Depends(database)):
        """Enables or disables location sharing for the requesting device."""
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.refresh(device)
        if device.status != "approved":
            raise HTTPException(403, "Device revoked")
        previous_sharing = device.sharing
        device.sharing = body.enabled
        audit(
            db,
            "sharing.resumed" if body.enabled else "sharing.paused",
            device.account_id,
            device.id,
            before=previous_sharing,
            after=body.enabled,
        )
        db.commit()
        return {"enabled": device.sharing}

    @app.get("/api/sharing/audience")
    def sharing_audience(device=Depends(approved), db: Session = Depends(database)):
        """Returns the device's sharing audience (always including the admin browser), the
        eligible members and the admin browser.
        """
        row = db.get(DeviceSharingAudience, device.id)
        targets = json.loads(row.account_ids) if row else None
        if review_mode.is_tester(db.get(Account, device.account_id)):
            # On an open demo server, a tester's phone shares with nobody.
            return {
                "account_ids": [],
                "default_all": False,
                "owner_viewer": None,
                "eligible_members": [],
            }
        # Testers on an open demo server are never offered to other phones.
        eligible = [
            a
            for a in db.scalars(
                select(Account)
                .where(
                    Account.status == "active",
                    Account.role != "admin",
                    trusted_accounts(),
                    Account.id != device.account_id,
                )
                .order_by(Account.id)
            )
            if not review_mode.is_tester(a)
        ]
        permitted = [a.id for a in eligible]
        # The admin browser always sees a phone that shares its location.
        owner = db.scalar(
            select(Account)
            .where(Account.status == "active", Account.role == "admin", trusted_accounts())
            .order_by(Account.id)
        )
        owner_id = owner.id if owner and owner.id != device.account_id else None
        chosen = set(permitted) if targets is None else set(targets) & set(permitted)
        return {
            "account_ids": sorted(chosen | ({owner_id} if owner_id else set())),
            "default_all": row is None,
            "owner_viewer": {"id": owner_id, "name": "Approved household owner browser"}
            if owner_id
            else None,
            "eligible_members": [
                {"id": a.id, "name": a.username or "Member", "role": a.role} for a in eligible
            ],
        }

    @app.put("/api/sharing/audience")
    def change_sharing_audience(
        body: AudienceInput, device=Depends(approved), db: Session = Depends(database)
    ):
        """Sets the device's sharing audience. Removed viewers lose server access to existing
        records immediately, though they may keep what they already downloaded.
        """
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.refresh(device)
        if device.status != "approved":
            raise HTTPException(403, "Device revoked")
        if review_mode.is_tester(db.get(Account, device.account_id)):
            raise HTTPException(403, "On this demo server, your location isn't shared with anyone")
        row = db.get(DeviceSharingAudience, device.id)
        previous_targets = json.loads(row.account_ids) if row else "all eligible members"
        targets = body.account_ids
        if len(set(targets)) != len(targets) or targets != sorted(targets):
            raise HTTPException(422, "Choose unique sorted household members")
        eligible = {
            a.id
            for a in db.scalars(
                select(Account).where(Account.status == "active", trusted_accounts())
            )
        }

        if any(
            not re.fullmatch("[a-f0-9]{32}", target)
            or target == device.account_id
            or target not in eligible
            for target in targets
        ):
            raise HTTPException(
                422,
                "Only other active verified household members or the explicitly enabled owner "
                "viewer can be selected",
            )
        row = db.get(DeviceSharingAudience, device.id)
        if row:
            row.account_ids = canonical(targets).decode()
        else:
            db.add(
                DeviceSharingAudience(device_id=device.id, account_ids=canonical(targets).decode())
            )
        eligible_devices = {
            d.id
            for d in active_devices(db)
            if d.account_id == device.account_id or d.account_id in targets
        }
        # Remove removed viewers' access to existing records. New viewers never gain access to older
        # records.
        query = select(EncryptedRecord.id).where(
            EncryptedRecord.device_id == device.id, EncryptedRecord.kind.in_(("location", "event"))
        )
        excluded = db.query(RecordRecipient).filter(RecordRecipient.record_id.in_(query))
        if eligible_devices:
            excluded = excluded.filter(~RecordRecipient.device_id.in_(eligible_devices))
        excluded.delete(synchronize_session=False)
        audit(
            db,
            "sharing.audience",
            device.account_id,
            device.id,
            before=previous_targets,
            after=targets,
        )
        db.commit()
        return {"account_ids": targets}
