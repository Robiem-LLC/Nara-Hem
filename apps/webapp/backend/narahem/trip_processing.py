"""Trusted, local-only trip processing. Never writes plaintext GPS to PostgreSQL.

New signed device records carry a sealed payload for this server. Older records
remain opaque and are NOT silently re-encrypted. The processor private key lives
on the server data volume, separately from database backups.
"""

import base64
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, SealedBox
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from narahem.models import EncryptedRecord, IndexedTrip, LatestState


def meters(a, b):
    """Returns the great-circle distance between two {"lat", "lon"} points in metres."""
    r = 6371008.8
    la1, la2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = la2 - la1, math.radians(b["lon"] - a["lon"])
    term = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(max(0, term))))


def normalize_points(points):
    """Drops unreliable fixes and implausible jumps. Never adds points."""
    output = []
    for p in sorted(points, key=lambda x: x["time"]):
        if (
            p["accuracy"] > 80
            or p["accuracy"] < 0
            or not -90 <= p["lat"] <= 90
            or not -180 <= p["lon"] <= 180
            or not all(math.isfinite(v) for v in (p["lat"], p["lon"], p["accuracy"]))
        ):
            continue
        if not output:
            output.append(p)
            continue
        prev = output[-1]
        dt = (p["time"] - prev["time"]) / 1000
        if dt <= 0:
            continue
        length = meters(prev, p)
        if length > 65 * dt + prev["accuracy"] + p["accuracy"]:
            continue
        if length <= min(15, (prev["accuracy"] + p["accuracy"]) / 2):
            continue
        output.append(p)
    return output


