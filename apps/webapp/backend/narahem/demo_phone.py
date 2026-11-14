"""A simulated phone for the demo family (see demo_family.py).

It signs in, enrolls and publishes signed, end-to-end encrypted records exactly as the apps do,
over the demo stack's own network. Its keys are kept in the demo family's state file, so the
same phone carries on after a restart.
"""

import base64
import math
import secrets
import time

import httpx
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem.app import trusted_accounts
from narahem.data_service import canonical
from narahem.models import Account, ClientDevice, ServiceState


def b64(value):
    """Returns bytes as standard base64 text."""
    return base64.b64encode(bytes(value)).decode()


def meters(a, b):
    """Returns the distance between two (lat, lon) points in metres."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 12_742_000 * math.asin(math.sqrt(h))


class Server:
    """The demo server: reached over the stack network, its database read directly."""

    def __init__(self, engine, address, public_url):
        """Talks to the server at address while naming it by its public URL, as a tunnel does."""
        self.engine, self.address, self.public_url = engine, address.rstrip("/"), public_url
        self.host = public_url.split("://", 1)[1]

    def client(self, token=None):
        """Returns an HTTP client, signed in with a bearer token if one is given."""
        headers = {"Host": self.host, "Origin": self.public_url}
        if token:
            headers["Authorization"] = "Bearer " + token
        return httpx.Client(base_url=self.address, headers=headers, timeout=30)

    def state(self):
        """Returns the household ID and roster revision."""
        with Session(self.engine) as db:
            state = db.get(ServiceState, 1)
            return state.household_id, state.revision

    def devices(self, account_id=None, viewers=None):
        """Returns (id, box key) for the approved devices a record must be sealed for: all of
        them, or only the sender's own and its viewers' when account_id is given.
        """
        with Session(self.engine) as db:
            rows = db.scalars(
                select(ClientDevice)
                .join(Account, Account.id == ClientDevice.account_id)
                .where(
                    ClientDevice.status == "approved",
                    Account.status == "active",
                    trusted_accounts(),
                )
                .order_by(ClientDevice.id)
            )
            return [
                (d.id, d.box_key)
                for d in rows
                if account_id is None or d.account_id == account_id or d.account_id in viewers
            ]


class DemoPhone:
    """One family member's phone."""

    def __init__(self, server, account_id, name, saved):
        """Restores the phone from its saved keys and credential."""
        self.server, self.account_id, self.name = server, account_id, name
        self.signing = SigningKey(base64.b64decode(saved["signing"]))
        self.box = PrivateKey(base64.b64decode(saved["box"]))
        self.id, self.credential = saved["id"], saved["credential"]
        self.device = server.client(self.credential)
        current = self.device.get("/api/device")
        current.raise_for_status()
        if current.json()["status"] != "approved":
            raise PermissionError(f"{name}'s demo phone is no longer approved")
        self.sequence = current.json()["sequence"]
        self.server_key = current.json()["trip_processing_key"]
        self.viewers = set()

    @classmethod
    def enroll(cls, server, account_id, name, login, password, code, platform):
        """Registers a new phone for the account and approves it with the review code. Returns
        the phone and what to save to restore it.
        """
        signing, box = SigningKey.generate(), PrivateKey.generate()
        device_id = secrets.token_hex(16)
        session = server.client()
        signed_in = session.post(
            "/api/login", json={"email": login, "password": password, "native": True}
        )
        signed_in.raise_for_status()
        session = server.client(signed_in.json()["access_token"])
        household, _ = server.state()
        registration = {
            "domain": "narahem.device.v1",
            "household": household,
            "id": device_id,
            "account_id": account_id,
            "signing_key": b64(signing.verify_key),
            "box_key": b64(box.public_key),
            "platform": platform,
        }
        registered = session.post(
            "/api/devices/register",
            json={
                "id": device_id,
                "name": "iPhone" if platform == "ios" else "Android phone",
                "platform": platform,
                "signing_key": registration["signing_key"],
                "box_key": registration["box_key"],
                "signature": b64(signing.sign(canonical(registration)).signature),
            },
        )
        registered.raise_for_status()
        asked = session.post("/api/phones/code", json={"device_id": device_id})
        if asked.status_code != 202:
            raise RuntimeError(
                f"{name}'s phone could not get a code ({asked.status_code}: {asked.text}). "
                "Is the server in review mode for the demo family's addresses?"
            )
        session.post(
            "/api/phones/verify", json={"device_id": device_id, "code": code}
        ).raise_for_status()
        saved = {
            "id": device_id,
            "signing": b64(signing.encode()),
            "box": b64(box.encode()),
            "credential": registered.json()["credential"],
        }
        return cls(server, account_id, name, saved), saved

    def share_with(self, account_ids):
        """Sets which accounts can see this phone's location."""
        self.viewers = set(account_ids)
        self.device.put(
            "/api/sharing/audience", json={"account_ids": sorted(self.viewers)}
        ).raise_for_status()

    def publish(self, kind, entity, data, captured_at=None, replaces=None):
        """Seals and signs a record for its recipients and uploads it."""
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
            self.server.devices(self.account_id, self.viewers)
            if kind in ("location", "event")
            else self.server.devices()
        )
        sealed = canonical(dict(body, domain="narahem.payload.v1", data=data))
        body["recipients"] = sorted(
            (
                {
                    "device_id": device_id,
                    "box": b64(SealedBox(PublicKey(base64.b64decode(key))).encrypt(sealed)),
                }
                for device_id, key in targets
            ),
            key=lambda r: r["device_id"],
        )
        server_key = PublicKey(base64.b64decode(self.server_key))
        body["server_box"] = b64(SealedBox(server_key).encrypt(sealed))
        headers = {}
        if kind == "place":
            headers["X-Places-State"] = self.device.get("/api/places/manifest").json()["token"]
        envelope = {"body": body, "signature": b64(self.signing.sign(canonical(body)).signature)}
        response = self.device.post("/api/records", json=envelope, headers=headers)
        if response.status_code != 201:
            raise RuntimeError(f"{self.name}: {kind} refused ({response.status_code})")

    def profile(self, photo):
        """Publishes the member's name and photo."""
        current = self.device.get("/api/profile/current").json()["replaces"]
        self.publish(
            "profile", self.account_id, {"name": self.name, "photo": photo}, replaces=current
        )

    def location(self, lat, lon, at=None, speed=None, battery=None, trip_id=None):
        """Publishes a position."""
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

    def summary(self, trip_id, path, started_at, ended_at, top_speed, origin_name=None):
        """Publishes the summary that closes a trip."""
        outline = (
            path if len(path) <= 160 else [path[i * (len(path) - 1) // 159] for i in range(160)]
        )
        data = {
            "type": "trip_summary",
            "account_id": self.account_id,
            "started_at": int(started_at),
            "ended_at": int(ended_at),
            "max_speed_mps": round(top_speed, 2),
            "distance_m": round(sum(meters(a, b) for a, b in zip(path, path[1:]))),
            "samples": len(path),
            "trip_id": trip_id,
            "start": list(path[0]),
            "end": list(path[-1]),
            "preview": [list(p) for p in outline],
        }
        if origin_name:
            data["origin_name"] = origin_name
        self.publish("event", secrets.token_hex(16), data, captured_at=int(ended_at))

    def drive(self, path, started_at, ended_at, origin_name=None, wait=None, battery=None):
        """Publishes a trip along path. With wait, each fix is sent when it happens, as a phone
        in a moving car does; without it the whole trip is published at once, back-dated.
        """
        trip_id = secrets.token_hex(16)
        lengths = [meters(a, b) for a, b in zip(path, path[1:])]
        # Slow near the ends and city speed in the middle, stretched to the trip's length.
        pace = [
            length / (4 + 12 * math.sin(math.pi * (i + 0.5) / len(lengths)))
            for i, length in enumerate(lengths)
        ]
        scale = (ended_at - started_at) / 1000 / (sum(pace) or 1)
        at, top = started_at, 0.0
        self.location(*path[0], at=int(at), speed=0, battery=battery, trip_id=trip_id)
        for (lat, lon), length, seconds in zip(path[1:], lengths, pace):
            at += seconds * scale * 1000
            speed = length / (seconds * scale) if seconds else 0
            top = max(top, speed)
            if wait:
                wait(max(0, at / 1000 - time.time()))
                at = time.time() * 1000
            self.location(lat, lon, at=int(at), speed=speed, battery=battery, trip_id=trip_id)
        self.summary(trip_id, path, started_at, at, top, origin_name)
