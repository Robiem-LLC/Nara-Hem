"""Native push subscriptions."""

import re

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from narahem.models import (
    PushDelivery,
    PushSubscription,
)
from narahem.schemas import (
    SubscribeInput,
)


def install(app, *, approved, cipher, database):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.put("/api/push/subscription")
    def subscribe(body: SubscribeInput, device=Depends(approved), db: Session = Depends(database)):
        """Stores the device's push token, encrypted."""
        if (
            (body.provider == "apns" and not re.fullmatch(r"[a-fA-F0-9]{32,512}", body.token))
            or not body.token.isascii()
            or any(c.isspace() for c in body.token)
        ):
            raise HTTPException(422, "Invalid push registration token")
        if body.provider != "apns" and body.environment is not None:
            raise HTTPException(422, "Only APNs registrations have environments")
        registration = (
            f"{body.environment}:{body.token}"
            if body.provider == "apns" and body.environment
            else body.token
        )
        value = cipher.encrypt(registration.encode()).decode()
        existing = db.get(PushSubscription, device.id)
        if existing:
            existing.provider, existing.token = body.provider, value
        else:
            db.add(PushSubscription(device_id=device.id, provider=body.provider, token=value))
        db.commit()
        return {"registered": True}

    @app.delete("/api/push/subscription")
    def unsubscribe(device=Depends(approved), db: Session = Depends(database)):
        """Deletes the device's push token and its queued deliveries."""
        db.query(PushSubscription).filter_by(device_id=device.id).delete()
        db.query(PushDelivery).filter_by(device_id=device.id).delete()
        db.commit()
        return {"removed": True}