def match_local_roads(fixes, address_override=None, failures=None):
    """Matches fixes to roads with a local OSRM server. GPS is never sent to the internet."""
    geometry = []
    distance_m = 0.0

    def failed(reason):
        """Records why matching failed, if the caller passed a failures list."""
        if failures is not None:
            failures.append(reason)
        return None

    address = (
        address_override
        if address_override is not None
        else os.environ.get("NARAHEM_ROAD_MATCH_URL", "").strip()
    )
    if not address:
        return None
    parsed = urlsplit(address)
    allowed = ("127.0.0.1:5000",) if address_override is not None else ("roadmatcher:5000",)
    if (
        parsed.scheme != "http"
        or parsed.netloc not in allowed
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Road matching must use the internal loopback service")
    if len(fixes) < 3:
        return failed("fewer_than_three_usable_points")
    for begin in range(0, len(fixes) - 1, 89):
        chunk = fixes[begin : begin + 90]
        if len(chunk) < 2:
            continue
        coords = ";".join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in chunk)
        try:
            # Ignore proxy settings so GPS is never sent through an HTTP proxy.
            with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
                response = client.get(
                    f"{address}/match/v1/driving/{coords}",
                    params={
                        "overview": "full",
                        "geometries": "geojson",
                        "steps": "false",
                        "tidy": "true",
                        "timestamps": ";".join(str(p["time"] // 1000) for p in chunk),
                        "radiuses": ";".join(str(min(30, max(5, p["accuracy"]))) for p in chunk),
                    },
                )
            response.raise_for_status()
            reply = response.json()
            matched = reply.get("matchings", [])
            if reply.get("code") != "Ok":
                return failed("osrm_no_matching_route")
            if len(matched) != 1:
                return failed("osrm_route_split_or_ambiguous")
            if float(matched[0].get("confidence", 0)) < 0.65:
                return failed("osrm_low_confidence")
            entry = matched[0]
            points = entry["geometry"]["coordinates"]
            if len(points) < 2 or len(points) > 3000:
                return failed("osrm_geometry_size_out_of_bounds")
            segment = [[float(coord[1]), float(coord[0])] for coord in points]
            if any(not math.isfinite(v) or abs(v) > 180 for item in segment for v in item):
                return failed("osrm_invalid_geometry")
            start = {"lat": segment[0][0], "lon": segment[0][1]}
            end = {"lat": segment[-1][0], "lon": segment[-1][1]}
            if meters(start, chunk[0]) > max(50, chunk[0]["accuracy"] * 3):
                return failed("osrm_start_too_far_from_gps")
            if meters(end, chunk[-1]) > max(50, chunk[-1]["accuracy"] * 3):
                return failed("osrm_end_too_far_from_gps")
            geometry.extend(segment if not geometry else segment[1:])
            distance_m += float(entry["distance"])
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
        ) as error:
            return failed("osrm_request_or_response_" + type(error).__name__)
        if len(geometry) > 8000:
            return failed("osrm_geometry_over_limit")
    return (
        (geometry, distance_m)
        if geometry and math.isfinite(distance_m) and distance_m > 0
        else None
    )


class TripProcessor:
    """Server-side trip handling: decrypts the server's copy of records and (parked) cleans up
    routes.
    """

    def __init__(self, directory):
        """Loads the server's record key, refusing to create a new one for an existing database."""
        path = Path(directory) / "trip-processing.box-key"
        if not path.exists() and (Path(directory) / "trip-processing.created").exists():
            raise RuntimeError("Trip processing private key is missing; restore server data volume")
        if not path.exists():
            value = base64.b64encode(bytes(PrivateKey.generate())).decode()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(value)
            (Path(directory) / "trip-processing.created").touch(mode=0o600)
        raw = base64.b64decode(path.read_text().strip(), validate=True)
        if len(raw) != 32:
            raise RuntimeError("Invalid server trip-processing key")
        self.key = PrivateKey(raw)
        self.public_key = base64.b64encode(bytes(self.key.public_key)).decode()
        # Road matching is parked: no road-cache preparation or OSRM matching.
        self.route_processing_enabled = False
        self.roads = None

    def open_record(self, body):
        """Decrypts the server's copy of a record after checking it matches the signed body."""
        from narahem.data_service import canonical, decode

        try:
            raw = SealedBox(self.key).decrypt(decode(body["server_box"], minimum=48, maximum=18432))
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("domain") != "narahem.payload.v1":
                raise ValueError("Unexpected payload")
            for name in (
                "household",
                "revision",
                "id",
                "sender",
                "sequence",
                "kind",
                "entity_id",
                "operation",
                "replaces",
                "captured_at",
            ):
                if name not in payload or canonical(payload[name]) != canonical(body.get(name)):
                    raise ValueError("Signed context mismatch")
            if not isinstance(payload.get("data"), dict):
                raise ValueError("Invalid record data")
            return payload
        except (
            CryptoError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            raise HTTPException(422, "Invalid authenticated server processing payload") from None

    def process_pending(self, engine, cipher):
        """Normalizes and road-matches finished trips. Parked with road matching, so it returns
        immediately; trips are shown from the phones' summaries.
        """
        if not self.route_processing_enabled:
            return

        # Dormant original implementation, intentionally retained.
        from narahem.data_service import diagnostic

        with Session(engine) as db:
            if self.roads:
                places = []
                for record in db.scalars(
                    select(EncryptedRecord)
                    .join(LatestState, LatestState.record_id == EncryptedRecord.id)
                    .where(LatestState.kind == "place", EncryptedRecord.operation == "upsert")
                ):
                    try:
                        box = json.loads(record.envelope)["body"]
                        if box.get("server_box"):
                            data = self.open_record(box)["data"]
                            if isinstance(data, dict):
                                places.append(data)
                    except (HTTPException, ValueError, KeyError, TypeError):
                        continue
                self.roads.pin_saved_places(places)
                self.roads.cleanup()
            tasks = db.scalars(
                select(IndexedTrip)
                .where(
                    or_(IndexedTrip.status == "pending", IndexedTrip.status == "raw"),
                    IndexedTrip.updated_at <= time.time() - 20,
                )
                .order_by(IndexedTrip.updated_at.asc())
                .limit(3)
            ).all()
            for task in tasks:
                rows = db.scalars(
                    select(EncryptedRecord)
                    .where(
                        EncryptedRecord.kind == "location",
                        EncryptedRecord.account_id == task.account_id,
                        EncryptedRecord.device_id == task.device_id,
                        EncryptedRecord.captured_at >= task.started_at,
                        EncryptedRecord.captured_at <= task.ended_at,
                    )
                    .order_by(EncryptedRecord.captured_at)
                    .limit(1001)
                ).all()
                if len(rows) > 1000:
                    task.status = "partial"
                    task.updated_at = time.time()
                    continue
                fixes = []
                for item in rows:
                    envelope = json.loads(item.envelope)
                    body = envelope["body"]
                    if not body.get("server_box"):
                        continue
                    try:
                        opened = self.open_record(body)
                    except HTTPException:
                        continue
                    data = opened["data"]
                    lat, lon, accuracy = data.get("lat"), data.get("lon"), data.get("accuracy")
                    if any(type(v) not in (int, float) for v in (lat, lon, accuracy)):
                        continue
                    fixes.append(
                        {
                            "lat": float(lat),
                            "lon": float(lon),
                            "accuracy": float(accuracy),
                            "time": item.captured_at,
                            "trip_id": data.get("trip_id"),
                        }
                    )
                if task.trip_id:
                    fixes = [f for f in fixes if f["trip_id"] == task.trip_id]
                normalized = normalize_points(fixes)
                if len(normalized) < 2:
                    task.updated_at = time.time()
                    continue
                distances = [meters(a, b) for a, b in zip(normalized, normalized[1:])]
                length = sum(distances)
                if not math.isfinite(length):
                    continue
                event = db.get(EncryptedRecord, task.event_id)
                if event is None:
                    continue
                try:
                    summary = self.open_record(json.loads(event.envelope)["body"])["data"]
                except HTTPException:
                    continue
                road = None
                if task.status == "raw" and self.roads:
                    address = self.roads.ready_for(normalized)
                    failures = []
                    if address:
                        road = match_local_roads(
                            normalized, address_override=address, failures=failures
                        )
                        if failures:
                            self.roads.last_error = failures[-1]
                    reason = (
                        failures[-1] if failures else self.roads.last_error
                    ) or "road_map_not_ready"
                    if not reason.isidentifier() or len(reason) > 80:
                        reason = "road_graph_preparation_failed"
                    diagnostic(
                        db,
                        "trip",
                        "trip.road_match",
                        task.account_id,
                        task.device_id,
                        outcome="ok" if road else "pending",
                        reason="osrm_matched" if road else reason,
                        received_points=len(fixes),
                        accepted_points=len(normalized),
                        matched=bool(road),
                    )
                    if not road:
                        task.updated_at = time.time() + 600
                        db.commit()
                        continue
                route = road[0] if road else [[p["lat"], p["lon"]] for p in normalized]
                if road:
                    length = road[1]
                data = {
                    "id": task.event_id,
                    "account_id": task.account_id,
                    "device_id": task.device_id,
                    "started_at": task.started_at,
                    "ended_at": task.ended_at,
                    "start": route[0],
                    "end": route[-1],
                    "distance_m": round(length, 2),
                    "max_speed_mps": min(65.0, max(0.0, float(summary.get("max_speed_mps", 0)))),
                    "samples": len(normalized),
                    "trip_id": task.trip_id,
                    "origin_name": str(summary["origin_name"])[:80]
                    if isinstance(summary.get("origin_name"), str)
                    else None,
                    "route": route,
                    "matched": bool(road),
                    "partial": len(fixes) < 3,
                    "processing": bool(self.roads and not road),
                }
                task.encrypted_trip = cipher.encrypt(
                    json.dumps(data, separators=(",", ":")).encode()
                ).decode()
                task.status = "ready" if road or not self.roads else "raw"
                task.updated_at = time.time()
            db.commit()
        if self.roads:
            self.roads.prepare_one_pinned()
