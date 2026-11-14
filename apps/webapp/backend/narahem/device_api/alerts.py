"""Household alert history."""

import json
import time

from fastapi import Depends, Query
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem.data_service import DAY
from narahem.models import (
    ClientDevice,
    ServerAlert,
)


def install(app, *, approved, audience_accounts, cipher, database, household_alerts, member_name):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.get("/api/alerts")
    def recent_household_alerts(
        since: int = Query(default=0, ge=0, le=9007199254740991),
        device=Depends(approved),
        db: Session = Depends(database),
    ):
        """Returns alerts about other members that this device may see, oldest first, with their
        text.
        """
        start = max(since, int((time.time() - DAY) * 1000))
        rows = db.scalars(
            select(ServerAlert)
            .where(
                ServerAlert.ready.is_(True),
                ServerAlert.captured_at >= start,
                ServerAlert.account_id != device.account_id,
            )
            .order_by(ServerAlert.captured_at.desc())
            .limit(50)
        ).all()
        audiences, names, alerts = {}, {}, []
        for row in reversed(rows):
            if row.device_id not in audiences:
                sender = db.get(ClientDevice, row.device_id)
                audiences[row.device_id] = (
                    audience_accounts(db, row.device_id)
                    if sender and sender.status == "approved"
                    else set()
                )
            if device.account_id not in audiences[row.device_id]:
                continue
            if row.account_id not in names:
                names[row.account_id] = member_name(db, row.account_id)
            alert = json.loads(cipher.decrypt(row.payload.encode()))
            alerts.append(
                {
                    "id": row.id,
                    "account_id": row.account_id,
                    "captured_at": row.captured_at,
                    "text": household_alerts.render(names[row.account_id], alert),
                }
            )
        return {"alerts": alerts}
