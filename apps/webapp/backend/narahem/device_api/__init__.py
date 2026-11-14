"""The device API: devices, encrypted records, sharing, Find My Phone and administration.

install() defines the helpers the areas share (authentication dependencies, visibility
rules, alert and trip bookkeeping), then registers each area's routes in a fixed order.
"""

import hashlib
import json
import math
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import (
    and_,
    or_,
    select,
)
from sqlalchemy.orm import Session

from narahem import alexa_api, household_alerts
from narahem.app import account_trusted, digest, trusted_accounts
from narahem.data_service import (
    DAY,
    canonical,
    prune,
)
from narahem.device_api import (
    alerts,
    devices,
    find_phone,
    push_subscriptions,
    records,
    roster,
    server_admin,
    sharing,
)
from narahem.models import (
    Account,
    AccountApproval,
    AlertMemory,
    ClientDevice,
    DeviceSharingAudience,
    EncryptedRecord,
    IndexedTrip,
    LatestState,
    PushDelivery,
    PushSubscription,
    RecordRecipient,
    ServerAlert,
    ServiceState,
    TripLabel,
)
from narahem.push_service import send_queued


def install(
    app,
    engine,
    directory,
    cipher,
    database,
    current,
    admin,
    rate,
    notifier=None,
    trip_processor=None,
    maps_key="",
):
    """Registers the device API routes and creates the helpers they share."""
    quota = int(os.environ.get("NARAHEM_STORAGE_QUOTA_MIB", "512")) * 1024 * 1024
    place_cache = {}

    if quota < 1024 * 1024:
        raise ValueError("Storage quota must be at least 1 MiB")

    def verified(auth=Depends(current), db: Session = Depends(database)):
        """Returns the signed-in account, raising a 403 unless its email is confirmed or it is
        approved.
        """
        if not account_trusted(auth[0], db):
            raise HTTPException(403, "Confirm your email before enrolling a device")
        return auth

    def credential(request: Request, db: Session = Depends(database)):
        """Returns the device identified by the bearer token, in any status. Also updates its
        last-seen time, at most once a minute.
        """
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 200:
            raise HTTPException(401, "Device credential required")
        device = db.scalar(
            select(ClientDevice).where(ClientDevice.credential == digest(header[7:]))
        )
        account = db.get(Account, device.account_id) if device else None
        if (
            not device
            or device.status == "revoked"
            or not account
            or account.status != "active"
            or not account_trusted(account, db)
        ):
            raise HTTPException(401, "Device credential not accepted")
        if time.time() - (device.seen or 0) > 60:
            device.seen = time.time()
            db.commit()
        return device

    def approved(device=Depends(credential)):
        """Returns the requesting device, raising a 403 unless it is approved."""
        if device.status != "approved":
            raise HTTPException(403, "Trusted device approval required")
        return device

    def active_devices(db):
        """Returns every approved device belonging to an active account."""
        return list(
            db.scalars(
                select(ClientDevice)
                .join(Account, Account.id == ClientDevice.account_id)
                .where(
                    ClientDevice.status == "approved",
                    Account.status == "active",
                    trusted_accounts(),
                )
                .order_by(ClientDevice.id)
            )
        )

    def available(record, device, db):
        """Returns True if the record was encrypted for this device."""
        body = json.loads(record.envelope)["body"]
        return db.get(RecordRecipient, (record.id, device.id)) is not None and any(
            x["device_id"] == device.id for x in body["recipients"]
        )

    def audience_accounts(db, device_id):
        """Returns the accounts a device shares its location with: its chosen audience, or every
        member if it hasn't chosen, and always the admin, whose browser sees every phone that
        shares its location.
        """
        audience = db.get(DeviceSharingAudience, device_id)
        members = {
            a.id
            for a in db.scalars(
                select(Account).where(
                    Account.status == "active", Account.role != "admin", trusted_accounts()
                )
            )
        }
        admins = {
            a.id
            for a in db.scalars(
                select(Account).where(
                    Account.status == "active", Account.role == "admin", trusted_accounts()
                )
            )
        }
        chosen = set(json.loads(audience.account_ids)) & members if audience else members
        return chosen | admins

    def event_audience(db, device):
        """Returns the approved devices a device's location and trip records must be encrypted
        for.
        """
        targets = audience_accounts(db, device.id)
        return sorted(
            d.id
            for d in active_devices(db)
            if d.account_id == device.account_id or d.account_id in targets
        )

    def joined_day(account_id, db):
        """Returns the start of the UTC day the account was approved, in milliseconds. The admin
        has no limit.
        """
        approval = db.get(AccountApproval, account_id)
        return int(approval.created // DAY * DAY * 1000) if approval else 0

    def trip_visible(db, row, device):
        """Returns True if the device may read a trip: its own account's, or one from a device
        sharing with it now, dated on or after the day its account joined.
        """
        if device.account_id == row.account_id:
            return True
        return device.account_id in audience_accounts(
            db, row.device_id
        ) and row.ended_at >= joined_day(device.account_id, db)

    def location_visible(db, record, device):
        """Returns True if the device may see a member's latest location: their own, or one from
        a device that shares with it now.
        """
        sender = db.get(ClientDevice, record.device_id)
        if not sender or sender.status != "approved" or not sender.sharing:
            return False
        return device.account_id == record.account_id or device.account_id in audience_accounts(
            db, record.device_id
        )

    def server_places(db):
        """Returns the saved places decrypted with the server's key, for alerts."""
        token, rows = places_manifest(db)
        if place_cache.get("token") != token:
            places = []
            for row in rows:
                body = json.loads(row.envelope)["body"]
                if row.operation != "upsert" or not body.get("server_box"):
                    continue
                try:
                    data = trip_processor.open_record(body)["data"]
                except HTTPException:
                    continue
                if isinstance(data.get("name"), str) and all(
                    type(data.get(k)) in (int, float) for k in ("lat", "lon", "radius")
                ):
                    places.append(
                        {
                            "id": row.entity_id,
                            "name": data["name"][:80],
                            "lat": float(data["lat"]),
                            "lon": float(data["lon"]),
                            "radius": float(data["radius"]),
                            "alerts": data["alerts"]
                            if isinstance(data.get("alerts"), dict)
                            else {},
                        }
                    )
            place_cache.update(token=token, places=places)
        return place_cache["places"]

    def alert_memory(db, device_id):
        """Returns a device's decrypted alert memory and its database row."""
        row = db.get(AlertMemory, device_id)
        memory = (
            json.loads(cipher.decrypt(row.state.encode()))
            if row
            else household_alerts.fresh_memory()
        )
        return row, memory

    def keep_memory(db, row, device_id, memory):
        """Encrypts and saves a device's alert memory."""
        state = cipher.encrypt(json.dumps(memory, separators=(",", ":")).encode()).decode()
        if row:
            row.state = state
        else:
            db.add(AlertMemory(device_id=device_id, state=state))

    def push_alert(db, item, now):
        """Queues a push to the devices of members who receive this alert. They fetch the text
        themselves.
        """
        audience = audience_accounts(db, item.device_id)
        for target in active_devices(db):
            if (
                target.account_id != item.account_id
                and target.account_id in audience
                and db.get(PushSubscription, target.id)
            ):
                db.add(
                    PushDelivery(
                        id=secrets.token_hex(16),
                        record_id=item.id,
                        device_id=target.id,
                        created=now,
                        expires_at=item.captured_at / 1000 + household_alerts.STALE_MS / 1000,
                    )
                )

    def raise_alerts(db, device, captured_at, alerts, now):
        """Stores new alerts and queues pushes, unless the fix arrived too late for the alert to
        be useful.
        """
        if now * 1000 - captured_at > household_alerts.STALE_MS:
            return  # uploaded too late to be news
        for alert in alerts:
            if "at" in alert and os.environ.get("NARAHEM_ALERT_ADDRESSES", "1") == "0":
                alert = {k: v for k, v in alert.items() if k != "at"} | {
                    "place": household_alerts.place_from(None)
                }
            item = ServerAlert(
                id=secrets.token_hex(16),
                account_id=device.account_id,
                device_id=device.id,
                captured_at=captured_at,
                created=now,
                ready="place" in alert,
                attempts=0,
                payload=cipher.encrypt(json.dumps(alert).encode()).decode(),
            )
            db.add(item)
            if item.ready:
                push_alert(db, item, now)

    def note_fix(db, device, captured_at, data, now):
        """Updates the device's alert memory with a new location and raises any departure alerts."""
        lat, lon, accuracy = data.get("lat"), data.get("lon"), data.get("accuracy")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon, accuracy)):
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        trip_id = data.get("trip_id") if isinstance(data.get("trip_id"), str) else None
        row, memory = alert_memory(db, device.id)
        if captured_at < memory.get("last_at", 0):
            return  # an older fix uploaded late
        memory, alerts = household_alerts.on_fix(
            memory,
            device.account_id,
            float(lat),
            float(lon),
            float(accuracy),
            trip_id,
            captured_at,
            server_places(db),
        )
        keep_memory(db, row, device.id, memory)
        raise_alerts(db, device, captured_at, alerts, now)

    def note_trip_end(db, device, summary, now):
        """Updates the alert memory at the end of a trip and raises an arrival alert."""
        if not summary.get("end"):
            return
        row, memory = alert_memory(db, device.id)
        memory, alert = household_alerts.on_trip_end(
            memory,
            device.account_id,
            summary["end"],
            summary["distance_m"],
            summary["max_speed_mps"],
            server_places(db),
        )
        memory["last_at"] = max(memory.get("last_at", 0), summary["ended_at"])
        memory["still_since"] = summary["ended_at"]  # parked where the drive ended
        keep_memory(db, row, device.id, memory)
        raise_alerts(db, device, summary["ended_at"], [alert] if alert else [], now)

    def member_name(db, account_id):
        """Returns a member's display name from their latest profile, or a fallback."""
        profile = db.get(LatestState, ("profile", account_id))
        record = db.get(EncryptedRecord, profile.record_id) if profile else None
        body = json.loads(record.envelope)["body"] if record else {}
        if body.get("server_box"):
            try:
                name = trip_processor.open_record(body)["data"].get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()[:64]
            except HTTPException:
                pass
        account = db.get(Account, account_id)
        return (account.username if account and account.username else None) or "A household member"

    def resolve_alert_addresses(db):
        """Names the location of pending alerts (a saved place reached shortly after the trip,
        otherwise a street address) and queues their pushes.
        """
        for item in db.scalars(
            select(ServerAlert)
            .where(ServerAlert.ready.is_(False))
            .order_by(ServerAlert.created)
            .limit(3)
        ).all():
            alert = json.loads(cipher.decrypt(item.payload.encode()))
            if time.time() * 1000 - item.captured_at > household_alerts.STALE_MS:
                db.delete(item)
                continue
            if alert["kind"] == "arrived":
                fixes = device_fixes(
                    db,
                    item.account_id,
                    item.device_id,
                    item.captured_at,
                    item.captured_at + household_alerts.BOUNDARY_MS,
                    limit=200,
                )
                place = household_alerts.boundary_place(
                    alert["at"], item.captured_at, fixes, server_places(db), after=True
                )
                if place and not household_alerts.allowed(place, item.account_id, departure=False):
                    db.delete(item)
                    continue
                if place:
                    alert["place"] = place["name"]
                elif time.time() * 1000 - item.captured_at < household_alerts.BOUNDARY_MS:
                    continue
            if "place" not in alert:
                address = household_alerts.lookup_address(alert["at"][0], alert["at"][1], maps_key)
                if address is None and item.attempts < 2:
                    item.attempts += 1
                    continue
                alert["place"] = household_alerts.place_from(address)
            alert.pop("at", None)
            item.payload, item.ready = cipher.encrypt(json.dumps(alert).encode()).decode(), True
            push_alert(db, item, time.time())
        db.commit()

    def device_fixes(db, account_id, device_id, start, end, trip_id=None, limit=1000):
        """Returns a device's GPS fixes between two times, decrypted with the server's key,
        oldest first.
        """
        fixes = []
        for item in db.scalars(
            select(EncryptedRecord)
            .where(
                EncryptedRecord.kind == "location",
                EncryptedRecord.account_id == account_id,
                EncryptedRecord.device_id == device_id,
                EncryptedRecord.captured_at >= start,
                EncryptedRecord.captured_at <= end,
            )
            .order_by(EncryptedRecord.captured_at)
            .limit(limit)
        ):
            body = json.loads(item.envelope)["body"]
            if not body.get("server_box"):
                continue
            try:
                data = trip_processor.open_record(body)["data"]
            except HTTPException:
                continue
            if trip_id and data.get("trip_id") not in (None, trip_id):
                continue
            if all(type(data.get(k)) in (int, float) for k in ("lat", "lon", "accuracy")):
                fixes.append(
                    {
                        "lat": float(data["lat"]),
                        "lon": float(data["lon"]),
                        "accuracy": float(data["accuracy"]),
                        "time": item.captured_at,
                    }
                )
        return fixes

    def label_trips(db):
        """Names the start and end of finished trips (saved place, otherwise street address),
        once per trip after late fixes have arrived.
        """
        settled = int(time.time() * 1000) - household_alerts.BOUNDARY_MS - 60_000
        pending = db.execute(
            select(IndexedTrip, TripLabel)
            .outerjoin(TripLabel, TripLabel.event_id == IndexedTrip.event_id)
            .where(
                IndexedTrip.status.in_(("ready", "raw")),
                IndexedTrip.ended_at < settled,
                or_(
                    TripLabel.event_id.is_(None),
                    and_(TripLabel.labels.is_(None), TripLabel.attempts < 3),
                ),
            )
            .order_by(IndexedTrip.ended_at.desc())
            .limit(1)
        ).all()
        lookups = os.environ.get("NARAHEM_ALERT_ADDRESSES", "1") != "0"
        for row, label in pending:
            trip = json.loads(cipher.decrypt(row.encrypted_trip.encode()))
            found, failed = {}, False
            for side, at, after in (("start", row.started_at, False), ("end", row.ended_at, True)):
                point = trip.get(side)
                window = (
                    (at, at + household_alerts.BOUNDARY_MS)
                    if after
                    else (at - household_alerts.START_LOOKBACK_MS, at)
                )
                fixes = device_fixes(db, row.account_id, row.device_id, *window, limit=200)
                place = household_alerts.boundary_place(point, at, fixes, server_places(db), after)
                if place:
                    found[side] = {"place": place["id"]}
                elif point and lookups:
                    address = household_alerts.lookup_address(point[0], point[1], maps_key)
                    if address:
                        found[side] = {"address": address}
                    else:
                        failed = True
            if label is None:
                label = TripLabel(event_id=row.event_id, attempts=0)
                db.add(label)
            label.attempts += 1
            if not failed or label.attempts >= 3:
                label.labels = cipher.encrypt(json.dumps(found).encode()).decode()
        db.commit()

    def trip_endpoint_labels(db, rows, trips):
        """Returns start_label and end_label for each trip: a saved place containing the point
        now, otherwise the label stored when the trip was named.
        """
        places = server_places(db)
        by_id = {p["id"]: p["name"] for p in places}
        stored = {
            r.event_id: r
            for r in db.scalars(
                select(TripLabel).where(
                    TripLabel.event_id.in_([row.event_id for row in rows]),
                    TripLabel.labels.is_not(None),
                )
            )
        }
        result = {}
        for row, trip in zip(rows, trips):
            noted = (
                json.loads(cipher.decrypt(stored[row.event_id].labels.encode()))
                if row.event_id in stored
                else {}
            )
            labels = {}
            for side in ("start", "end"):
                point = trip.get(side)
                here = household_alerts.match(point[0], point[1], places) if point else None
                kept = noted.get(side, {})
                text = here["name"] if here else by_id.get(kept.get("place")) or kept.get("address")
                if text:
                    labels[side + "_label"] = text
            result[row.event_id] = labels
        return result

    def visible_query(db):
        """Returns a query for records inside the retention period."""
        cutoff = int((time.time() - db.get(ServiceState, 1).retention_days * DAY) * 1000)
        return select(EncryptedRecord).where(
            (EncryptedRecord.expires_at.is_(None))
            | and_(EncryptedRecord.captured_at > cutoff, EncryptedRecord.expires_at > time.time())
        )

    def serialize(record):
        """Returns a record in the format the apps expect: the signed envelope plus server
        metadata.
        """
        return {
            "envelope": json.loads(record.envelope),
            "received_at": record.received_at,
            "expires_at": record.expires_at,
        }

    def places_manifest(db):
        """Returns the current saved places and a token that changes whenever any of them
        changes.
        """
        rows = list(
            db.scalars(
                select(EncryptedRecord)
                .join(LatestState, LatestState.record_id == EncryptedRecord.id)
                .where(LatestState.kind == "place")
                .order_by(EncryptedRecord.entity_id)
            )
        )
        token = hashlib.sha256(canonical([[row.entity_id, row.id] for row in rows])).hexdigest()
        return token, rows

    def deliveries():
        """Background job: runs retention cleanup every five minutes and sends queued pushes."""
        with Session(engine) as db:
            if time.time() - db.get(ServiceState, 1).last_cleanup >= 300:
                prune(db)

            send_queued(db, cipher, notifier)

    def place_names():
        """Background job: names trip ends and alert locations. Runs separately from pushes and
        email because address lookups can be slow.
        """
        with Session(engine) as db:
            resolve_alert_addresses(db)
            label_trips(db)

    def maintenance():
        """Background job: runs place_names() and deliveries()."""
        place_names()
        deliveries()

    alerts.install(
        app,
        approved=approved,
        audience_accounts=audience_accounts,
        cipher=cipher,
        database=database,
        household_alerts=household_alerts,
        member_name=member_name,
    )
    devices.install(
        app,
        credential=credential,
        current=current,
        database=database,
        rate=rate,
        trip_processor=trip_processor,
        verified=verified,
    )
    store_command = find_phone.install(
        app,
        admin=admin,
        approved=approved,
        cipher=cipher,
        database=database,
        engine=engine,
        notifier=notifier,
        rate=rate,
    )
    roster.install(
        app,
        active_devices=active_devices,
        credential=credential,
        database=database,
        directory=directory,
    )
    sharing.install(app, active_devices=active_devices, approved=approved, database=database)
    records.install(
        app,
        active_devices=active_devices,
        alert_memory=alert_memory,
        approved=approved,
        available=available,
        cipher=cipher,
        database=database,
        device_fixes=device_fixes,
        event_audience=event_audience,
        location_visible=location_visible,
        note_fix=note_fix,
        note_trip_end=note_trip_end,
        places_manifest=places_manifest,
        quota=quota,
        serialize=serialize,
        trip_endpoint_labels=trip_endpoint_labels,
        trip_processor=trip_processor,
        trip_visible=trip_visible,
        visible_query=visible_query,
    )
    server_admin.install(
        app, admin=admin, database=database, quota=quota, visible_query=visible_query
    )
    push_subscriptions.install(app, approved=approved, cipher=cipher, database=database)

    if alexa_api.enabled():
        alexa_api.install(
            app,
            admin=admin,
            alert_memory=alert_memory,
            cipher=cipher,
            database=database,
            engine=engine,
            maps_key=maps_key,
            member_name=member_name,
            rate=rate,
            server_places=server_places,
            store_command=store_command,
            trip_processor=trip_processor,
        )

    app.state.maintenance = maintenance
    app.state.deliveries = deliveries
    app.state.place_names = place_names
