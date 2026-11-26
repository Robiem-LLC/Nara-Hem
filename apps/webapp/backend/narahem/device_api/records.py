"""Encrypted records, places, trips and the household view."""

import hmac
import json
import re
import time

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import (
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from narahem import review_mode
from narahem.data_service import DAY, audit, canonical, decode, verify_signature
from narahem.models import (
    Account,
    AlertMemory,
    ClientDevice,
    EncryptedRecord,
    IndexedTrip,
    LatestState,
    PushDelivery,
    RecordRecipient,
    ServiceState,
)
from narahem.schemas import (
    RecordInput,
)
from narahem.trip_processing import meters, normalize_points
from narahem.zones import zone_name

# A trip that sets off within this distance of where the previous one ended starts there.
ANCHOR_METERS = 250


def install(
    app,
    *,
    active_devices,
    alert_memory,
    approved,
    available,
    cipher,
    database,
    device_fixes,
    event_audience,
    location_visible,
    note_fix,
    note_trip_end,
    places_manifest,
    quota,
    serialize,
    trip_endpoint_labels,
    trip_processor,
    trip_visible,
    visible_query,
):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    def anchor_starts(db, rows, trips, device):
        """Starts each trip where the person's previous trip ended, when that's within
        ANCHOR_METERS. Phones only notice movement a little after someone sets off, so otherwise
        "left" would sit a short way down the road from where they "arrived". Changes the trips
        in place and returns, by event id, the previous trip's arrival name to use as the start.
        """
        names = {}
        for row, trip in zip(rows, trips):
            start = trip.get("start")
            previous = db.scalar(
                select(IndexedTrip)
                .where(
                    IndexedTrip.account_id == row.account_id,
                    IndexedTrip.ended_at <= row.started_at,
                    IndexedTrip.event_id != row.event_id,
                    IndexedTrip.status.in_(("ready", "raw")),
                    IndexedTrip.encrypted_trip.is_not(None),
                )
                .order_by(IndexedTrip.ended_at.desc())
                .limit(1)
            )
            if not start or not previous or not trip_visible(db, previous, device):
                continue
            before = json.loads(cipher.decrypt(previous.encrypted_trip.encode()))
            end = before.get("end")
            if not end:
                continue
            gap = meters({"lat": end[0], "lon": end[1]}, {"lat": start[0], "lon": start[1]})
            if gap > ANCHOR_METERS:
                continue
            trip["start"] = list(end)
            route = trip.get("route")
            if isinstance(route, list) and route and list(route[0]) != list(end):
                trip["route"] = [list(end), *route]
                if isinstance(trip.get("times"), list) and trip["times"]:
                    trip["times"] = [trip["times"][0], *trip["times"]]
            if isinstance(trip.get("distance_m"), (int, float)):
                trip["distance_m"] = round(trip["distance_m"] + gap, 2)
            name = trip_endpoint_labels(db, [previous], [before])[previous.event_id]
            if name.get("end_label"):
                names[row.event_id] = name["end_label"]
        return names

    @app.get("/api/profile/current")
    def own_profile_pointer(device=Depends(approved), db: Session = Depends(database)):
        """Returns the ID of this account's current profile record, for edit conflict checks.
        Never returns profile content.
        """
        latest = db.get(LatestState, ("profile", device.account_id))
        return {"replaces": latest.record_id if latest else None}

    @app.get("/api/places/manifest")
    def shared_places_manifest(device=Depends(approved), db: Session = Depends(database)):
        """Returns the saved places list and its change token, which is required to save a place."""
        token, rows = places_manifest(db)
        return {
            "token": token,
            "places": [
                {"id": row.entity_id, "record_id": row.id, "operation": row.operation}
                for row in rows
            ],
        }

    def check_audience(db, device, value):
        """Checks the record is encrypted for exactly the devices allowed to read it, and returns
        the recipient IDs.
        """
        recipients = [r["device_id"] for r in value["recipients"]]
        devices = active_devices(db)
        everyone = sorted(d.id for d in devices)
        accepted = [everyone]
        if value["kind"] in ("location", "event"):
            allowed = event_audience(db, device)
            # The admin browser always may see a sharing phone, but phone builds from before that
            # don't encrypt for it; their records are still accepted.
            admins = {
                d.id
                for d in devices
                if d.account_id != device.account_id
                and db.get(Account, d.account_id).role == "admin"
            }
            accepted = [allowed, [d for d in allowed if d not in admins]]
        if recipients not in accepted:
            raise HTTPException(
                409, "Refresh the approved sharing audience and re-encrypt for its exact devices"
            )
        for recipient in value["recipients"]:
            decode(
                recipient["box"],
                minimum=48,
                maximum={"profile": 16384, "event": 8192}.get(value["kind"], 2048),
            )
        return recipients

    def open_server_copy(value):
        """Decrypts the server's copy of the record, if present. Updates must include one."""
        if value.get("server_box") is not None:
            if value["kind"] not in ("location", "event", "place", "profile") or (
                value["kind"] != "place" and value["operation"] != "upsert"
            ):
                raise HTTPException(
                    422, "Server copy is only valid for location, trip, place or profile records"
                )
            return trip_processor.open_record(value)
        if value["operation"] == "upsert":
            raise HTTPException(422, "Update the app: the server needs its own copy of this record")
        return None

    def check_limits(db, device, value, state, size, now, latest_state):
        """Checks size, sequence replay, capture time, sharing state, permissions, quota, edit
        conflicts and rate limits.
        """
        if size > 1024 * 1024:
            raise HTTPException(413, "Encrypted record too large")
        if value["sequence"] <= device.last_sequence:
            raise HTTPException(409, "Device sequence replay rejected")
        if value["captured_at"] > int((now + 300) * 1000) or value["captured_at"] <= int(
            (now - state.retention_days * DAY) * 1000
        ):
            raise HTTPException(422, "Capture time outside the retention window")
        if value["kind"] in ("location", "event") and (
            not device.sharing or value["operation"] != "upsert"
        ):
            raise HTTPException(403, "Sharing paused or invalid operation")
        if (
            value["kind"] == "place"
            and value["operation"] == "delete"
            and db.get(Account, device.account_id).role != "admin"
        ):
            raise HTTPException(403, "Only a household administrator can delete a saved place")
        if value["kind"] in ("location", "profile") and value["entity_id"] != device.account_id:
            raise HTTPException(403, "This record must describe the publishing account")
        used = db.scalar(select(func.coalesce(func.sum(EncryptedRecord.bytes), 0)))
        if used + size > quota:
            raise HTTPException(507, "Encrypted storage quota reached; run retention cleanup")
        if value["kind"] in ("place", "profile"):
            if value["replaces"] != (latest_state.record_id if latest_state else None):
                raise HTTPException(409, "Saved state changed; refresh before editing")
            if (
                latest_state is None
                and db.query(LatestState).filter(LatestState.kind.in_(["place", "profile"])).count()
                >= 64
            ):
                raise HTTPException(409, "Saved state limit reached")
        elif (
            db.query(EncryptedRecord)
            .filter_by(device_id=device.id)
            .filter(EncryptedRecord.received_at > now - 60)
            .count()
            >= 120
        ):
            raise HTTPException(429, "Device update rate exceeded")

    def index_trip(db, device, record, meta, now):
        """Stores a trip summary index entry, encrypted with the server's key, so allowed devices
        can list it immediately.
        """
        summary_data = trip_summary(record, device, meta)
        db.add(
            IndexedTrip(
                event_id=record.id,
                account_id=device.account_id,
                device_id=device.id,
                started_at=summary_data["started_at"],
                ended_at=summary_data["ended_at"],
                trip_id=summary_data["trip_id"],
                status="ready",
                encrypted_trip=cipher.encrypt(
                    json.dumps(summary_data, separators=(",", ":")).encode()
                ).decode(),
                updated_at=time.time(),
            )
        )
        note_trip_end(db, device, summary_data, now)

    @app.post("/api/records", status_code=201)
    def ingest(
        body: RecordInput,
        request: Request,
        device=Depends(approved),
        db: Session = Depends(database),
    ):
        """Validates a signed, encrypted record from a device and stores it."""
        # Lock the household row so a roster change can't race this upload.
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        db.refresh(device)
        if device.status != "approved" or db.get(Account, device.account_id).status != "active":
            raise HTTPException(403, "Device access revoked")
        # exclude_unset keeps signatures valid from older apps that don't send server_box.
        value, now = body.body.model_dump(exclude_unset=True), time.time()
        if value["sender"] != device.id or value["household"] != state.household_id:
            raise HTTPException(403, "Sender or household mismatch")
        verify_signature(device.signing_key, value, body.signature)
        envelope = canonical({"body": value, "signature": body.signature}).decode()
        existing = db.get(EncryptedRecord, value["id"])
        if existing:
            if existing.device_id != device.id or existing.envelope != envelope:
                raise HTTPException(409, "Record identity collision")
            return {"id": existing.id, "duplicate": True}
        if value["kind"] == "place":
            token, _ = places_manifest(db)
            if not hmac.compare_digest(request.headers.get("x-places-state", ""), token):
                raise HTTPException(
                    409, "Shared places changed; refresh with a current client before saving"
                )
        if value["revision"] != state.revision:
            raise HTTPException(409, "Refresh trusted membership and re-encrypt before publishing")
        recipients = check_audience(db, device, value)
        if review_mode.is_tester(db.get(Account, device.account_id)):
            # On an open demo server, a tester's records reach only their own phone, and they
            # can't add places that would show up for everyone else.
            if value["kind"] == "place":
                raise HTTPException(403, "Places can't be added on this demo server")
            own = {d.id for d in active_devices(db) if d.account_id == device.account_id}
            recipients = [r for r in recipients if r in own]
        clear_data = open_server_copy(value)
        size = len(envelope.encode())
        latest_state = db.get(LatestState, (value["kind"], value["entity_id"]))
        check_limits(db, device, value, state, size, now, latest_state)
        record = EncryptedRecord(
            id=value["id"],
            account_id=device.account_id,
            device_id=device.id,
            sequence=value["sequence"],
            kind=value["kind"],
            entity_id=value["entity_id"],
            captured_at=value["captured_at"],
            received_at=now,
            expires_at=(value["captured_at"] / 1000 + state.retention_days * DAY)
            if value["kind"] in ("location", "event")
            else None,
            operation=value["operation"],
            envelope=envelope,
            bytes=size,
        )
        db.add(record)
        db.flush()
        if value["kind"] == "event" and clear_data is not None:
            meta = clear_data.get("data")
            if isinstance(meta, dict) and meta.get("type") == "trip_summary":
                index_trip(db, device, record, meta, now)
        if value["kind"] == "location" and clear_data is not None:
            note_fix(db, device, value["captured_at"], clear_data["data"], now)
        for recipient in recipients:
            db.add(RecordRecipient(record_id=record.id, device_id=recipient))
        if value["kind"] in ("location", "place", "profile"):
            update_latest(db, value, record, latest_state)
        device.last_sequence, device.seen = value["sequence"], now
        db.commit()
        return {"id": record.id, "duplicate": False}

    @app.post("/api/records/batch", status_code=201)
    def ingest_batch(
        body: dict, request: Request, device=Depends(approved), db: Session = Depends(database)
    ):
        """Accepts up to 12 signed location records in one request. Each goes through the same
        checks as a single upload and is committed separately, so clients can retry the ones
        that failed.
        """
        records = body.get("records")
        responses = []
        if not isinstance(records, list) or not 1 <= len(records) <= 12:
            raise HTTPException(422, "A batch must contain 1-12 encrypted records")
        for entry in records:
            try:
                item = RecordInput.model_validate(entry)
            except Exception:
                raise HTTPException(422, "Invalid signed record in batch") from None
            if item.body.kind != "location":
                raise HTTPException(422, "Only GPS records may be batched")
            responses.append(ingest(item, request, device, db))
        return {"records": responses}

    @app.get("/api/records")
    def history(
        kind: str = "location",
        cursor: str | None = None,
        limit: int = 50,
        account_id: str | None = None,
        device_id: str | None = None,
        start: int | None = Query(default=None, ge=0, le=9007199254740991),
        end: int | None = Query(default=None, ge=0, le=9007199254740991),
        device=Depends(approved),
        db: Session = Depends(database),
    ):
        """Returns a page of location or event history this device may read."""
        if kind not in ("location", "event") or not 1 <= limit <= 50:
            raise HTTPException(422, "Use a history kind and limit 1–50")
        query = (
            visible_query(db)
            .join(RecordRecipient, RecordRecipient.record_id == EncryptedRecord.id)
            .where(RecordRecipient.device_id == device.id, EncryptedRecord.kind == kind)
        )
        if account_id is not None:
            if not re.fullmatch(r"[a-f0-9]{32}", account_id):
                raise HTTPException(422, "Invalid account filter")
            query = query.where(EncryptedRecord.account_id == account_id)
        if device_id is not None:
            if not re.fullmatch(r"[a-f0-9]{32}", device_id):
                raise HTTPException(422, "Invalid device filter")
            query = query.where(EncryptedRecord.device_id == device_id)
        if (
            (start is not None and start < 0)
            or (end is not None and end < 0)
            or (start is not None and end is not None and start > end)
        ):
            raise HTTPException(422, "Invalid capture time range")
        if start is not None:
            query = query.where(EncryptedRecord.captured_at >= start)
        if end is not None:
            query = query.where(EncryptedRecord.captured_at <= end)
        if cursor is not None:
            if not re.fullmatch(r"[0-9]{1,16}:[a-f0-9]{32}", cursor):
                raise HTTPException(422, "Invalid history cursor")
            stamp, ident = cursor.split(":")
            query = query.where(
                or_(
                    EncryptedRecord.captured_at < int(stamp),
                    and_(EncryptedRecord.captured_at == int(stamp), EncryptedRecord.id < ident),
                )
            )
        rows = list(
            db.scalars(
                query.order_by(EncryptedRecord.captured_at.desc(), EncryptedRecord.id.desc()).limit(
                    limit + 1
                )
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "records": [serialize(r) for r in rows],
            "next_cursor": f"{rows[-1].captured_at}:{rows[-1].id}" if has_more else None,
        }

    @app.get("/api/trips")
    def indexed_trips(
        account_id: str,
        start: int = Query(ge=0),
        end: int = Query(ge=0),
        limit: int = Query(default=100, ge=1, le=200),
        include_routes: bool = False,
        device=Depends(approved),
        db: Session = Depends(database),
    ):
        """Returns a member's trips from the trip index, without scanning GPS history."""
        if (
            not re.fullmatch(r"[a-f0-9]{32}", account_id)
            or end < start
            or end - start > 14 * DAY * 1000
        ):
            raise HTTPException(422, "Invalid trip range")
        candidates = db.scalars(
            select(IndexedTrip)
            .join(EncryptedRecord, EncryptedRecord.id == IndexedTrip.event_id)
            .where(
                IndexedTrip.account_id == account_id,
                IndexedTrip.ended_at >= start,
                IndexedTrip.started_at <= end,
                IndexedTrip.status.in_(("ready", "raw")),
                or_(EncryptedRecord.expires_at.is_(None), EncryptedRecord.expires_at > time.time()),
            )
            .order_by(IndexedTrip.ended_at.desc())
            .limit(500)
        ).all()
        rows = [row for row in candidates if trip_visible(db, row, device)][:limit]
        fields = (
            "distance_m",
            "max_speed_mps",
            "samples",
            "trip_id",
            "origin_name",
            "tz",
            "matched",
            "partial",
            "processing",
            "start",
            "end",
            "device_id",
        )
        if include_routes:
            fields += ("route",)
        trips = [json.loads(cipher.decrypt(row.encrypted_trip.encode())) for row in rows]
        arrived = anchor_starts(db, rows, trips, device)
        labels = trip_endpoint_labels(db, rows, trips)
        for event_id, name in arrived.items():
            labels[event_id]["start_label"] = name

        def summary(row, decrypted):
            """Returns one trip in the trip list format."""
            item = dict(
                id=row.event_id,
                started_at=row.started_at,
                ended_at=row.ended_at,
                **{k: v for k, v in decrypted.items() if k in fields},
                **labels[row.event_id],
            )
            if not include_routes:
                route = decrypted.get("route", [])
                if isinstance(route, list) and route:
                    stride = max(1, (len(route) + 78) // 79)
                    preview = route[::stride]
                    if preview[-1] != route[-1]:
                        preview.append(route[-1])
                    item["preview"] = preview
            return item

        return {
            "trips": [summary(row, trip) for row, trip in zip(rows, trips)],
            "processing": trip_processor.route_processing_enabled,
            "road_matching_enabled": bool(trip_processor.roads),
        }

    @app.get("/api/trips/{event_id}")
    def indexed_trip_route(
        event_id: str, device=Depends(approved), db: Session = Depends(database)
    ):
        """Returns the full GPS route of one trip."""
        if not re.fullmatch(r"[a-f0-9]{32}", event_id):
            raise HTTPException(404, "Trip not found")
        row = db.get(IndexedTrip, event_id)
        record = db.get(EncryptedRecord, event_id)
        if (
            not row
            or row.status not in ("ready", "raw")
            or not record
            or not trip_visible(db, row, device)
        ):
            raise HTTPException(404, "Processed trip not available")
        if record.expires_at is not None and record.expires_at <= time.time():
            raise HTTPException(404, "Trip expired")
        trip = json.loads(cipher.decrypt(row.encrypted_trip.encode()))
        if not trip.get("matched") and not trip.get("gps_route"):
            fixes = device_fixes(
                db, row.account_id, row.device_id, row.started_at, row.ended_at, row.trip_id
            )
            kept = normalize_points(fixes)
            route = [[p["lat"], p["lon"]] for p in kept]
            if len(route) >= 2:
                trip.update(
                    route=route,
                    times=[p["time"] for p in kept],
                    start=route[0],
                    end=route[-1],
                    samples=len(route),
                )
                if time.time() - row.ended_at / 1000 > 900:
                    trip["gps_route"] = True
                    row.encrypted_trip = cipher.encrypt(
                        json.dumps(trip, separators=(",", ":")).encode()
                    ).decode()
                    db.commit()
        arrived = anchor_starts(db, [row], [trip], device)
        labels = trip_endpoint_labels(db, [row], [trip])[row.event_id]
        if row.event_id in arrived:
            labels["start_label"] = arrived[row.event_id]
        return trip | labels

    @app.get("/api/view")
    def household_view(device=Depends(approved), db: Session = Depends(database)):
        """Returns every member's latest location, the saved places and profiles, decrypted with
        the server's key and filtered by current sharing settings.
        """
        rows = db.scalars(
            visible_query(db)
            .join(LatestState, LatestState.record_id == EncryptedRecord.id)
            .where(EncryptedRecord.operation == "upsert")
            .order_by(EncryptedRecord.kind, EncryptedRecord.entity_id)
            .limit(256)
        ).all()
        records = []
        senders = {row.device_id for row in rows if row.kind == "location"}
        db.scalars(select(ClientDevice).where(ClientDevice.id.in_(senders))).all()
        db.scalars(select(AlertMemory).where(AlertMemory.device_id.in_(senders))).all()
        last_seen = dict(
            db.execute(
                select(ClientDevice.account_id, func.max(ClientDevice.seen))
                .where(ClientDevice.status == "approved")
                .group_by(ClientDevice.account_id)
            ).all()
        )
        testers = {}
        for row in rows:
            if row.kind == "location" and not location_visible(db, row, device):
                continue
            # On an open demo server, nobody else sees a tester's profile or location.
            if row.account_id != device.account_id:
                if row.account_id not in testers:
                    testers[row.account_id] = review_mode.is_tester(db.get(Account, row.account_id))
                if testers[row.account_id]:
                    continue
            try:
                payload = trip_processor.open_record(json.loads(row.envelope)["body"])
            except (HTTPException, KeyError):
                continue
            item = {
                key: payload[key]
                for key in ("id", "sender", "kind", "entity_id", "operation", "captured_at", "data")
            }
            if row.kind == "location":
                _, memory = alert_memory(db, row.device_id)
                item["still_since"] = memory.get("still_since")
                item["last_contact"] = int(1000 * (last_seen.get(row.account_id) or 0)) or None
            records.append(item)
        return {"revision": db.get(ServiceState, 1).revision, "records": records}

    @app.get("/api/records/{record_id}")
    def get_record(record_id: str, device=Depends(approved), db: Session = Depends(database)):
        """Returns one record if this device is a recipient."""
        record = db.scalar(visible_query(db).where(EncryptedRecord.id == record_id))
        if not record or not available(record, device, db):
            raise HTTPException(404, "Record not available")
        return serialize(record)

    @app.delete("/api/records/mine")
    def erase_own_history(device=Depends(approved), db: Session = Depends(database)):
        """Deletes every location, event and trip record this account has published."""
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.query(PushDelivery).filter(
            PushDelivery.record_id.in_(
                select(EncryptedRecord.id).where(
                    EncryptedRecord.account_id == device.account_id,
                    EncryptedRecord.kind.in_(["location", "event"]),
                )
            )
        ).delete(synchronize_session=False)
        count = (
            db.query(EncryptedRecord)
            .filter(
                EncryptedRecord.account_id == device.account_id,
                EncryptedRecord.kind.in_(["location", "event"]),
            )
            .delete(synchronize_session=False)
        )
        audit(db, "history.deleted", device.account_id)
        db.commit()
        return {"deleted": count}


def trip_point(value):
    """Returns a [lat, lon] pair if it is valid, otherwise None."""
    return (
        [float(value[0]), float(value[1])]
        if isinstance(value, list)
        and len(value) == 2
        and all(type(v) in (int, float) for v in value)
        and -90 <= value[0] <= 90
        and -180 <= value[1] <= 180
        else None
    )


def trip_summary(record, device, meta):
    """Validates a trip summary from a phone and returns the fields the trip list uses."""
    start, end = meta.get("started_at"), meta.get("ended_at")
    trip_id = meta.get("trip_id")
    preview = meta.get("preview") if isinstance(meta.get("preview"), list) else []
    outline = [p for p in map(trip_point, preview[:128]) if p]
    if meta.get("account_id") != device.account_id:
        raise HTTPException(422, "Trip summary account mismatch")
    if (
        type(start) is not int
        or type(end) is not int
        or start <= 0
        or end < start
        or end != record.captured_at
        or end - start > 14 * DAY * 1000
    ):
        raise HTTPException(422, "Trip timestamps rejected")
    if trip_id is not None and (
        not isinstance(trip_id, str)
        or len(trip_id) != 32
        or any(c not in "0123456789abcdef" for c in trip_id)
    ):
        raise HTTPException(422, "Trip identity rejected")

    def number(key, top):
        """Returns a numeric field clamped to 0..top, or 0 if missing or invalid."""
        return min(top, max(0.0, float(meta[key]))) if type(meta.get(key)) in (int, float) else 0.0

    return {
        "id": record.id,
        "account_id": device.account_id,
        "device_id": device.id,
        "started_at": start,
        "ended_at": end,
        "start": trip_point(meta.get("start")) or (outline[0] if outline else None),
        "end": trip_point(meta.get("end")) or (outline[-1] if outline else None),
        "distance_m": round(number("distance_m", 5_000_000.0), 2),
        "max_speed_mps": number("max_speed_mps", 65.0),
        "samples": int(number("samples", 100_000.0)),
        "trip_id": trip_id,
        "origin_name": str(meta["origin_name"])[:80]
        if isinstance(meta.get("origin_name"), str)
        else None,
        "tz": zone_name(meta.get("tz")),
        "route": outline,
        "matched": False,
        "partial": False,
        "processing": False,
    }


def update_latest(db, value, record, latest_state):
    """Points the latest location, place or profile at this record. An older location never
    replaces a newer one; a replaced place or profile record is deleted.
    """
    if latest_state is None:
        db.add(
            LatestState(
                kind=value["kind"],
                entity_id=value["entity_id"],
                record_id=record.id,
                captured_at=value["captured_at"],
            )
        )
    elif value["kind"] != "location" or value["captured_at"] >= latest_state.captured_at:
        old_id = latest_state.record_id
        latest_state.record_id, latest_state.captured_at = record.id, value["captured_at"]
        db.flush()
        if value["kind"] in ("place", "profile"):
            db.query(EncryptedRecord).filter_by(id=old_id).delete(synchronize_session=False)
