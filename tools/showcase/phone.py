"""A simulated family phone for the showcase household.

It enrolls by emailed code and publishes end-to-end encrypted records exactly as the apps do.
"""

import base64
import math
import secrets
import time

import httpx
from household import B64, meters  # also puts the backend on the import path
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey

from narahem.data_service import canonical


class FakePhone:
    """A simulated phone for the showcase: enrolls by emailed code and publishes encrypted
    records like the real apps.
    """

    def __init__(self, server, account_id, email, name, password, platform="ios"):
        """Generates keys, signs in and enrolls the phone."""
        self.server, self.account_id, self.name = server, account_id, name
        self.signing, self.box = SigningKey.generate(), PrivateKey.generate()
        self.id = secrets.token_hex(16)
        self.session = server.client()
        login = self.session.post("/api/login", json={"email": email, "password": password})
        login.raise_for_status()
        self.session.headers["X-CSRF-Token"] = login.json()["csrf"]
        household, _ = server.state()
        registration = {
            "domain": "narahem.device.v1",
            "household": household,
            "id": self.id,
            "account_id": account_id,
            "signing_key": B64(self.signing.verify_key),
            "box_key": B64(self.box.public_key),
            "platform": platform,
        }
        response = self.session.post(
            "/api/devices/register",
            json={
                "id": self.id,
                "name": "iPhone" if platform == "ios" else "Android phone",
                "platform": platform,
                "signing_key": registration["signing_key"],
                "box_key": registration["box_key"],
                "signature": B64(self.signing.sign(canonical(registration)).signature),
            },
        )
        response.raise_for_status()
        self.credential = response.json()["credential"]
        sent = len(server.mail)
        self.session.post("/api/phones/code", json={"device_id": self.id}).raise_for_status()
        code = server.code_for(email, sent, timeout=10)
        self.session.post(
            "/api/phones/verify", json={"device_id": self.id, "code": code}
        ).raise_for_status()
        self.device = httpx.Client(
            base_url=server.origin,
            headers={"Origin": server.origin, "Authorization": "Bearer " + self.credential},
            timeout=30,
        )
        self.sequence = self.device.get("/api/device").json()["sequence"]
        self.viewers = set()

    def share_with(self, account_ids):
        """Sets which accounts can see this phone's location."""
        self.viewers = set(account_ids)
        self.device.put(
            "/api/sharing/audience", json={"account_ids": sorted(self.viewers)}
        ).raise_for_status()

    def publish(self, kind, entity, data, captured_at=None, replaces=None):
        """Encrypts and signs a record for its recipients and uploads it."""
        household, revision = self.server.state()
        self.sequence += 1
        body = {
            "domain": "narahem.record.v1",
            "household": household,
            "revision": revision,
            "id": secrets.token_hex(16),
            "sender": self.id,
            "sequence": self.sequence,
            "kind": kind,
            "entity_id": entity,
            "operation": "upsert",
            "replaces": replaces,
            "captured_at": captured_at or int(time.time() * 1000),
        }
        targets = (
            self.server.recipients_for(self.account_id, self.viewers)
            if kind in ("location", "event")
            else self.server.all_devices()
        )
        payload = dict(body, domain="narahem.payload.v1", data=data)
        sealed = canonical(payload)
        body["recipients"] = sorted(
            (
                {
                    "device_id": device_id,
                    "box": B64(SealedBox(PublicKey(base64.b64decode(key))).encrypt(sealed)),
                }
                for device_id, key in targets
            ),
            key=lambda r: r["device_id"],
        )
        server_key = self.server.app.state.trip_processor.public_key
        body["server_box"] = B64(SealedBox(PublicKey(base64.b64decode(server_key))).encrypt(sealed))
        headers = {}
        if kind == "place":
            headers["X-Places-State"] = self.device.get("/api/places/manifest").json()["token"]
        envelope = {"body": body, "signature": B64(self.signing.sign(canonical(body)).signature)}
        response = self.device.post("/api/records", json=envelope, headers=headers)
        if response.status_code != 201:
            raise RuntimeError(
                f"{self.name}: {kind} rejected ({response.status_code}): {response.text}"
            )
        return body["id"]

    def profile(self, photo):
        """Publishes the member's name and photo."""
        self.publish("profile", self.account_id, {"name": self.name, "photo": photo})

    def location(self, lat, lon, at=None, speed=None, battery=None, trip_id=None):
        """Publishes a location."""
        data = {"lat": round(lat, 6), "lon": round(lon, 6), "accuracy": 8.0}
        if speed is not None:
            data["speed_mps"] = round(speed, 2)
        if battery is not None:
            data.update(battery_pct=battery, charging=False)
        if trip_id:
            data["trip_id"] = trip_id
        self.publish("location", self.account_id, data, captured_at=at)

    def place(self, name, lat, lon, radius=120):
        """Publishes a saved place."""
        self.publish(
            "place",
            secrets.token_hex(16),
            {"name": name, "lat": lat, "lon": lon, "radius": radius, "alerts": []},
        )

    def trip(self, path, started_at, ended_at, origin_name=None):
        """Publishes a trip's GPS fixes and then its summary."""
        trip_id = secrets.token_hex(16)
        lengths = [meters(a, b) for a, b in zip(path, path[1:])]
        distance = sum(lengths)
        # Slow near the ends, city speed in the middle: time per segment follows that profile,
        # then the whole trip is stretched to take exactly ended_at - started_at.
        pace = [
            length / (4 + 12 * math.sin(math.pi * (i + 0.5) / len(lengths)))
            for i, length in enumerate(lengths)
        ]
        scale = (ended_at - started_at) / 1000 / (sum(pace) or 1)
        at, speeds = started_at, [0.0]
        self.location(*path[0], at=int(at), speed=0, trip_id=trip_id)
        for (lat, lon), length, seconds in zip(path[1:], lengths, pace):
            at += seconds * scale * 1000
            speeds.append(length / (seconds * scale) if seconds else 0)
            self.location(lat, lon, at=int(at), speed=speeds[-1], trip_id=trip_id)
        outline = (
            path if len(path) <= 160 else [path[i * (len(path) - 1) // 159] for i in range(160)]
        )
        data = {
            "type": "trip_summary",
            "account_id": self.account_id,
            "started_at": int(started_at),
            "ended_at": int(ended_at),
            "max_speed_mps": round(max(speeds), 2),
            "distance_m": round(distance),
            "samples": len(path),
            "trip_id": trip_id,
            "start": list(path[0]),
            "end": list(path[-1]),
            "preview": [list(p) for p in outline],
        }
        if origin_name:
            data["origin_name"] = origin_name
        self.publish("event", secrets.token_hex(16), data, captured_at=int(ended_at))
