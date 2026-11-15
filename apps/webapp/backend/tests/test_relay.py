import base64
import copy
import json
import secrets
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem.app import HASHER, create_app, digest
from narahem.data_service import canonical, diagnostic
from narahem.models import (
    Account,
    AuditEntry,
    Challenge,
    ClientDevice,
    DiagnosticEntry,
    EncryptedRecord,
    LatestState,
    LoginSession,
    Outbox,
    PushDelivery,
    PushSubscription,
    RecordRecipient,
    RosterRevision,
    ServiceState,
)
from tests import test_setup


def B64(x):
    return base64.b64encode(bytes(x)).decode()


class RelayTests(unittest.TestCase):
    tearDown = test_setup.SetupTests.tearDown
    setup_owner = test_setup.SetupTests.setup_owner
    login = test_setup.SetupTests.login
    configure = test_setup.SetupTests.configure

    def setUp(self):
        self.start()

    def start(self):
        test_setup.SetupTests.setUp(self)
        self.configure()
        with Session(self.app.state.engine) as db:
            owner = db.scalar(select(Account).where(Account.email == test_setup.OWNER))
            owner.verified = True
            self.owner_id = owner.id
            self.household = db.get(ServiceState, 1).household_id
            db.commit()
        self.devices = []

    def register(self, client=None, account=None):
        signing, box = SigningKey.generate(), PrivateKey.generate()
        d = dict(
            id=secrets.token_hex(16),
            account_id=account or self.owner_id,
            signing_key=B64(signing.verify_key),
            box_key=B64(box.public_key),
            signing=signing,
            box=box,
        )
        body = dict(domain="narahem.device.v1", household=self.household, **self.identity(d))
        response = (client or self.client).post(
            "/api/devices/register",
            json=dict(
                id=d["id"],
                name="Synthetic device",
                signing_key=d["signing_key"],
                box_key=d["box_key"],
                signature=B64(signing.sign(canonical(body)).signature),
            ),
        )
        self.assertEqual(response.status_code, 201, response.text)
        d["credential"] = response.json()["credential"]
        self.devices.append(d)
        return d

    def identity(self, d):
        return {k: d[k] for k in ("id", "account_id", "signing_key", "box_key")}

    def call(self, d, method, path, body=None, headers=None):
        kwargs = dict(headers={"Authorization": f"Bearer {d['credential']}"})
        if body is not None:
            kwargs["json"] = body
        if (
            path == "/api/records"
            and method == "POST"
            and body
            and body.get("body", {}).get("kind") == "place"
        ):
            response = self.client.get("/api/places/manifest", headers=kwargs["headers"])
            if response.status_code == 200:
                kwargs["headers"]["X-Places-State"] = response.json()["token"]
        if headers:
            kwargs["headers"].update(headers)
        return self.client.request(method, path, **kwargs)

    def roster(self, signer, devices, token=None):
        with Session(self.app.state.engine) as db:
            state = db.get(ServiceState, 1)
            old = db.get(RosterRevision, state.revision)
            body = dict(
                domain="narahem.roster.v1",
                household=self.household,
                revision=state.revision + 1,
                previous=old.hash if old else "",
                signer=signer["id"],
                devices=sorted([self.identity(d) for d in devices], key=lambda d: d["id"]),
                issued_at=int(time.time()),
            )
        return dict(
            body=body,
            signature=B64(signer["signing"].sign(canonical(body)).signature),
            bootstrap_token=token,
        )

    def bootstrap(self):
        d = self.register()
        body = self.roster(d, [d], (self.path / "device-bootstrap-token").read_text())
        result = self.call(d, "POST", "/api/roster", body)
        self.assertEqual(result.status_code, 200, result.text)
        return d

    def pair(self):
        a = self.bootstrap()
        b = self.register()
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b])).status_code, 200
        )
        return a, b

    def record(
        self,
        d,
        kind="location",
        data=None,
        captured=None,
        sequence=None,
        recipients=None,
        entity=None,
        operation="upsert",
        replaces="auto",
        notify=False,
        server=True,
    ):
        with Session(self.app.state.engine) as db:
            state = db.get(ServiceState, 1)
            device = db.get(ClientDevice, d["id"])
            all_devices = list(
                db.scalars(select(ClientDevice).where(ClientDevice.status == "approved"))
            )
            entity = entity or (
                d["account_id"] if kind in ("location", "profile") else secrets.token_hex(16)
            )
            latest = db.get(LatestState, (kind, entity))
            previous = latest.record_id if latest and kind in ("place", "profile") else None
            body = dict(
                domain="narahem.record.v1",
                household=self.household,
                revision=state.revision,
                id=secrets.token_hex(16),
                sender=d["id"],
                sequence=sequence or device.last_sequence + 1,
                kind=kind,
                entity_id=entity,
                operation=operation,
                replaces=previous if replaces == "auto" else replaces,
                captured_at=captured or int(time.time() * 1000),
            )
            if kind in ("location", "event") and recipients is None:
                all_devices = [
                    v
                    for v in all_devices
                    if v.account_id == d["account_id"]
                    or db.get(Account, v.account_id).role != "admin"
                ]
            targets = (
                [
                    {k: getattr(v, k) for k in ("id", "account_id", "signing_key", "box_key")}
                    for v in all_devices
                ]
                if recipients is None
                else [self.identity(v) for v in recipients]
            )
        payload = dict(
            body,
            domain="narahem.payload.v1",
            data=data or {"lat": 12.3456789, "lon": -23.4567891, "accuracy": 5},
        )
        body["recipients"] = sorted(
            [
                dict(
                    device_id=r["id"],
                    box=B64(
                        SealedBox(PublicKey(base64.b64decode(r["box_key"]))).encrypt(
                            canonical(payload)
                        )
                    ),
                )
                for r in targets
            ],
            key=lambda r: r["device_id"],
        )
        if server and (operation == "upsert" or kind == "place"):
            # Phones also seal every record for the server, which serves it to allowed devices.
            key = self.app.state.trip_processor.public_key
            body["server_box"] = B64(
                SealedBox(PublicKey(base64.b64decode(key))).encrypt(canonical(payload))
            )
        signed = dict(body=body, signature=B64(d["signing"].sign(canonical(body)).signature))
        if notify:
            signed["notify"] = True
        return signed

    def publish(self, d, **kwargs):
        body = self.record(d, **kwargs)
        r = self.call(d, "POST", "/api/records", body)
        self.assertEqual(r.status_code, 201, r.text)
        return body

    def decrypt(self, d, envelope):
        sender = next(x for x in self.devices if x["id"] == envelope["body"]["sender"])
        sender["signing"].verify_key.verify(
            canonical(envelope["body"]), base64.b64decode(envelope["signature"])
        )
        box = next(x["box"] for x in envelope["body"]["recipients"] if x["device_id"] == d["id"])
        return json.loads(SealedBox(d["box"]).decrypt(base64.b64decode(box)))

    def test_signed_location_batch_uses_normal_authorization_and_idempotency(self):
        owner = self.bootstrap()
        sequence = self.call(owner, "GET", "/api/device").json()["sequence"]
        first = self.record(owner, sequence=sequence + 1)
        second = self.record(owner, sequence=sequence + 2)
        payload = {"records": [first, second]}
        result = self.call(owner, "POST", "/api/records/batch", payload)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(len(result.json()["records"]), 2)
        again = self.call(owner, "POST", "/api/records/batch", payload)
        self.assertEqual(again.status_code, 201, again.text)
        self.assertTrue(all(item["duplicate"] for item in again.json()["records"]))
        self.assertEqual(self.client.post("/api/records/batch", json=payload).status_code, 401)
        self.assertEqual(
            self.call(owner, "POST", "/api/records/batch", {"records": []}).status_code, 422
        )
        self.assertIn(
            self.call(
                owner, "POST", "/api/records/batch", {"records": [payload["records"][0]] * 13}
            ).status_code,
            (413, 422),
        )

    def test_realistic_multi_device_batch_is_not_rejected_for_size(self):
        # Eight fixes sealed for five devices exceed the generic 8 KiB request limit.
        owner = self.bootstrap()
        others = [self.register() for _ in range(4)]
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, *others])
            ).status_code,
            200,
        )
        sequence = self.call(owner, "GET", "/api/device").json()["sequence"]
        data = {
            "lat": 40.712812345678,
            "lon": -74.006012345678,
            "accuracy": 12.5,
            "speed_mps": 13.41,
            "battery_pct": 87,
            "charging": False,
            "trip_id": secrets.token_hex(16),
        }
        payload = {
            "records": [self.record(owner, data=data, sequence=sequence + n) for n in range(1, 9)]
        }
        self.assertGreater(len(json.dumps(payload)), 8192)
        result = self.call(owner, "POST", "/api/records/batch", payload)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(len(result.json()["records"]), 8)

    def test_trip_summary_with_full_route_outline_is_accepted(self):
        # iOS sends up to ~128 full-precision outline points; that exceeded the old 2 KiB limit.
        owner = self.bootstrap()
        outline = [[40.71281234567891 + i / 1e4, -74.00601234567891 - i / 1e4] for i in range(128)]
        now = int(time.time() * 1000)
        data = {
            "type": "trip_summary",
            "account_id": owner["account_id"],
            "started_at": now - 600000,
            "ended_at": now,
            "distance_m": 11425.7,
            "max_speed_mps": 28.2,
            "samples": 103,
            "trip_id": secrets.token_hex(16),
            "start": outline[0],
            "end": outline[-1],
            "preview": outline,
        }
        trip = self.record(owner, kind="event", data=data, captured=now)
        self.assertGreater(len(base64.b64decode(trip["body"]["recipients"][0]["box"])), 2048)
        result = self.call(owner, "POST", "/api/records", trip)
        self.assertEqual(result.status_code, 201, result.text)
        # Locations keep the smaller limit.
        oversized = self.record(
            owner, data={"lat": 1.0, "lon": 1.0, "accuracy": 5, "padding": "x" * 3000}
        )
        self.assertEqual(self.call(owner, "POST", "/api/records", oversized).status_code, 422)

    def server_sealed(self, d, record, data):
        """Also seal a record for the server, as phones do in server mode."""
        key = self.call(d, "GET", "/api/device").json()["trip_processing_key"]
        plain = dict(record["body"], domain="narahem.payload.v1", data=data)
        record["body"]["server_box"] = B64(
            SealedBox(PublicKey(base64.b64decode(key))).encrypt(canonical(plain))
        )
        record["signature"] = B64(d["signing"].sign(canonical(record["body"])).signature)
        return record

    def test_server_mode_serves_trips_to_devices_approved_later_from_their_join_day(self):
        from narahem.models import AccountApproval

        owner = self.bootstrap()
        subject_id, subject_client = self.second_member("subject@example.invalid", "subject")
        subject = self.register(subject_client, subject_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, subject])
            ).status_code,
            200,
        )
        captured = int(time.time() * 1000) - 3_600_000
        trip = {
            "type": "trip_summary",
            "account_id": subject_id,
            "started_at": captured - 600000,
            "ended_at": captured,
            "distance_m": 5000,
            "max_speed_mps": 20,
            "samples": 30,
            "preview": [[40.0, -74.0], [40.01, -74.0]],
        }
        event = self.server_sealed(
            subject, self.record(subject, kind="event", data=trip, captured=captured), trip
        )
        self.assertEqual(self.call(subject, "POST", "/api/records", event).status_code, 201)
        # A member approved later gets the trip from the server's database, not from a phone.
        viewer_id, viewer_client = self.second_member("viewer@example.invalid", "viewer")

        def joined(at):
            with Session(self.app.state.engine) as db:
                approval = db.get(AccountApproval, viewer_id)
                if approval is None:
                    db.add(
                        AccountApproval(account_id=viewer_id, approved_by=self.owner_id, created=at)
                    )
                else:
                    approval.created = at
                db.commit()

        joined(time.time() - 3 * 86400)
        viewer = self.register(viewer_client, viewer_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, subject, viewer])
            ).status_code,
            200,
        )
        url = f"/api/trips?account_id={subject_id}&start={captured - 700000}&end={captured + 1000}"
        listed = self.call(viewer, "GET", url).json()
        self.assertEqual([t["id"] for t in listed["trips"]], [event["body"]["id"]])
        self.assertEqual(
            listed["trips"][0]["route"]
            if "route" in listed["trips"][0]
            else listed["trips"][0]["preview"],
            [[40.0, -74.0], [40.01, -74.0]],
        )
        self.assertEqual(
            self.call(viewer, "GET", "/api/trips/" + event["body"]["id"]).status_code, 200
        )
        # ...but nothing from before the day their account joined.
        joined(time.time() + 2 * 86400)
        self.assertEqual(self.call(viewer, "GET", url).json()["trips"], [])
        self.assertEqual(
            self.call(viewer, "GET", "/api/trips/" + event["body"]["id"]).status_code, 404
        )

    def test_sharing_again_shows_past_trips_back_to_the_join_day(self):
        # Intended: sharing is about who may look now. Someone added back sees the member's
        # earlier trips again, but never from before the day their own account joined.
        from narahem.models import AccountApproval

        owner = self.bootstrap()
        subject_id, subject_client = self.second_member("subject@example.invalid", "subject")
        viewer_id, viewer_client = self.second_member("viewer@example.invalid", "viewer")
        with Session(self.app.state.engine) as db:
            approval = db.get(AccountApproval, viewer_id)
            if approval is None:
                approval = AccountApproval(account_id=viewer_id, approved_by=self.owner_id)
                db.add(approval)
            approval.created = time.time() - 3 * 86400
            db.commit()
        subject = self.register(subject_client, subject_id)
        viewer = self.register(viewer_client, viewer_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, subject, viewer])
            ).status_code,
            200,
        )
        captured = int(time.time() * 1000) - 2 * 86_400_000
        trip = {
            "type": "trip_summary",
            "account_id": subject_id,
            "started_at": captured - 600000,
            "ended_at": captured,
            "distance_m": 5000,
            "max_speed_mps": 20,
            "samples": 30,
            "preview": [[40.0, -74.0], [40.01, -74.0]],
        }
        event = self.server_sealed(
            subject, self.record(subject, kind="event", data=trip, captured=captured), trip
        )
        self.assertEqual(self.call(subject, "POST", "/api/records", event).status_code, 201)
        url = "/api/trips/" + event["body"]["id"]

        def share_with(ids):
            reply = self.call(subject, "PUT", "/api/sharing/audience", {"account_ids": ids})
            self.assertEqual(reply.status_code, 200)

        self.assertEqual(self.call(viewer, "GET", url).status_code, 200)
        share_with([])
        self.assertEqual(self.call(viewer, "GET", url).status_code, 404)
        share_with([viewer_id])
        self.assertEqual(self.call(viewer, "GET", url).status_code, 200)

    def test_server_decides_household_alerts_and_serves_their_text(self):
        from narahem.models import PushDelivery

        owner = self.bootstrap()
        subject_id, subject_client = self.second_member("subject@example.invalid", "Sam")
        viewer_id, viewer_client = self.second_member("viewer@example.invalid", "Vic")
        subject, viewer = (
            self.register(subject_client, subject_id),
            self.register(viewer_client, viewer_id),
        )
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, subject, viewer])
            ).status_code,
            200,
        )
        self.publish(
            owner, kind="place", data={"name": "Home", "lat": 40.0, "lon": -74.0, "radius": 100}
        )
        for d in (subject, viewer):
            reply = self.call(
                d,
                "PUT",
                "/api/push/subscription",
                {"provider": "fcm", "token": "synthetic-fcm-token-" + d["id"][:8]},
            )
            self.assertEqual(reply.json(), {"registered": True})

        def pushes(d):
            with Session(self.app.state.engine) as db:
                return db.query(PushDelivery).filter_by(device_id=d["id"]).count()

        def feed(d):
            return [a["text"] for a in self.call(d, "GET", "/api/alerts").json()["alerts"]]

        now = int(time.time() * 1000)
        trip = secrets.token_hex(16)
        self.publish(
            subject, captured=now - 120000, data={"lat": 40.0, "lon": -74.0, "accuracy": 10}
        )
        self.publish(
            subject, captured=now - 110000, data={"lat": 40.0003, "lon": -74.0, "accuracy": 10}
        )
        self.assertEqual(feed(viewer), [], "drift inside the place is quiet")
        self.publish(
            subject,
            captured=now - 100000,
            data={"lat": 40.01, "lon": -74.0, "accuracy": 10, "trip_id": trip},
        )
        self.assertEqual(feed(viewer), ["Sam left Home"])
        self.assertEqual(pushes(viewer), 1)
        self.assertEqual(
            (feed(subject), pushes(subject)), ([], 0), "nobody is alerted about themselves"
        )
        # An older fix uploaded late does not undo what the server already saw.
        self.publish(
            subject, captured=now - 115000, data={"lat": 40.0, "lon": -74.0, "accuracy": 10}
        )
        # The drive ends somewhere unsaved: the server looks up the address, then pushes.
        summary = {
            "type": "trip_summary",
            "account_id": subject_id,
            "started_at": now - 100000,
            "ended_at": now - 1000,
            "trip_id": trip,
            "distance_m": 5000,
            "max_speed_mps": 20,
            "samples": 40,
            "end": [40.05, -74.0],
            "preview": [[40.01, -74.0], [40.05, -74.0]],
        }
        self.publish(subject, kind="event", captured=now - 1000, data=summary)
        self.assertEqual(feed(viewer), ["Sam left Home"])
        with patch(
            "narahem.household_alerts.lookup_address", return_value="Near 12 Main St, Springfield"
        ) as lookup:
            self.app.state.maintenance()
            self.assertEqual(
                feed(viewer), ["Sam left Home"], "two minutes to report reaching a saved place"
            )
            later = time.time() + 130
            with patch("time.time", return_value=later):
                self.app.state.maintenance()
        lookup.assert_called_once()
        self.assertEqual(
            feed(viewer),
            [
                "Sam left Home",
                "Sam arrived at near 12 Main St, Springfield after a 3.1 mile drive, top speed 45 "
                "mph",
            ],
        )
        self.assertEqual(pushes(viewer), 2)
        # The member's sharing choice applies to alerts too.
        self.assertEqual(
            self.call(subject, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        self.assertEqual(feed(viewer), [])
        self.assertEqual(self.client.get("/api/alerts").status_code, 401)

    def test_server_names_where_trips_start_and_end_for_every_app(self):
        a, b = self.alert_pair()
        now = int(time.time() * 1000)
        start, end = now - 20 * 60000, now - 10 * 60000
        # The recorded end stops ~170 m short of home; a fix a minute later is inside it.
        self.publish(a, captured=end + 60000, data={"lat": 40.0001, "lon": -74.0, "accuracy": 10})
        summary = {
            "type": "trip_summary",
            "account_id": a["account_id"],
            "started_at": start,
            "ended_at": end,
            "trip_id": secrets.token_hex(16),
            "distance_m": 3000,
            "max_speed_mps": 15,
            "samples": 30,
            "start": [40.03, -74.0],
            "end": [40.0015, -74.0],
        }
        trip = self.publish(a, kind="event", captured=end, data=summary)["body"]["id"]
        url = f"/api/trips?account_id={a['account_id']}&start={start - 1000}&end={end + 1000}"

        def listed():
            return self.call(b, "GET", url).json()["trips"][0]

        self.assertNotIn("start_label", listed(), "no label until the server has looked")
        with patch(
            "narahem.household_alerts.lookup_address", return_value="556 Myrtle Ave, Clifton"
        ) as lookup:
            self.app.state.maintenance()
            self.app.state.maintenance()
        lookup.assert_called_once()  # only the unsaved start; each trip is named once
        self.assertEqual(lookup.call_args.args[:2], (40.03, -74.0))
        alerts = [a["text"] for a in self.call(b, "GET", "/api/alerts").json()["alerts"]]
        self.assertTrue(any("arrived at Private Home" in text for text in alerts), alerts)
        self.assertEqual(
            (listed()["start_label"], listed()["end_label"]),
            ("556 Myrtle Ave, Clifton", "Private Home"),
        )
        opened = self.call(b, "GET", f"/api/trips/{trip}").json()
        self.assertEqual(
            (opened["start_label"], opened["end_label"]),
            ("556 Myrtle Ave, Clifton", "Private Home"),
        )
        # A place saved later names the trip too.
        self.publish(
            a, kind="place", data={"name": "Work", "lat": 40.03, "lon": -74.0, "radius": 100}
        )
        self.assertEqual(listed()["start_label"], "Work")

    def test_trip_labels_retry_failed_lookups_then_give_up(self):
        from narahem.models import TripLabel

        a, b = self.alert_pair()
        end = int(time.time() * 1000) - 10 * 60000
        summary = {
            "type": "trip_summary",
            "account_id": a["account_id"],
            "started_at": end - 60000,
            "ended_at": end,
            "trip_id": secrets.token_hex(16),
            "distance_m": 3000,
            "max_speed_mps": 15,
            "samples": 30,
            "start": [40.03, -74.0],
            "end": [40.0, -74.0],
        }
        trip = self.publish(a, kind="event", captured=end, data=summary)["body"]["id"]
        with patch("narahem.household_alerts.lookup_address", return_value=None) as lookup:
            for _ in range(4):
                self.app.state.maintenance()
        self.assertEqual(lookup.call_count, 3)
        with Session(self.app.state.engine) as db:
            self.assertIsNotNone(db.get(TripLabel, trip).labels)
        listed = self.call(
            b,
            "GET",
            f"/api/trips?account_id={a['account_id']}&start={end - 70000}&end={end + 1000}",
        ).json()["trips"][0]
        self.assertEqual(listed["end_label"], "Private Home")
        self.assertNotIn("start_label", listed, "the apps fall back to their own lookup")

    def test_view_says_since_when_a_member_stayed_put_and_when_their_phone_was_last_heard(self):
        owner = self.bootstrap()
        member_id, member_client = self.second_member("still@example.invalid", "Sam")
        member = self.register(member_client, member_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, member])
            ).status_code,
            200,
        )
        now = int(time.time() * 1000)
        first = now - 40 * 60000
        for minutes in (40, 25, 10):  # parked: small GPS wobble only
            self.publish(
                member,
                captured=now - minutes * 60000,
                data={"lat": 40.0 + minutes * 1e-6, "lon": -74.0, "accuracy": 10},
            )

        def location():
            return next(
                r
                for r in self.call(member, "GET", "/api/view").json()["records"]
                if r["kind"] == "location"
            )

        seen = location()
        self.assertEqual(seen["still_since"], first)
        self.assertGreater(seen["last_contact"], now - 60000, "any request counts as contact")
        self.publish(member, captured=now, data={"lat": 40.01, "lon": -74.0, "accuracy": 10})
        self.assertEqual(location()["still_since"], now, 'a real move restarts "since"')

    def test_household_alerts_do_not_force_the_slow_trip_history_path(self):
        owner = self.bootstrap()
        now = int(time.time() * 1000)
        url = f"/api/trips?account_id={owner['account_id']}&start={now - 60000}&end={now + 60000}"
        # A trip the server cannot read is refused: it would be missing from the server's history.
        unread = self.record(
            owner,
            kind="event",
            captured=now,
            data={"type": "trip_summary", "started_at": now - 1, "ended_at": now},
            server=False,
        )
        self.assertEqual(self.call(owner, "POST", "/api/records", unread).status_code, 422)
        self.assertEqual(self.call(owner, "GET", url).json()["trips"], [])

    def test_server_serves_places_profiles_and_shared_locations_to_devices_approved_later(self):
        owner = self.bootstrap()
        member_id, member_client = self.second_member("member@example.invalid", "member")
        member = self.register(member_client, member_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, member])
            ).status_code,
            200,
        )
        place = self.publish(
            owner, kind="place", data={"name": "Home", "lat": 40.0, "lon": -74.0, "radius": 100}
        )
        self.publish(
            member,
            kind="profile",
            data={"name": "Member", "photo": "data:image/jpeg;base64," + "A" * 12000},
        )
        self.publish(member, data={"lat": 40.5, "lon": -74.5, "accuracy": 7, "battery_pct": 80})
        # A phone enrolled afterwards was never a recipient, yet the server shows it everything.
        late_id, late_client = self.second_member("late@example.invalid", "late")
        late = self.register(late_client, late_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, member, late])
            ).status_code,
            200,
        )
        view = self.call(late, "GET", "/api/view").json()
        by_kind = {(r["kind"], r["entity_id"]): r for r in view["records"]}
        self.assertEqual(by_kind[("place", place["body"]["entity_id"])]["data"]["name"], "Home")
        self.assertEqual(by_kind[("profile", member_id)]["data"]["name"], "Member")
        self.assertEqual(by_kind[("location", member_id)]["data"]["battery_pct"], 80)
        self.assertEqual(by_kind[("location", member_id)]["sender"], member["id"])
        # The member's sharing choice applies to the server's copy too.
        self.assertEqual(
            self.call(member, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        hidden = self.call(late, "GET", "/api/view").json()["records"]
        self.assertNotIn(("location", member_id), [(r["kind"], r["entity_id"]) for r in hidden])
        self.assertIn(
            ("location", member_id),
            [
                (r["kind"], r["entity_id"])
                for r in self.call(member, "GET", "/api/view").json()["records"]
            ],
        )
        self.assertEqual(self.client.get("/api/view").status_code, 401)

    def test_server_mode_lists_trips_from_its_database_and_opens_their_gps_route(self):
        from narahem.models import IndexedTrip

        owner = self.bootstrap()
        owner_device = self.call(owner, "GET", "/api/device")
        self.assertEqual(owner_device.status_code, 200)
        key = owner_device.json()["trip_processing_key"]
        self.assertEqual(len(base64.b64decode(key)), 32)
        self.assertEqual(self.client.get("/api/device").status_code, 401)
        captured = int(time.time() * 1000)
        trip_id = secrets.token_hex(16)
        points = []
        for index, coords in enumerate([(40.0, -74.0), (40.001, -74.0), (40.002, -74.0)]):
            record = self.record(
                owner,
                data=dict(lat=coords[0], lon=coords[1], accuracy=5, trip_id=trip_id),
                captured=captured + index * 15000,
            )
            plain = dict(
                record["body"],
                domain="narahem.payload.v1",
                data=dict(lat=coords[0], lon=coords[1], accuracy=5, trip_id=trip_id),
            )
            record["body"]["server_box"] = B64(
                SealedBox(PublicKey(base64.b64decode(key))).encrypt(canonical(plain))
            )
            record["signature"] = B64(owner["signing"].sign(canonical(record["body"])).signature)
            self.assertEqual(self.call(owner, "POST", "/api/records", record).status_code, 201)
            points.append(record)
        finish = captured + 30000
        summary = dict(
            type="trip_summary",
            account_id=owner["account_id"],
            started_at=captured,
            ended_at=finish,
            trip_id=trip_id,
            max_speed_mps=12,
            distance_m=180,
            samples=3,
        )
        event = self.record(owner, kind="event", data=summary, captured=finish)
        plain = dict(event["body"], domain="narahem.payload.v1", data=summary)
        event["body"]["server_box"] = B64(
            SealedBox(PublicKey(base64.b64decode(key))).encrypt(canonical(plain))
        )
        event["signature"] = B64(owner["signing"].sign(canonical(event["body"])).signature)
        self.assertEqual(self.call(owner, "POST", "/api/records", event).status_code, 201)
        processor = self.app.state.trip_processor
        processor.process_pending(self.app.state.engine, self.app.state.cipher)
        with Session(self.app.state.engine) as db:
            entry = db.get(IndexedTrip, event["body"]["id"])
            self.assertIsNotNone(entry)
            # Server mode: the readable summary is indexed straight away, encrypted at rest.
            self.assertEqual(entry.status, "ready")
            self.assertNotIn("74.0", entry.encrypted_trip)
        window = f"start={captured - 1000}&end={finish + 1000}"
        url = f"/api/trips?account_id={owner['account_id']}&{window}"
        summaries = self.call(owner, "GET", url)
        self.assertEqual(summaries.status_code, 200, summaries.text)
        self.assertEqual([t["id"] for t in summaries.json()["trips"]], [event["body"]["id"]])
        self.assertEqual(summaries.json()["trips"][0]["distance_m"], 180)
        self.assertFalse(summaries.json()["processing"])
        self.assertFalse(summaries.json()["road_matching_enabled"])
        # Original event stays encrypted and available to its approved devices.
        history = self.call(
            owner,
            "GET",
            f"/api/records?kind=event&account_id={owner['account_id']}&{window}",
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(len(history.json()["records"]), 1)
        stored = history.json()["records"][0]["envelope"]
        self.assertEqual(stored["body"]["id"], event["body"]["id"])
        self.assertIn("server_box", stored["body"])
        self.assertEqual(self.decrypt(owner, stored)["data"], summary)
        # Opening the trip returns the route from the GPS fixes the server can read.
        opened = self.call(owner, "GET", "/api/trips/" + event["body"]["id"])
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.json()["route"], [[40.0, -74.0], [40.001, -74.0], [40.002, -74.0]])
        self.assertEqual(self.client.get("/api/trips/" + event["body"]["id"]).status_code, 401)
        # Modifying the processor ciphertext breaks the signed record body.
        tampered = self.record(owner)
        tampered["body"]["server_box"] = event["body"]["server_box"]
        tampered["signature"] = B64(owner["signing"].sign(canonical(tampered["body"])).signature)
        self.assertEqual(self.call(owner, "POST", "/api/records", tampered).status_code, 422)

    def test_device_permission_snapshot_is_authenticated_and_never_a_live_claim(self):
        admin, member = self.pair()
        payload = dict(
            foreground_location=True,
            background_location=False,
            remote_alarm=True,
            dnd_access=False,
            notifications=True,
            sharing=True,
        )
        self.assertEqual(self.client.put("/api/device/permissions", json=payload).status_code, 401)
        self.assertEqual(
            self.call(member, "PUT", "/api/device/permissions", payload).status_code, 200
        )
        view = self.client.get("/api/devices").json()["devices"]
        result = next(d for d in view if d["id"] == member["id"])
        self.assertEqual(result["permissions"]["foreground_location"], True)
        self.assertEqual(result["permissions"]["background_location"], False)
        self.assertEqual(result["permissions"]["dnd_access"], False)
        self.assertGreater(result["permissions"]["reported_at"], 0)
        payload["dnd_access"] = True
        self.assertEqual(
            self.call(member, "PUT", "/api/device/permissions", payload).status_code, 200
        )
        again = next(
            d for d in self.client.get("/api/devices").json()["devices"] if d["id"] == member["id"]
        )
        self.assertEqual(again["permissions"]["dnd_access"], True)
        self.assertIsNone(next(d for d in view if d["id"] == admin["id"])["permissions"])

    def test_the_admin_browser_always_sees_a_sharing_phone(self):
        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        choices = self.call(b, "GET", "/api/sharing/audience").json()
        self.assertEqual(choices["account_ids"], [self.owner_id])
        self.assertEqual(choices["eligible_members"], [], "the admin is not a member to choose")
        self.assertEqual(choices["owner_viewer"]["id"], self.owner_id)
        # Even with no one chosen, the admin browser stays in the audience.
        self.assertEqual(
            self.call(b, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        self.assertEqual(
            self.call(b, "GET", "/api/sharing/audience").json()["account_ids"], [self.owner_id]
        )
        encrypted = self.record(b, recipients=[a, b])
        self.assertEqual(self.call(b, "POST", "/api/records", encrypted).status_code, 201)
        owner_view = self.call(a, "GET", "/api/view").json()["records"]
        self.assertTrue(any(r["id"] == encrypted["body"]["id"] for r in owner_view))
        # Phone builds from before this don't encrypt for the admin browser; they still upload.
        older = self.record(b, recipients=[b])
        self.assertEqual(self.call(b, "POST", "/api/records", older).status_code, 201)
        mapped = client.get("/api/household/members").json()["members"]
        self.assertNotIn(self.owner_id, [p["id"] for p in mapped])
        self.assertEqual(mapped[0]["id"], member, "A member sees themselves first")
        # The administrator's own phone lists them first, so it can show their own trips.
        own = self.client.get("/api/household/members").json()["members"]
        self.assertEqual([own[0]["id"], own[0]["username"]], [self.owner_id, "Me"])
        self.assertIn(member, [p["id"] for p in own])
        self.assertEqual(
            self.call(a, "GET", "/api/sharing/audience").json()["eligible_members"][0]["id"], member
        )

    def test_capture_filtered_history_keeps_recipient_access_and_pagination(self):
        a = self.bootstrap()
        old = self.publish(a, captured=int(time.time() * 1000) - 600000)
        member, client = self.member()
        b = self.register(client, member)
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        start = int(time.time() * 1000) - 300000
        first = self.publish(b, captured=start + 1000)
        second = self.publish(b, captured=start + 2000)
        self.publish(a, captured=start + 3000)
        params = {
            "kind": "location",
            "account_id": member,
            "device_id": b["id"],
            "start": start,
            "end": start + 2500,
            "limit": 1,
        }
        response = self.call(
            b,
            "GET",
            "/api/records?" + __import__("urllib.parse", fromlist=["urlencode"]).urlencode(params),
        ).json()
        self.assertEqual(response["records"][0]["envelope"]["body"]["id"], second["body"]["id"])
        params["cursor"] = response["next_cursor"]
        older = self.call(
            b,
            "GET",
            "/api/records?" + __import__("urllib.parse", fromlist=["urlencode"]).urlencode(params),
        ).json()
        self.assertEqual(older["records"][0]["envelope"]["body"]["id"], first["body"]["id"])
        self.assertIsNone(older["next_cursor"])
        inaccessible = self.call(
            b,
            "GET",
            "/api/records?account_id=" + self.owner_id + "&end=" + str(old["body"]["captured_at"]),
        ).json()
        self.assertEqual(inaccessible["records"], [])
        self.assertEqual(self.call(a, "GET", "/api/records?start=2&end=1").status_code, 422)
        self.assertEqual(self.call(a, "GET", "/api/records?account_id=invalid").status_code, 422)
        self.assertEqual(self.call(a, "GET", "/api/records?device_id=invalid").status_code, 422)
        self.assertEqual(
            self.call(a, "GET", "/api/records?start=999999999999999999999").status_code, 422
        )

    def test_standard_gps_logs_include_stationary_receipts_and_page_without_debug(self):
        a = self.bootstrap()
        if True:
            first = self.publish(a)
            second = self.publish(a)
            result = self.client.get(
                "/api/logs",
                params={"category": "gps", "limit": 1, "user": self.owner_id, "device": a["id"]},
            ).json()
            self.assertEqual(len(result["entries"]), 1)
            self.assertEqual(result["next_offset"], 1)
            next_page = self.client.get("/api/logs?category=gps&limit=1&offset=1").json()
            ids = {
                result["entries"][0]["details"]["record_id"],
                next_page["entries"][0]["details"]["record_id"],
            }
            self.assertEqual(ids, {first["body"]["id"], second["body"]["id"]})
            self.assertNotIn("12.3456789", json.dumps(result))
            self.assertEqual(
                self.client.get("/api/logs?category=gps&device=" + "0" * 32).json()["entries"], []
            )
            self.assertEqual(
                self.client.get("/api/logs?category=gps&outcome=failed").json()["entries"], []
            )

    def test_redacted_diagnostics_download_is_admin_only(self):
        phone = self.bootstrap()
        self.publish(phone, captured=int(time.time() * 1000) - 60000)
        report = self.client.get("/api/admin/diagnostics?category=gps&hours=3")
        self.assertEqual(report.status_code, 200, report.text[:400])
        self.assertTrue(report.headers["content-disposition"].startswith("attachment; filename="))
        self.assertEqual(report.headers["cache-control"], "no-store")
        self.assertIn("NARAHEM SUPPORT DIAGNOSTICS", report.text)
        self.assertIn("platform=", report.text)
        self.assertIn("upload_delay_ms", report.text)
        self.assertNotIn("12.3456789", report.text)
        self.assertNotIn("private_key", report.text)
        self.assertNotIn("server.key", report.text)
        self.assertEqual(
            self.client.get("/api/admin/diagnostics?category=gps&hours=0").status_code, 422
        )
        self.assertEqual(
            self.client.get("/api/admin/diagnostics?category=foo&hours=3").status_code, 422
        )
        _, member_client = self.member()
        self.assertEqual(
            member_client.get("/api/admin/diagnostics?category=gps&hours=3").status_code, 403
        )
        self.assertEqual(
            self.client.get("/api/admin/diagnostics?category=trips&hours=3").status_code, 200
        )

    def test_diagnostics_export_writes_readable_redacted_reports(self):
        import os
        import stat
        import tempfile

        phone = self.bootstrap()
        self.publish(phone, captured=int(time.time() * 1000) - 60000)
        # Without a mounted folder the feature is off.
        with patch.dict("os.environ", {"NARAHEM_EXPORT_DIR": "/nonexistent-narahem-exports"}):
            self.assertFalse(self.client.get("/api/storage").json()["exports_available"])
            self.assertEqual(
                self.client.post(
                    "/api/admin/diagnostics/export", json={"category": "gps", "hours": 3}
                ).status_code,
                409,
            )
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict("os.environ", {"NARAHEM_EXPORT_DIR": folder}),
        ):
            self.assertTrue(self.client.get("/api/storage").json()["exports_available"])
            saved = self.client.post(
                "/api/admin/diagnostics/export", json={"category": "gps", "hours": 3}
            )
            self.assertEqual(saved.status_code, 201, saved.text)
            path = os.path.join(folder, saved.json()["saved"])
            self.assertEqual(
                stat.S_IMODE(os.stat(path).st_mode), 0o644, "Readable from a host file share"
            )
            with open(path) as f:
                text = f.read()
            self.assertIn("NARAHEM SUPPORT DIAGNOSTICS", text)
            self.assertNotIn("12.3456789", text)
            self.assertNotIn("private_key", text)
            # Old reports beyond the 30-day window are pruned on the next save.
            stale = os.path.join(folder, "narahem-gps-3h-20000101-000000.txt")
            with open(stale, "w") as f:
                f.write("old")
            os.utime(stale, (time.time() - 40 * 86400,) * 2)
            time.sleep(1)
            self.assertEqual(
                self.client.post(
                    "/api/admin/diagnostics/export", json={"category": "trips", "hours": 24}
                ).status_code,
                201,
            )
            self.assertFalse(os.path.exists(stale))
            self.assertEqual(
                self.client.post(
                    "/api/admin/diagnostics/export", json={"category": "bogus", "hours": 3}
                ).status_code,
                422,
            )
            _, member_client = self.member()
            self.assertEqual(
                member_client.post(
                    "/api/admin/diagnostics/export", json={"category": "gps", "hours": 3}
                ).status_code,
                403,
            )

    def test_logs_expire_diagnostics(self):
        a = self.bootstrap()
        if True:
            with Session(self.app.state.engine) as db:
                db.add(
                    DiagnosticEntry(
                        id="0" * 32,
                        category="gps",
                        action="old",
                        account_id=self.owner_id,
                        device_id=a["id"],
                        outcome="ok",
                        created=time.time() - 15 * 86400,
                        details="{}",
                    )
                )
                db.commit()
                diagnostic(db, "gps", "new", self.owner_id, a["id"])
                db.commit()
                self.assertIsNone(db.get(DiagnosticEntry, "0" * 32))

    def test_email_verification_and_local_bootstrap_are_separate(self):
        with Session(self.app.state.engine) as db:
            db.get(Account, self.owner_id).verified = False
            db.commit()
        signing, box = SigningKey.generate(), PrivateKey.generate()
        response = self.client.post(
            "/api/devices/register",
            json=dict(
                id=secrets.token_hex(16),
                name="Unverified",
                signing_key=B64(signing.verify_key),
                box_key=B64(box.public_key),
                signature=B64(bytes(64)),
            ),
        )
        self.assertEqual(response.status_code, 403)
        with Session(self.app.state.engine) as db:
            db.get(Account, self.owner_id).verified = True
            db.commit()
        d = self.register()
        r = self.call(d, "POST", "/api/roster", self.roster(d, [d], "wrong" * 8))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.call(d, "GET", "/api/view").status_code, 403)

    def test_verified_admin_can_bootstrap_first_device_using_short_lived_email_code(self):
        import re

        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        d = self.register()
        request = self.client.post(
            "/api/device-bootstrap/email/request", json={"device_id": d["id"]}
        )
        self.assertEqual(request.status_code, 202, request.text)
        code = re.search(r"six-digit first-device code is ([0-9]{6})", self.messages[-1][3]).group(
            1
        )
        self.assertNotIn("\\n", self.messages[-1][3])
        envelope = self.roster(d, [d])
        envelope["bootstrap_email_code"] = code
        result = self.call(d, "POST", "/api/roster", envelope)
        self.assertEqual(result.status_code, 200, result.text)
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(ServiceState, 1).anchor, d["signing_key"])
        second = self.client.post(
            "/api/device-bootstrap/email/request", json={"device_id": d["id"]}
        )
        self.assertEqual(second.status_code, 409)

    def test_wrong_email_codes_are_limited_and_cannot_bootstrap(self):
        import re

        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        d = self.register()
        self.assertEqual(
            self.client.post(
                "/api/device-bootstrap/email/request", json={"device_id": d["id"]}
            ).status_code,
            202,
        )
        sent = re.search(r"six-digit first-device code is ([0-9]{6})", self.messages[-1][3]).group(
            1
        )
        wrong = "000000" if sent != "000000" else "111111"
        for _ in range(5):
            envelope = self.roster(d, [d])
            envelope["bootstrap_email_code"] = wrong
            self.assertEqual(self.call(d, "POST", "/api/roster", envelope).status_code, 403)
        envelope = self.roster(d, [d])
        envelope["bootstrap_email_code"] = sent
        self.assertEqual(self.call(d, "POST", "/api/roster", envelope).status_code, 403)

    def test_signed_short_code_pairing_requires_exact_pending_registration(self):
        a = self.bootstrap()
        b = self.register()
        body = self.roster(a, [a, b])
        body["body"]["pairing_target"] = b["id"]
        body["body"]["pairing_hash"] = "0" * 64
        body["signature"] = B64(a["signing"].sign(canonical(body["body"])).signature)
        denied = self.call(a, "POST", "/api/roster", body)
        self.assertEqual(denied.status_code, 422, denied.text)
        expected = (
            __import__("hashlib")
            .sha256(
                canonical(
                    dict(domain="narahem.device.v1", household=self.household, **self.identity(b))
                )
            )
            .hexdigest()
        )
        body["body"]["pairing_hash"] = expected
        body["signature"] = B64(a["signing"].sign(canonical(body["body"])).signature)
        allowed = self.call(a, "POST", "/api/roster", body)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        reply = self.call(b, "GET", "/api/roster").json()
        self.assertEqual(reply["changes"][-1]["body"]["pairing_target"], b["id"])
        self.assertEqual(reply["changes"][-1]["body"]["pairing_hash"], expected)

    def test_pairing_cannot_claim_old_device_or_add_two_at_once(self):
        a = self.bootstrap()
        b = self.register()
        c = self.register()
        body = self.roster(a, [a, b, c])
        body["body"]["pairing_target"] = b["id"]
        body["body"]["pairing_hash"] = (
            __import__("hashlib")
            .sha256(
                canonical(
                    dict(domain="narahem.device.v1", household=self.household, **self.identity(b))
                )
            )
            .hexdigest()
        )
        body["signature"] = B64(a["signing"].sign(canonical(body["body"])).signature)
        self.assertEqual(self.call(a, "POST", "/api/roster", body).status_code, 422)
        body = self.roster(a, [a])
        body["body"]["pairing_target"] = a["id"]
        body["body"]["pairing_hash"] = "0" * 64
        body["signature"] = B64(a["signing"].sign(canonical(body["body"])).signature)
        self.assertEqual(self.call(a, "POST", "/api/roster", body).status_code, 422)
        self.assertEqual(self.call(b, "GET", "/api/view").status_code, 403)

    def test_pending_device_cannot_approve_itself_or_read_data(self):
        a = self.bootstrap()
        b = self.register()
        self.assertEqual(
            self.call(b, "POST", "/api/roster", self.roster(b, [a, b])).status_code, 403
        )
        self.assertEqual(self.call(b, "GET", "/api/records").status_code, 403)
        self.assertEqual(self.call(b, "POST", "/api/records", self.record(b)).status_code, 403)
        batch = {"records": [self.record(b)]}
        self.assertEqual(self.call(b, "POST", "/api/records/batch", batch).status_code, 403)

    def test_two_device_roundtrip_database_has_no_plaintext_payload(self):
        a, b = self.pair()
        record = self.publish(a)
        for d in (a, b):
            fetched = self.call(d, "GET", f"/api/records/{record['body']['id']}")
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(self.decrypt(d, fetched.json()["envelope"])["data"]["lat"], 12.3456789)
        with Session(self.app.state.engine) as db:
            stored = db.get(EncryptedRecord, record["body"]["id"])
            self.assertNotIn("12.3456789", stored.envelope)
            self.assertNotIn("-23.4567891", stored.envelope)
            self.assertNotEqual(db.get(ClientDevice, a["id"]).credential, a["credential"])

    def test_sender_signature_replay_and_duplicate_controls(self):
        a = self.bootstrap()
        r = self.publish(a)
        duplicate = self.call(a, "POST", "/api/records", r)
        self.assertTrue(duplicate.json()["duplicate"])
        changed = copy.deepcopy(r)
        changed["body"]["captured_at"] -= 1000
        self.assertEqual(self.call(a, "POST", "/api/records", changed).status_code, 403)
        replay = self.record(a, sequence=r["body"]["sequence"])
        self.assertEqual(self.call(a, "POST", "/api/records", replay).status_code, 409)
        r["body"]["id"] = secrets.token_hex(16)
        self.assertEqual(self.call(a, "POST", "/api/records", r).status_code, 403)

    def test_stale_membership_and_missing_recipients_rejected(self):
        a = self.bootstrap()
        old = self.record(a)
        b = self.register()
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        self.assertEqual(self.call(a, "POST", "/api/records", old).status_code, 409)
        self.assertEqual(
            self.call(a, "POST", "/api/records", self.record(a, recipients=[a])).status_code, 409
        )

    def test_plaintext_fields_and_cross_household_forgery_rejected(self):
        a = self.bootstrap()
        r = self.record(a)
        r["body"]["latitude"] = 12.3456789
        self.assertEqual(self.call(a, "POST", "/api/records", r).status_code, 422)
        r = self.record(a)
        r["body"]["household"] = "f" * 32
        r["signature"] = B64(a["signing"].sign(canonical(r["body"])).signature)
        self.assertEqual(self.call(a, "POST", "/api/records", r).status_code, 403)

    def test_old_offline_fix_does_not_replace_newer_latest(self):
        a = self.bootstrap()
        now = int(time.time() * 1000)
        new = self.publish(a, captured=now)
        self.publish(a, captured=now - 3600000)
        state = self.call(a, "GET", "/api/view").json()["records"]
        self.assertEqual(state[0]["id"], new["body"]["id"])

    def test_expiry_hides_records_before_cleanup_and_rejects_old_upload(self):
        a = self.bootstrap()
        r = self.publish(a)
        future = time.time() + 15 * 86400
        with patch("narahem.data_service.time.time", return_value=future):
            self.assertEqual(
                self.call(a, "GET", f"/api/records/{r['body']['id']}").status_code, 404
            )
            self.assertEqual(self.call(a, "GET", "/api/records").json()["records"], [])
            with Session(self.app.state.engine) as db:
                self.assertIsNotNone(db.get(EncryptedRecord, r["body"]["id"]))
            self.assertEqual(
                self.call(
                    a, "POST", "/api/records", self.record(a, captured=r["body"]["captured_at"])
                ).status_code,
                422,
            )
            self.app.state.maintenance()
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord, r["body"]["id"]))

    def test_retention_shortening_deletes_history_but_keeps_places(self):
        a = self.bootstrap()
        old = int((time.time() - 2 * 86400) * 1000)
        r = self.publish(a, captured=old)
        place = self.publish(a, kind="place", data={"name": "Private School"}, captured=old)
        self.assertEqual(
            self.client.put("/api/storage/retention", json={"days": 1}).status_code, 200
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord, r["body"]["id"]))
            self.assertIsNotNone(db.get(EncryptedRecord, place["body"]["id"]))
        self.assertEqual(
            self.client.put("/api/storage/retention", json={"days": 15}).status_code, 422
        )

    def test_place_compare_and_swap_and_tombstone(self):
        a = self.bootstrap()
        place = self.publish(a, kind="place", data={"name": "Private Home"})
        stale = self.record(a, kind="place", entity=place["body"]["entity_id"], replaces=None)
        self.assertEqual(self.call(a, "POST", "/api/records", stale).status_code, 409)
        deleted = self.publish(
            a, kind="place", entity=place["body"]["entity_id"], operation="delete", data={}
        )
        self.assertEqual(
            self.call(a, "GET", "/api/view").json()["records"], [], "a deleted place is gone"
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord, place["body"]["id"]))
            self.assertEqual(
                db.get(LatestState, ("place", place["body"]["entity_id"])).record_id,
                deleted["body"]["id"],
            )

    def test_equal_timestamp_pagination_never_drops_records(self):
        a = self.bootstrap()
        stamp = int(time.time() * 1000)
        r1 = self.publish(a, captured=stamp)
        r2 = self.publish(a, captured=stamp)
        first = self.call(a, "GET", "/api/records?limit=1").json()
        second = self.call(a, "GET", f"/api/records?limit=1&cursor={first['next_cursor']}").json()
        ids = {
            first["records"][0]["envelope"]["body"]["id"],
            second["records"][0]["envelope"]["body"]["id"],
        }
        self.assertEqual(ids, {r1["body"]["id"], r2["body"]["id"]})
        self.assertIsNone(second["next_cursor"])

    def test_pause_hides_latest_and_blocks_new_location(self):
        a = self.bootstrap()
        self.publish(a)
        self.assertEqual(self.call(a, "PUT", "/api/sharing", {"enabled": False}).status_code, 200)
        self.assertEqual(self.call(a, "GET", "/api/view").json()["records"], [])
        self.assertEqual(self.call(a, "POST", "/api/records", self.record(a)).status_code, 403)
        self.call(a, "PUT", "/api/sharing", {"enabled": True})
        self.publish(a)

    def test_revocation_excludes_future_recipient_and_blocks_credential(self):
        a, b = self.pair()
        old = self.publish(a)
        self.assertEqual(self.call(a, "POST", "/api/roster", self.roster(a, [a])).status_code, 200)
        self.assertEqual(self.call(b, "GET", "/api/view").status_code, 401)
        future = self.publish(a)
        self.assertEqual([r["device_id"] for r in future["body"]["recipients"]], [a["id"]])
        self.assertEqual(self.decrypt(b, old)["data"]["lat"], 12.3456789)

    def test_delete_own_history_does_not_delete_other_accounts_or_places(self):
        a = self.bootstrap()
        loc = self.publish(a)
        place = self.publish(a, kind="place", data={"name": "Persistent place"})
        self.assertEqual(self.call(a, "DELETE", "/api/records/mine", {}).json()["deleted"], 1)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord, loc["body"]["id"]))
            self.assertIsNotNone(db.get(EncryptedRecord, place["body"]["id"]))
        self.assertEqual(self.call(a, "POST", "/api/records", loc).status_code, 409)

    def test_phone_audience_enforces_exact_encryption_and_removes_old_server_access(self):
        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b])).status_code, 200
        )
        old = self.publish(a)
        self.assertEqual(len(self.call(b, "GET", "/api/view").json()["records"]), 1)
        permitted = self.call(a, "GET", "/api/sharing/audience").json()
        self.assertEqual(permitted["account_ids"], [member])
        self.assertTrue(permitted["default_all"])
        self.assertEqual(
            self.call(a, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        self.assertEqual(self.call(b, "GET", "/api/view").json()["records"], [])
        self.assertEqual(self.call(b, "GET", "/api/records?kind=location").json()["records"], [])
        self.assertEqual(self.call(b, "GET", f"/api/records/{old['body']['id']}").status_code, 404)
        # Even a valid signed all-devices record must now be rejected.
        self.assertEqual(
            self.call(a, "POST", "/api/records", self.record(a, recipients=[a, b])).status_code, 409
        )
        private = self.publish(a, recipients=[a])
        self.assertEqual(len(self.call(a, "GET", "/api/view").json()["records"]), 1)
        self.assertEqual(self.call(b, "GET", "/api/view").json()["records"], [])
        self.assertEqual(
            self.call(a, "PUT", "/api/sharing/audience", {"account_ids": [member]}).status_code, 200
        )
        new = self.publish(a, recipients=[a, b])
        self.assertEqual(
            self.call(b, "GET", "/api/view").json()["records"][0]["id"], new["body"]["id"]
        )
        # Existing encrypted private record was NOT retroactively shared.
        self.assertEqual(
            self.call(b, "GET", f"/api/records/{private['body']['id']}").status_code, 404
        )
        self.assertEqual(
            self.call(
                a, "PUT", "/api/sharing/audience", {"account_ids": [self.owner_id]}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.call(
                a, "PUT", "/api/sharing/audience", {"account_ids": ["not-an-id"]}
            ).status_code,
            422,
        )

    def test_profile_pointer_allows_new_device_to_update_own_encrypted_avatar(self):
        a = self.bootstrap()
        self.assertIsNone(self.call(a, "GET", "/api/profile/current").json()["replaces"])
        first = self.publish(
            a, kind="profile", data={"name": "Owner", "photo": "data:image/jpeg;base64," + "AA=="}
        )
        self.assertEqual(
            self.call(a, "GET", "/api/profile/current").json()["replaces"], first["body"]["id"]
        )
        b = self.register()
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b])).status_code, 200
        )
        # Newly approved phone cannot decrypt an old profile yet, but can
        # replace it using the authenticated pointer.
        self.assertEqual(
            self.call(b, "GET", "/api/profile/current").json()["replaces"], first["body"]["id"]
        )
        updated = self.publish(
            b,
            kind="profile",
            replaces=first["body"]["id"],
            data={"name": "Owner", "photo": "data:image/jpeg;base64," + "AA=="},
        )
        self.assertEqual(
            self.call(a, "GET", "/api/profile/current").json()["replaces"], updated["body"]["id"]
        )
        self.assertEqual(len(self.call(b, "GET", "/api/view").json()["records"]), 1)

    def test_storage_quota_and_large_request_fail_closed(self):
        a = self.bootstrap()
        r = self.publish(a)
        with Session(self.app.state.engine) as db:
            db.get(EncryptedRecord, r["body"]["id"]).bytes = 600 * 1048576
            db.commit()
        self.assertEqual(self.call(a, "POST", "/api/records", self.record(a)).status_code, 507)
        response = self.client.post(
            "/api/records",
            content=b"x" * 1048577,
            headers={
                "Authorization": f"Bearer {a['credential']}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 413)

    def apns(self):
        key = (
            ec.generate_private_key(ec.SECP256R1())
            .private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            .decode()
        )
        conf = {
            "team_id": "A" * 10,
            "key_id": "B" * 10,
            "topic": "com.example.app",
            "sandbox": True,
            "private_key": key,
        }
        self.assertEqual(
            self.client.put("/api/push/config", json={"apns": conf, "fcm": None}).status_code, 200
        )
        return conf

    def test_signed_find_phone_command_sends_only_generic_push_nudge(self):
        owner, target = self.pair()
        self.assertEqual(
            self.call(
                target,
                "PUT",
                "/api/find-phone/capability",
                {"enabled": True, "platform": "android"},
            ).status_code,
            200,
        )
        phone_token = "trusted-phone-token-" + "A" * 100
        self.assertEqual(
            self.call(
                target, "PUT", "/api/push/subscription", {"provider": "fcm", "token": phone_token}
            ).status_code,
            200,
        )
        now = int(time.time())
        body = dict(
            domain="narahem.find-phone.v1",
            household=self.household,
            id=secrets.token_hex(16),
            issuer=owner["id"],
            target=target["id"],
            action="ring",
            issued_at=now,
            expires_at=now + 90,
        )
        signed = dict(body=body, signature=B64(owner["signing"].sign(canonical(body)).signature))
        with patch.dict(
            "os.environ",
            {
                "NARAHEM_FCM_RELAY_URL": "https://fcm.example.workers.dev/v1/push",
                "NARAHEM_FCM_RELAY_TOKEN": "worker-private-auth-value",
            },
        ):
            with patch("narahem.push_service.httpx.Client") as transport:
                client = transport.return_value.__enter__.return_value
                client.post.return_value.status_code = 200
                client.post.return_value.json.return_value = {"acceptedByFcm": True}
                outcome = self.call(owner, "POST", "/api/find-phone/commands", signed)
        self.assertEqual(outcome.status_code, 201, outcome.text)
        self.assertTrue(client.post.called)
        forwarded = client.post.call_args.kwargs["json"]
        self.assertEqual(forwarded["deviceToken"], phone_token)
        # A silent wake (no text): the phone fetches the signed command itself.
        self.assertEqual(set(forwarded), {"deviceToken", "expiresInSeconds", "intent"})
        self.assertEqual(forwarded["intent"], "alert")
        self.assertLessEqual(forwarded["expiresInSeconds"], 120)
        self.assertNotIn(body["id"], repr(forwarded))
        self.assertNotIn(self.household, repr(forwarded))
        status = self.call(target, "GET", "/api/find-phone/command").json()
        self.assertEqual(status["command"]["body"]["id"], body["id"])

    def test_find_phone_push_provider_failure_is_recorded_without_secrets(self):
        owner, target = self.pair()
        self.assertEqual(
            self.call(
                target, "PUT", "/api/find-phone/capability", {"enabled": True, "platform": "ios"}
            ).status_code,
            200,
        )
        token = "f" * 64
        self.assertEqual(
            self.call(
                target,
                "PUT",
                "/api/push/subscription",
                {"provider": "apns", "token": token, "environment": "production"},
            ).status_code,
            200,
        )
        now = int(time.time())
        body = dict(
            domain="narahem.find-phone.v1",
            household=self.household,
            id=secrets.token_hex(16),
            issuer=owner["id"],
            target=target["id"],
            action="ring",
            issued_at=now,
            expires_at=now + 90,
        )
        signed = dict(body=body, signature=B64(owner["signing"].sign(canonical(body)).signature))
        with patch.dict(
            "os.environ",
            {
                "NARAHEM_PUSH_RELAY_URL": "https://apns.example.workers.dev/v1/push",
                "NARAHEM_PUSH_RELAY_TOKEN": "private-server-only-value",
            },
        ):
            with patch("narahem.push_service.httpx.Client") as transport:
                client = transport.return_value.__enter__.return_value
                client.post.return_value.status_code = 502
                client.post.return_value.json.return_value = {
                    "acceptedByApns": False,
                    "stage": "apns_response",
                    "reason": "BadDeviceToken",
                    "apnsStatus": 400,
                    "private_key": "must-not-be-recorded",
                    "deviceToken": token,
                }
                outcome = self.call(owner, "POST", "/api/find-phone/commands", signed)
        self.assertEqual(outcome.status_code, 201, outcome.text)
        self.assertTrue(client.post.called)
        with Session(self.app.state.engine) as db:
            rows = list(
                db.scalars(
                    select(DiagnosticEntry).where(
                        DiagnosticEntry.action == "find-phone.push.result"
                    )
                )
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].outcome, "failed")
        self.assertEqual(rows[0].device_id, target["id"])
        self.assertEqual(rows[0].category, "notification")
        self.assertNotIn(token, rows[0].details)
        self.assertNotIn("private-server-only-value", rows[0].details)
        self.assertNotIn(body["id"], rows[0].details)
        details = json.loads(rows[0].details)
        self.assertEqual(details["reason"], "relay_or_provider_request_failed")
        self.assertEqual(details["stage"], "apns_response")
        self.assertEqual(details["relay_http_status"], 502)
        self.assertEqual(details["apns_http_status"], 400)
        self.assertEqual(details["apns_reason"], "BadDeviceToken")
        self.assertNotIn("must-not-be-recorded", rows[0].details)

    def test_safe_apns_relay_error_identifiers_never_copy_untrusted_strings(self):
        from narahem.push_service import PushRelayFailure

        error = PushRelayFailure(
            502,
            {
                "stage": "signing_key_import",
                "errorCode": "DataError",
                "reason": "unexpected-secret-from-provider",
                "apnsStatus": None,
                "private_key": "synthetic-sensitive-value",
            },
        )
        self.assertEqual(error.stage, "signing_key_import")
        self.assertEqual(error.error_code, "DataError")
        self.assertIsNone(error.apns_reason)
        self.assertIsNone(error.apns_status)
        rejected = PushRelayFailure(
            401,
            {
                "stage": "<script>secret</script>",
                "errorCode": "unbounded-credential",
                "reason": "token-contents",
                "apnsStatus": "403",
            },
        )
        self.assertEqual(rejected.stage, "relay_response")
        self.assertIsNone(rejected.error_code)
        self.assertIsNone(rejected.apns_reason)
        self.assertIsNone(rejected.apns_status)
        self.assertEqual(rejected.relay_status, 401)

    def test_admin_targeted_push_checks_other_member_subscription_without_leaking_token(self):
        owner = self.bootstrap()
        member, member_client = self.member()
        iphone = self.register(member_client, member)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, iphone])
            ).status_code,
            200,
        )
        self.apns()
        # An approved device can have notifications permitted but no subscription.
        before = self.client.get("/api/push/status")
        self.assertEqual(before.status_code, 200, before.text)
        entry = next(d for d in before.json()["devices"] if d["id"] == iphone["id"])
        self.assertFalse(entry["registered"])
        self.assertIsNone(entry["provider"])
        self.assertNotIn("token", json.dumps(before.json()))
        self.assertEqual(member_client.get("/api/push/status").status_code, 403)
        self.assertEqual(
            member_client.post("/api/push/test", json={"device_id": iphone["id"]}).status_code, 403
        )
        self.assertEqual(self.client.post("/api/push/test", json={}).json(), {"sent": 0})
        self.assertEqual(
            self.client.post("/api/push/test", json={"device_id": iphone["id"]}).json(), {"sent": 0}
        )

        token = "e" * 64
        response = self.call(
            iphone,
            "PUT",
            "/api/push/subscription",
            {"provider": "apns", "token": token, "environment": "production"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        status = self.client.get("/api/push/status").json()
        entry = next(d for d in status["devices"] if d["id"] == iphone["id"])
        self.assertTrue(entry["registered"])
        self.assertEqual(entry["provider"], "apns")
        self.assertNotIn(token, json.dumps(status))
        with patch("narahem.push_service.deliver", return_value="sent") as deliver:
            response = self.client.post("/api/push/test", json={"device_id": iphone["id"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"sent": 1})
        self.assertEqual(deliver.call_args.args[0], "apns")
        self.assertEqual(deliver.call_args.args[1], "production:" + token)
        self.assertEqual(deliver.call_count, 1)
        with patch("narahem.push_service.deliver", return_value="invalid"):
            rejected = self.client.post("/api/push/test", json={"device_id": iphone["id"]})
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(
            rejected.json(),
            {"sent": 0},
            "Invalid token must not be reported as a submitted test push",
        )
        from narahem.push_service import PushRelayFailure

        refusal = PushRelayFailure(
            502, {"stage": "apns_response", "apnsStatus": 400, "reason": "DeviceTokenNotForTopic"}
        )
        with patch("narahem.push_service.deliver", side_effect=refusal):
            refused = self.client.post("/api/push/test", json={"device_id": iphone["id"]})
        self.assertEqual(refused.status_code, 424, refused.text)
        self.assertIn("HTTP 502 (Apple: DeviceTokenNotForTopic)", refused.json()["detail"])
        self.assertEqual(
            self.client.post("/api/push/test", json={"device_id": "f" * 32}).status_code, 404
        )
        self.assertEqual(
            self.client.post("/api/push/test", json={"device_id": "bad-id"}).status_code, 422
        )

    def alert_pair(self):
        """Phones of two members, a and b; a is at a saved place called Private Home."""
        owner = self.bootstrap()
        ids = [self.second_member(f"{n}@example.invalid", n) for n in ("alex", "blair")]
        a, b = [self.register(client, ident) for ident, client in ids]
        self.assertEqual(
            self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, a, b])).status_code,
            200,
        )
        self.publish(
            owner,
            kind="place",
            data={"name": "Private Home", "lat": 40.0, "lon": -74.0, "radius": 100},
        )
        self.publish(a, data={"lat": 40.0, "lon": -74.0, "accuracy": 10})
        return a, b

    def leave_home(self, a):
        """a drives away from Private Home: the server decides "left" and queues pushes."""
        self.publish(
            a, data={"lat": 40.01, "lon": -74.0, "accuracy": 10, "trip_id": secrets.token_hex(16)}
        )
        from narahem.models import ServerAlert

        with Session(self.app.state.engine) as db:
            return db.scalar(select(ServerAlert.id).order_by(ServerAlert.created.desc()))

    def test_alert_pushes_reach_subscribed_phones_of_other_members(self):
        a, b = self.alert_pair()
        self.apns()
        self.assertEqual(
            self.call(
                b, "PUT", "/api/push/subscription", {"provider": "apns", "token": "c" * 64}
            ).json(),
            {"registered": True},
        )
        alert = self.leave_home(a)
        with Session(self.app.state.engine) as db:
            job = db.scalar(select(PushDelivery))
            self.assertEqual((job.record_id, job.device_id), (alert, b["id"]))
            self.assertLessEqual(job.expires_at - job.created, 900)
        with patch("narahem.push_service.deliver", return_value="sent") as deliver:
            self.app.state.maintenance()
        self.assertEqual(deliver.call_args.kwargs["kind"], "alert")
        self.assertEqual(self.call(b, "DELETE", "/api/push/subscription", {}).status_code, 200)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(PushSubscription, b["id"]))

    def test_push_secrets_encrypted_event_queue_and_provider_failure_retry(self):
        a, b = self.alert_pair()
        conf = self.apns()
        token = "c" * 64
        self.call(b, "PUT", "/api/push/subscription", {"provider": "apns", "token": token})
        event = self.leave_home(a)
        with Session(self.app.state.engine) as db:
            self.assertNotIn(conf["private_key"], db.get(ServiceState, 1).push_config)
            self.assertNotIn(token, db.get(PushSubscription, b["id"]).token)
            self.assertEqual(db.query(PushDelivery).count(), 1)
        self.assertNotIn("private_key", json.dumps(self.client.get("/api/push/config").json()))
        with patch("narahem.push_service.deliver", side_effect=OSError("provider-secret")):
            self.app.state.maintenance()
        with Session(self.app.state.engine) as db:
            job = db.scalar(select(PushDelivery))
            self.assertEqual(job.attempts, 1)
            job.retry_at = 0
            db.commit()
        with patch("narahem.push_service.deliver", return_value="sent") as deliver:
            self.app.state.maintenance()
        self.assertEqual(deliver.call_args.args[2], event)
        self.assertNotIn("Private Home", repr(deliver.call_args))
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.query(PushDelivery).count(), 0)

    def test_find_phone_direct_apns_is_time_sensitive_but_not_critical(self):
        import uuid

        from narahem.push_service import deliver

        apns = self.apns()
        with patch("narahem.push_service.httpx.Client") as client:
            connection = client.return_value.__enter__.return_value
            connection.post.return_value.status_code = 200
            delivered = deliver(
                "apns",
                "production:" + "a" * 64,
                "0" * 32,
                uuid.uuid4().hex,
                {"apns": apns},
                kind="find-phone",
            )
            self.assertEqual(delivered, "sent")
        posted = connection.post.call_args
        self.assertEqual(posted.args[0], "https://api.push.apple.com/3/device/" + "a" * 64)
        payload = posted.kwargs["json"]
        self.assertEqual(payload["aps"]["interruption-level"], "time-sensitive")
        self.assertEqual(payload["aps"]["category"], "narahem-find-phone")
        self.assertEqual(payload["aps"]["sound"], "narahem-find-phone-v1.wav")
        self.assertNotIn("critical", json.dumps(payload))
        self.assertNotIn("location", json.dumps(payload))
        with self.assertRaises(ValueError):
            deliver(
                "apns",
                "a" * 64,
                "0" * 32,
                uuid.uuid4().hex,
                {"apns": apns},
                kind="unapproved-category",
            )

    def test_apns_request_is_generic_and_invalid_registration_removed(self):
        a, b = self.alert_pair()
        self.apns()
        self.call(b, "PUT", "/api/push/subscription", {"provider": "apns", "token": "c" * 64})
        self.leave_home(a)
        with patch("narahem.push_service.httpx.Client") as client:
            connection = client.return_value.__enter__.return_value
            connection.post.return_value.status_code = 410
            self.app.state.maintenance()
        request = connection.post.call_args
        self.assertEqual(request.args[0], "https://api.sandbox.push.apple.com/3/device/" + "c" * 64)
        self.assertNotIn("12.3456789", json.dumps(request.kwargs["json"]))
        self.assertNotIn("Secret Home", json.dumps(request.kwargs["json"]))
        # The iPhone's service extension replaces this fallback text with the decrypted alert.
        self.assertEqual(request.kwargs["json"]["aps"]["mutable-content"], 1)
        self.assertEqual(request.kwargs["json"]["aps"]["alert"]["body"], "Household alert")
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(PushSubscription, b["id"]))

    def test_android_fcm_cloudflare_relay_only_sends_generic_push(self):
        a, b = self.alert_pair()
        token = "test-android-fcm-token-value" + "X" * 80
        variables = {
            "NARAHEM_FCM_RELAY_URL": "https://android-relay.example.workers.dev/v1/push",
            "NARAHEM_FCM_RELAY_TOKEN": "separate-android-worker-secret",
        }
        with patch.dict("os.environ", variables):
            self.assertTrue(
                self.client.get("/api/push/config").json()["cloudflare_fcm_relay_configured"]
            )
            registration = self.call(
                b, "PUT", "/api/push/subscription", {"provider": "fcm", "token": token}
            )
            self.assertEqual(registration.status_code, 200, registration.text)
            self.leave_home(a)
            with patch("narahem.push_service.httpx.Client") as client:
                connection = client.return_value.__enter__.return_value
                connection.post.return_value.status_code = 200
                connection.post.return_value.json.return_value = {
                    "acceptedByFcm": True,
                    "fcmStatus": 200,
                }
                self.app.state.maintenance()
            request = connection.post.call_args
            self.assertEqual(request.args[0], variables["NARAHEM_FCM_RELAY_URL"])
            self.assertEqual(
                request.kwargs["headers"]["Authorization"], "Bearer separate-android-worker-secret"
            )
            self.assertEqual(
                request.kwargs["json"],
                {
                    "deviceToken": token,
                    "expiresInSeconds": request.kwargs["json"]["expiresInSeconds"],
                    "intent": "alert",
                },
            )
            self.assertNotIn("Private Home", repr(request.kwargs))
            self.assertNotIn("12.345", repr(request.kwargs))
            with Session(self.app.state.engine) as db:
                self.assertEqual(db.query(PushDelivery).count(), 0)

    def test_android_fcm_worker_rejection_is_not_reported_as_delivered(self):
        a, b = self.pair()
        token = "test-android-fcm-token-value" + "X" * 80
        variables = {
            "NARAHEM_FCM_RELAY_URL": "https://android-relay.example.workers.dev/v1/push",
            "NARAHEM_FCM_RELAY_TOKEN": "separate-android-worker-secret",
        }
        with patch.dict("os.environ", variables):
            self.assertEqual(
                self.call(
                    b, "PUT", "/api/push/subscription", {"provider": "fcm", "token": token}
                ).status_code,
                200,
            )
            with patch("narahem.push_service.httpx.Client") as client:
                connection = client.return_value.__enter__.return_value
                connection.post.return_value.status_code = 502
                connection.post.return_value.json.return_value = {
                    "ok": False,
                    "fcmStatus": 400,
                    "reason": "INVALID_ARGUMENT",
                }
                response = self.client.post("/api/push/test", json={"device_id": b["id"]})
            self.assertEqual(response.status_code, 424, response.text)
            self.assertIn("HTTP 502", response.json()["detail"])
            self.assertIn("(Firebase: INVALID_ARGUMENT)", response.json()["detail"])
            with Session(self.app.state.engine) as db:
                self.assertIsNotNone(db.get(PushSubscription, b["id"]))

    def test_cloudflare_relay_delivers_generic_production_push(self):
        a, b = self.alert_pair()
        token = "d" * 64
        variables = {
            "NARAHEM_PUSH_RELAY_URL": "https://relay.example.workers.dev/v1/push",
            "NARAHEM_PUSH_RELAY_TOKEN": "test-only-secret",
        }
        with patch.dict("os.environ", variables):
            registration = self.call(
                b,
                "PUT",
                "/api/push/subscription",
                {"provider": "apns", "token": token, "environment": "production"},
            )
            self.assertEqual(registration.status_code, 200, registration.text)
            with Session(self.app.state.engine) as db:
                encrypted = db.get(PushSubscription, b["id"]).token
                self.assertNotIn(token, encrypted)
                self.assertNotIn("production", encrypted)
            self.leave_home(a)
            with patch("narahem.push_service.httpx.Client") as client:
                connection = client.return_value.__enter__.return_value
                connection.post.return_value.status_code = 200
                connection.post.return_value.json.return_value = {
                    "acceptedByApns": True,
                    "apnsStatus": 200,
                }
                self.app.state.maintenance()
            call = connection.post.call_args
            self.assertEqual(call.args[0], variables["NARAHEM_PUSH_RELAY_URL"])
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-only-secret")
            payload = call.kwargs["json"]
            self.assertEqual(payload["deviceToken"], token)
            self.assertEqual(payload["environment"], "production")
            self.assertEqual(payload["intent"], "alert")
            self.assertNotIn("sound", payload)
            self.assertNotIn("body", payload)
            self.assertNotIn("record_id", payload)
            self.assertNotIn("12.3456789", repr(payload))
            self.assertNotIn("Private Home", repr(payload))
            with Session(self.app.state.engine) as db:
                self.assertEqual(db.query(PushDelivery).count(), 0)

    def test_cloudflare_find_phone_ringtone_intent_is_fixed_and_bounded(self):
        import uuid

        from narahem.push_service import deliver

        variables = {
            "NARAHEM_PUSH_RELAY_URL": "https://relay.example.workers.dev/v1/push",
            "NARAHEM_PUSH_RELAY_TOKEN": "server-only-test-token",
        }
        with patch.dict("os.environ", variables):
            from narahem.push_service import available_config

            with Session(self.app.state.engine) as db:
                conf = available_config(db.get(ServiceState, 1), self.app.state.cipher)
            with patch("narahem.push_service.httpx.Client") as client:
                conn = client.return_value.__enter__.return_value
                conn.post.return_value.status_code = 200
                conn.post.return_value.json.return_value = {"acceptedByApns": True}
                result = deliver(
                    "apns",
                    "production:" + "a" * 64,
                    "0" * 32,
                    uuid.uuid4().hex,
                    conf,
                    kind="find-phone",
                )
            self.assertEqual(result, "sent")
            payload = conn.post.call_args.kwargs["json"]
            self.assertEqual(payload["intent"], "find-phone")
            self.assertEqual(payload["deviceToken"], "a" * 64)
            self.assertEqual(payload["environment"], "production")
            self.assertLessEqual(payload["expiresInSeconds"], 120)
            self.assertNotIn("title", payload)
            self.assertNotIn("body", payload)
            self.assertNotIn("sound", payload)
            self.assertNotIn("command", repr(payload))
            self.assertNotIn("coordinates", repr(payload))

    def test_cloudflare_relay_failure_retries_without_dropping_subscription(self):
        a, b = self.alert_pair()
        vars = {
            "NARAHEM_PUSH_RELAY_URL": "https://relay.example.workers.dev/v1/push",
            "NARAHEM_PUSH_RELAY_TOKEN": "test-only-secret",
        }
        with patch.dict("os.environ", vars):
            self.call(
                b,
                "PUT",
                "/api/push/subscription",
                {"provider": "apns", "token": "c" * 64, "environment": "sandbox"},
            )
            self.leave_home(a)
            with patch("narahem.push_service.httpx.Client") as client:
                connection = client.return_value.__enter__.return_value
                connection.post.return_value.status_code = 502
                connection.post.return_value.json.return_value = {
                    "apnsStatus": 400,
                    "reason": "BadDeviceToken",
                }
                self.app.state.maintenance()
            with Session(self.app.state.engine) as db:
                self.assertEqual(db.query(PushDelivery).count(), 1)
                self.assertEqual(db.scalar(select(PushDelivery)).attempts, 1)
                self.assertIsNotNone(db.get(PushSubscription, b["id"]))

    def test_push_subscription_rejects_fcm_environment(self):
        a, b = self.pair()
        response = self.call(
            b,
            "PUT",
            "/api/push/subscription",
            {
                "provider": "fcm",
                "token": "synthetic-registration-token",
                "environment": "production",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_fcm_configuration_rejects_custom_token_endpoints(self):
        response = self.client.put(
            "/api/push/config",
            json={
                "fcm": {"project_id": "synthetic-project", "token_uri": "http://127.0.0.1/secret"}
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_native_account_login_uses_bearer_without_browser_csrf(self):
        client = TestClient(self.app, base_url=test_setup.PUBLIC)
        r = client.post(
            "/api/login",
            json={"email": test_setup.OWNER, "password": test_setup.PASSWORD, "native": True},
            headers={"X-NaraHem-Client": "native"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["access_token"]
        client.cookies.clear()
        self.assertEqual(
            client.get("/api/session", headers={"Authorization": f"Bearer {token}"}).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                "/api/logout", json={}, headers={"Authorization": f"Bearer {token}"}
            ).status_code,
            200,
        )

    def member(self):
        ident = secrets.token_hex(16)
        with Session(self.app.state.engine) as db:
            db.add(
                Account(
                    id=ident,
                    email="member@example.invalid",
                    username="member",
                    password=HASHER.hash(test_setup.PASSWORD),
                    status="active",
                    verified=True,
                    role="member",
                )
            )
            db.commit()
        client = TestClient(self.app, base_url=test_setup.PUBLIC)
        client.headers["Origin"] = test_setup.PUBLIC
        result = client.post(
            "/api/login", json={"email": "member@example.invalid", "password": test_setup.PASSWORD}
        )
        self.assertEqual(result.status_code, 200)
        client.headers["X-CSRF-Token"] = result.json()["csrf"]
        return ident, client

    def second_member(self, email, name):
        ident = secrets.token_hex(16)
        with Session(self.app.state.engine) as db:
            db.add(
                Account(
                    id=ident,
                    email=email,
                    username=name,
                    password=HASHER.hash(test_setup.PASSWORD),
                    status="active",
                    verified=True,
                    role="member",
                )
            )
            db.commit()
        client = TestClient(self.app, base_url=test_setup.PUBLIC)
        client.headers["Origin"] = test_setup.PUBLIC
        client.headers["X-CSRF-Token"] = client.post(
            "/api/login", json={"email": email, "password": test_setup.PASSWORD}
        ).json()["csrf"]
        return ident, client

    def test_device_activity_hidden_from_members_outside_location_audience(self):
        owner = self.bootstrap()
        viewer_id, viewer_client = self.second_member("viewer@example.invalid", "viewer")
        subject_id, subject_client = self.second_member("subject@example.invalid", "subject")
        viewer = self.register(viewer_client, viewer_id)
        subject = self.register(subject_client, subject_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, viewer, subject])
            ).status_code,
            200,
        )
        self.publish(subject)

        def row(client):
            return next(
                d for d in client.get("/api/devices").json()["devices"] if d["id"] == subject["id"]
            )

        # Default audience (everyone): the viewer may see activity times.
        self.assertTrue(row(viewer_client)["activity_visible"])
        self.assertIsNotNone(row(viewer_client)["last_location"])
        # Subject excludes everyone: the viewer loses activity metadata;
        # the owner account and the admin keep it.
        self.assertEqual(
            self.call(subject, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        hidden = row(viewer_client)
        self.assertFalse(hidden["activity_visible"])
        self.assertEqual(
            (hidden["seen"], hidden["last_location"], hidden["sequence"]), (None, None, None)
        )
        self.assertIsNotNone(row(subject_client)["last_location"])
        self.assertIsNotNone(row(self.client)["last_location"])
        # Re-adding the viewer restores visibility.
        self.assertEqual(
            self.call(
                subject, "PUT", "/api/sharing/audience", {"account_ids": [viewer_id]}
            ).status_code,
            200,
        )
        self.assertTrue(row(viewer_client)["activity_visible"])

    def audience_household(self):
        owner = self.bootstrap()
        viewer_id, viewer_client = self.second_member("viewer@example.invalid", "viewer")
        subject_id, subject_client = self.second_member("subject@example.invalid", "subject")
        viewer = self.register(viewer_client, viewer_id)
        subject = self.register(subject_client, subject_id)
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, viewer, subject])
            ).status_code,
            200,
        )
        return owner, viewer, subject

    def test_trip_events_follow_location_audience(self):
        owner, viewer, subject = self.audience_household()
        now = int(time.time() * 1000)
        trip = {
            "type": "trip_summary",
            "account_id": subject["account_id"],
            "started_at": now - 60000,
            "ended_at": now,
        }
        # Shared with everyone by default: the viewer receives the trip.
        shared = self.publish(subject, kind="event", data=trip, captured=now)
        self.assertEqual(
            self.call(viewer, "GET", f"/api/records/{shared['body']['id']}").status_code, 200
        )
        # Excluding the viewer removes access to that older trip as well.
        self.assertEqual(
            self.call(subject, "PUT", "/api/sharing/audience", {"account_ids": []}).status_code, 200
        )
        self.assertEqual(
            self.call(viewer, "GET", f"/api/records/{shared['body']['id']}").status_code, 404
        )
        # New trips sealed for the audience (own devices only) are accepted and unseen.
        private = self.publish(subject, kind="event", data=trip, recipients=[subject], captured=now)
        self.assertEqual(
            self.call(viewer, "GET", f"/api/records/{private['body']['id']}").status_code, 404
        )
        history = self.call(viewer, "GET", "/api/records?kind=event").json()["records"]
        self.assertNotIn(private["body"]["id"], {r["envelope"]["body"]["id"] for r in history})

    def test_member_never_receives_pending_device_approvals(self):
        self.bootstrap()
        pending = self.register()
        member_id, member_client = self.member()
        admin_listing = self.client.get("/api/devices")
        self.assertEqual(admin_listing.status_code, 200)
        self.assertTrue(admin_listing.json()["pairing_available"])
        self.assertIn(
            pending["id"],
            {
                device["id"]
                for device in admin_listing.json()["devices"]
                if device["status"] == "pending"
            },
        )

        response = member_client.get("/api/devices")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["pairing_available"])
        self.assertNotIn(pending["id"], {device["id"] for device in response.json()["devices"]})
        # Approved roster public identities remain readable for E2EE.
        self.assertTrue(
            any(device["status"] == "approved" for device in response.json()["devices"])
        )

    def test_email_code_approves_only_one_phone_and_revoke_frees_slot(self):
        owner = self.bootstrap()
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        reply = self.client.post("/api/enrollment/signer", json={})
        self.assertEqual(reply.status_code, 200, reply.text)
        service = reply.json()
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, service])
            ).status_code,
            200,
        )
        account, member_client = self.member()

        def register_phone():
            signature = SigningKey.generate()
            box = PrivateKey.generate()
            device_id = secrets.token_hex(16)
            registration = {
                "domain": "narahem.device.v1",
                "household": self.household,
                "id": device_id,
                "account_id": account,
                "signing_key": B64(signature.verify_key),
                "box_key": B64(box.public_key),
                "platform": "android",
            }
            result = member_client.post(
                "/api/devices/register",
                json={
                    "id": device_id,
                    "name": "Android phone",
                    "platform": "android",
                    "signing_key": registration["signing_key"],
                    "box_key": registration["box_key"],
                    "signature": B64(signature.sign(canonical(registration)).signature),
                },
            )
            self.assertEqual(result.status_code, 201, result.text)
            return device_id, result.json()["credential"]

        first, credential = register_phone()
        abandoned, _ = register_phone()
        # Pending phone enrollments are never manual approval requests.
        self.assertNotIn(
            first, {item["id"] for item in self.client.get("/api/devices").json()["devices"]}
        )
        self.assertNotIn(
            abandoned, {item["id"] for item in self.client.get("/api/devices").json()["devices"]}
        )
        self.assertNotIn(
            abandoned, {item["id"] for item in member_client.get("/api/devices").json()["devices"]}
        )
        self.assertEqual(
            member_client.post("/api/phones/code", json={"device_id": first}).status_code, 202
        )
        code = self.messages[-1][3].split("Enter ")[1][:6]
        self.assertEqual(
            member_client.post(
                "/api/phones/verify", json={"device_id": first, "code": code}
            ).status_code,
            200,
        )
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(ClientDevice, first).status, "approved")
            self.assertIsNone(
                db.get(ClientDevice, abandoned),
                "Phone verification clears abandoned pending registrations",
            )
        self.assertIn(
            first, {item["id"] for item in self.client.get("/api/devices").json()["devices"]}
        )
        second, _ = register_phone()
        response = member_client.post("/api/phones/code", json={"device_id": second})
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(ClientDevice, second))
        response = self.call({"credential": credential}, "POST", "/api/phones/self-revoke", {})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.call({"credential": credential}, "GET", "/api/device").status_code, 401
        )

    def test_new_verified_phone_prunes_old_revoked_device_from_signed_roster(self):
        owner = self.bootstrap()
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        service = self.client.post("/api/enrollment/signer", json={}).json()
        self.assertEqual(
            self.call(
                owner, "POST", "/api/roster", self.roster(owner, [owner, service])
            ).status_code,
            200,
        )
        account, member_client = self.member()

        def register_and_verify():
            signing = SigningKey.generate()
            box = PrivateKey.generate()
            device_id = secrets.token_hex(16)
            registration = {
                "domain": "narahem.device.v1",
                "household": self.household,
                "id": device_id,
                "account_id": account,
                "signing_key": B64(signing.verify_key),
                "box_key": B64(box.public_key),
                "platform": "ios",
            }
            request = member_client.post(
                "/api/devices/register",
                json={
                    "id": device_id,
                    "name": "iPhone",
                    "platform": "ios",
                    "signing_key": registration["signing_key"],
                    "box_key": registration["box_key"],
                    "signature": B64(signing.sign(canonical(registration)).signature),
                },
            )
            self.assertEqual(request.status_code, 201, request.text)
            self.assertEqual(
                member_client.post("/api/phones/code", json={"device_id": device_id}).status_code,
                202,
            )
            code = self.messages[-1][3].split("Enter ")[1][:6]
            response = member_client.post(
                "/api/phones/verify", json={"device_id": device_id, "code": code}
            )
            self.assertEqual(response.status_code, 200, response.text)
            return device_id

        old = register_and_verify()
        # Simulate a previous account-level revocation that invalidated the
        # old phone in the database without a signed roster reconciliation.
        with Session(self.app.state.engine) as db:
            db.get(ClientDevice, old).status = "revoked"
            db.commit()
        new = register_and_verify()
        with Session(self.app.state.engine) as db:
            revision = db.get(ServiceState, 1).revision
            devices = json.loads(db.get(RosterRevision, revision).payload)["devices"]
            ids = {device["id"] for device in devices}
            self.assertNotIn(old, ids)
            self.assertIn(new, ids)
            self.assertIn(service["id"], ids)
            self.assertEqual(db.get(ClientDevice, old).status, "revoked")
        self.assertEqual(self.call(owner, "GET", "/api/device").status_code, 200)

    def test_trusted_member_can_help_enroll_but_cannot_revoke_owner(self):
        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b])).status_code, 200
        )
        c = self.register()
        self.assertEqual(
            self.call(b, "POST", "/api/roster", self.roster(b, [a, b, c])).status_code, 200
        )
        self.assertEqual(
            self.call(b, "POST", "/api/roster", self.roster(b, [b, c])).status_code, 403
        )
        self.assertEqual(client.get("/api/storage").status_code, 403)
        self.assertEqual(client.get("/api/push/config").status_code, 403)

    def test_member_cannot_revoke_another_members_phone(self):
        a = self.bootstrap()
        helper, helper_client = self.member()
        b = self.register(helper_client, helper)
        other_id, other_client = self.second_member("other@example.invalid", "other")
        c = self.register(other_client, other_id)
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b, c])).status_code, 200
        )
        # Dropping another member's phone from the signed list is refused, and it stays approved.
        self.assertEqual(
            self.call(b, "POST", "/api/roster", self.roster(b, [a, b])).status_code, 403
        )
        self.assertEqual(self.call(c, "GET", "/api/records").status_code, 200)
        # The admin may.
        self.assertEqual(
            self.call(a, "POST", "/api/roster", self.roster(a, [a, b])).status_code, 200
        )
        self.assertEqual(self.call(c, "GET", "/api/records").status_code, 401)

    def test_account_revocation_blocks_reads_and_requires_signed_reconciliation(self):
        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        self.publish(a)
        self.assertEqual(
            self.client.post(f"/api/accounts/{member}/revoke", json={}).status_code, 200
        )
        with Session(self.app.state.engine) as db:
            entry = db.scalar(select(AuditEntry).where(AuditEntry.action == "account.revoked"))
            self.assertEqual(entry.actor_id, self.owner_id)
            self.assertEqual(entry.target_id, member)
        self.assertEqual(self.call(b, "GET", "/api/view").status_code, 401)
        self.assertEqual(
            self.call(a, "POST", "/api/records", self.record(a, recipients=[a, b])).status_code, 409
        )
        self.assertEqual(self.call(a, "POST", "/api/roster", self.roster(a, [a])).status_code, 200)
        self.publish(a)

    def test_delete_member_erases_data_denies_old_credentials_and_allows_reinvitation(self):
        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        owner_record = self.publish(a, kind="place")
        records = [self.publish(b, kind=kind) for kind in ("location", "event", "place", "profile")]
        denied_place_delete = self.record(
            b, kind="place", entity=records[2]["body"]["entity_id"], operation="delete"
        )
        self.assertEqual(self.call(b, "POST", "/api/records", denied_place_delete).status_code, 403)
        stale = self.record(b)
        old_confirmation = "synthetic-deleted-confirmation-token"
        with Session(self.app.state.engine) as db:
            db.add(
                Challenge(
                    id=digest(old_confirmation), account_id=member, expires=time.time() + 1800
                )
            )
            db.add(
                Outbox(
                    id=secrets.token_hex(16),
                    account_id=member,
                    payload="synthetic",
                    created=time.time(),
                )
            )
            db.add(
                Outbox(
                    id=secrets.token_hex(16),
                    account_id="req-" + digest("member@example.invalid")[:32],
                    payload="synthetic",
                    created=time.time(),
                )
            )
            db.add(PushSubscription(device_id=b["id"], provider="apns", token="synthetic"))
            db.add(
                PushDelivery(
                    id=secrets.token_hex(16),
                    device_id=a["id"],
                    record_id=records[0]["body"]["id"],
                    created=time.time(),
                    expires_at=time.time() + 3600,
                )
            )
            db.add(
                PushDelivery(
                    id=secrets.token_hex(16),
                    device_id=b["id"],
                    record_id=owner_record["body"]["id"],
                    created=time.time(),
                    expires_at=time.time() + 3600,
                )
            )
            db.commit()
        response = self.client.request("DELETE", f"/api/accounts/{member}", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["records_deleted"], 3)
        self.assertTrue(response.json()["membership_reconciliation_required"])
        self.assertEqual(client.get("/api/session").status_code, 401)
        self.assertEqual(self.call(b, "GET", "/api/view").status_code, 401)
        self.assertEqual(self.call(b, "POST", "/api/records", stale).status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/enrollment/verify", json={"token": old_confirmation}
            ).status_code,
            400,
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(Account, member))
            for model in (LoginSession, Challenge, ClientDevice):
                self.assertEqual(db.query(model).filter_by(account_id=member).count(), 0)
            self.assertEqual(db.query(Outbox).count(), 0)
            self.assertEqual(db.query(PushDelivery).count(), 0)
            self.assertIsNone(db.get(PushSubscription, b["id"]))
            self.assertEqual(db.query(RecordRecipient).filter_by(device_id=b["id"]).count(), 0)
            self.assertEqual(db.query(EncryptedRecord).count(), 2)
            self.assertEqual(db.query(LatestState).count(), 2)
            deletion = db.scalar(select(AuditEntry).where(AuditEntry.action == "account.deleted"))
            self.assertEqual(deletion.actor_id, self.owner_id)
            self.assertIsNone(deletion.target_id)
        self.assertEqual(
            self.call(a, "POST", "/api/records", self.record(a, recipients=[a, b])).status_code, 409
        )
        # Historical signed metadata remains, but a trusted owner can remove
        # the missing identity and surviving data still verifies/decrypts.
        self.assertEqual(self.call(a, "POST", "/api/roster", self.roster(a, [a])).status_code, 200)
        place = records[2]
        view = self.call(a, "GET", "/api/view").json()
        self.assertIn(place["body"]["id"], [x["id"] for x in view["records"]])
        self.publish(
            a,
            kind="place",
            entity=place["body"]["entity_id"],
            operation="delete",
            data={"deleted": True},
        )
        fetched = self.call(a, "GET", f"/api/records/{owner_record['body']['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.decrypt(a, fetched.json()["envelope"])
        self.assertEqual(
            self.client.post(
                "/api/invitations", json={"email": "member@example.invalid"}
            ).status_code,
            201,
        )
        token = test_setup.re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)
        self.assertEqual(
            self.client.post(
                "/api/enrollment/verify",
                json={"token": token, "username": "member", "password": test_setup.PASSWORD},
            ).status_code,
            200,
        )
        with Session(self.app.state.engine) as db:
            recreated = db.scalar(select(Account).where(Account.email == "member@example.invalid"))
            self.assertNotEqual(recreated.id, member)
            recreated_id = recreated.id
        self.assertEqual(client.get("/api/session").status_code, 401)
        self.assertEqual(self.call(b, "GET", "/api/view").status_code, 401)
        result = client.post(
            "/api/login", json={"email": "member@example.invalid", "password": test_setup.PASSWORD}
        )
        self.assertEqual(result.status_code, 200)
        client.headers["X-CSRF-Token"] = result.json()["csrf"]
        registration = dict(
            domain="narahem.device.v1", household=self.household, **self.identity(b)
        )
        registration["account_id"] = recreated_id
        response = client.post(
            "/api/devices/register",
            json=dict(
                id=b["id"],
                name="Old identity",
                signing_key=b["signing_key"],
                box_key=b["box_key"],
                signature=B64(b["signing"].sign(canonical(registration)).signature),
            ),
        )
        self.assertEqual(response.status_code, 409)
        new_device = self.register(client, recreated_id)
        self.assertEqual(self.call(new_device, "GET", "/api/view").status_code, 403)

    def test_delete_member_requires_owner_and_csrf_and_protects_owner(self):
        member, client = self.member()
        self.assertEqual(
            client.request("DELETE", f"/api/accounts/{member}", json={}).status_code, 403
        )
        self.assertEqual(
            self.client.request("DELETE", f"/api/accounts/{self.owner_id}", json={}).status_code,
            409,
        )
        csrf = self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(
            self.client.request("DELETE", f"/api/accounts/{member}", json={}).status_code, 403
        )
        self.client.headers["X-CSRF-Token"] = csrf
        self.assertEqual(
            self.client.request("DELETE", f"/api/accounts/{member}", json={}).status_code, 200
        )
        self.assertEqual(
            self.client.request("DELETE", f"/api/accounts/{member}", json={}).status_code, 404
        )

    def test_new_device_cannot_read_history_encrypted_before_approval(self):
        a = self.bootstrap()
        old = self.publish(a)
        b = self.register()
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        self.assertEqual(self.call(b, "GET", f"/api/records/{old['body']['id']}").status_code, 404)
        self.assertEqual(self.call(b, "GET", "/api/records").json()["records"], [])
        self.publish(a)
        self.assertEqual(len(self.call(b, "GET", "/api/records").json()["records"]), 1)

    def test_fcm_adapter_uses_fixed_google_hosts_and_generic_payload(self):
        a, b = self.alert_pair()
        private = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            .decode()
        )
        fcm = {
            "type": "service_account",
            "project_id": "synthetic-project",
            "private_key_id": "synthetic",
            "private_key": private,
            "client_email": "synthetic@synthetic-project.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self.assertEqual(self.client.put("/api/push/config", json={"fcm": fcm}).status_code, 200)
        self.call(
            b,
            "PUT",
            "/api/push/subscription",
            {"provider": "fcm", "token": "synthetic-registration-token"},
        )
        self.leave_home(a)
        from google.oauth2 import service_account

        def refresh(credentials, request):
            credentials.token = "synthetic-oauth-token"

        with (
            patch.object(service_account.Credentials, "refresh", refresh),
            patch("narahem.push_service.httpx.Client") as client,
        ):
            connection = client.return_value.__enter__.return_value
            connection.post.return_value.status_code = 200
            self.app.state.maintenance()
        call = connection.post.call_args
        self.assertEqual(
            call.args[0], "https://fcm.googleapis.com/v1/projects/synthetic-project/messages:send"
        )
        self.assertNotIn("Private Home", json.dumps(call.kwargs["json"]))
        # Data-only and high priority: the Android app wakes and shows the decrypted alert itself.
        message = call.kwargs["json"]["message"]
        self.assertNotIn("notification", message)
        self.assertEqual(
            (message["data"], message["android"]["priority"]), ({"intent": "alert"}, "HIGH")
        )
        self.assertEqual(call.kwargs["headers"]["authorization"], "Bearer synthetic-oauth-token")
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.query(PushDelivery).count(), 0)

    def test_signed_metadata_requires_exact_domain_and_integer_types(self):
        a = self.bootstrap()
        r = self.record(a)
        r["body"]["domain"] = "narahemXrecordYv1"
        r["signature"] = B64(a["signing"].sign(canonical(r["body"])).signature)
        self.assertEqual(self.call(a, "POST", "/api/records", r).status_code, 422)
        r = self.record(a)
        r["body"]["sequence"] = True
        self.assertEqual(self.call(a, "POST", "/api/records", r).status_code, 422)

    def test_low_order_encryption_key_cannot_enter_the_roster(self):
        signing = SigningKey.generate()
        ident = secrets.token_hex(16)
        value = dict(
            id=ident,
            account_id=self.owner_id,
            signing_key=B64(signing.verify_key),
            box_key=B64(bytes(32)),
        )
        registration = dict(domain="narahem.device.v1", household=self.household, **value)
        result = self.client.post(
            "/api/devices/register",
            json=dict(
                id=ident,
                name="Invalid encryption identity",
                signing_key=value["signing_key"],
                box_key=value["box_key"],
                signature=B64(signing.sign(canonical(registration)).signature),
            ),
        )
        self.assertEqual(result.status_code, 422)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(ClientDevice, ident))

    def test_restart_keeps_accounts_and_requires_matching_key(self):
        self.app.state.initialize()
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(Account, self.owner_id).email, test_setup.OWNER)
        from cryptography.fernet import Fernet

        (self.path / "server.key").write_bytes(Fernet.generate_key())
        wrong = create_app(self.db_url, self.path, test_setup.PUBLIC, mail_worker=False)
        with self.assertRaises(RuntimeError):
            wrong.state.initialize()


if __name__ == "__main__":
    unittest.main()
