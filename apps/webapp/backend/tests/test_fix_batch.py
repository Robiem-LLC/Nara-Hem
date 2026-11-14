import secrets
import time
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem.app import HASHER
from narahem.models import Account, AccountApproval, EnrollmentClaim
from tests import test_relay as relay
from tests.test_setup import PASSWORD, PUBLIC


class FixBatchTests(unittest.TestCase):
    for helper in (
        "setUp",
        "start",
        "tearDown",
        "setup_owner",
        "login",
        "configure",
        "register",
        "identity",
        "call",
        "roster",
        "bootstrap",
        "pair",
        "record",
        "publish",
        "decrypt",
        "member",
    ):
        locals()[helper] = getattr(relay.RelayTests, helper)

    def test_invited_account_uses_email_link_without_second_approval(self):
        email = "direct@example.invalid"
        import re

        self.assertEqual(
            self.client.post("/api/invitations", json={"email": email}).status_code, 201
        )
        token = re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)
        response = self.client.post(
            "/api/enrollment/verify",
            json={"token": token, "username": "Direct", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["device_approval_required"])
        self.assertEqual(self.client.get("/api/enrollment/claims").json()["claims"], [])
        self.assertEqual(
            self.client.post(
                "/api/enrollment/claim",
                json={"email": email, "username": "direct", "password": PASSWORD},
            ).status_code,
            410,
        )
        anon = TestClient(self.app, base_url=PUBLIC)
        anon.headers["Origin"] = PUBLIC
        login = anon.post("/api/login", json={"email": email, "password": PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        anon.headers["X-CSRF-Token"] = login.json()["csrf"]
        session = anon.get("/api/session").json()
        self.assertTrue(session["verified"])
        self.assertTrue(session["email_verified"])
        self.assertEqual(session["username"], "Direct")
        changed = anon.put("/api/account/username", json={"username": "Alex"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["username"], "Alex")
        self.assertEqual(anon.get("/api/session").json()["username"], "Alex")
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == email))
            self.assertTrue(member.verified)
            self.assertIsNone(db.get(AccountApproval, member.id))
        self.assertEqual(
            self.client.post(
                "/api/enrollment/verify", json={"token": token, "password": PASSWORD}
            ).status_code,
            400,
        )

    def test_old_claim_route_cannot_create_accounts_or_override_invitation(self):
        email = "retry@example.invalid"
        self.assertEqual(
            self.client.post("/api/invitations", json={"email": email}).status_code, 201
        )
        anon = TestClient(self.app, base_url=PUBLIC)
        anon.headers["Origin"] = PUBLIC
        response = anon.post(
            "/api/enrollment/claim",
            json={"email": email, "username": "mistake", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 410)
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == email))
            self.assertEqual(member.status, "pending")
            self.assertIsNone(member.password)

    def test_admin_approves_or_rejects_a_legacy_setup_claim(self):
        # New claims are refused (410 above), but a database from an older version may still
        # hold some; an administrator can approve or reject those.
        claims = {}
        with Session(self.app.state.engine) as db:
            for email, username in (
                ("approve@example.invalid", "Approved"),
                ("reject@example.invalid", "Rejected"),
            ):
                self.assertEqual(
                    self.client.post("/api/invitations", json={"email": email}).status_code, 201
                )
                account = db.scalar(select(Account).where(Account.email == email))
                claims[username] = secrets.token_hex(16)
                db.add(
                    EnrollmentClaim(
                        id=claims[username],
                        account_id=account.id,
                        username=username,
                        password_hash=HASHER.hash(PASSWORD),
                        created=time.time(),
                        expires=time.time() + 600,
                    )
                )
            db.commit()
        listed = {c["id"] for c in self.client.get("/api/enrollment/claims").json()["claims"]}
        self.assertEqual(listed, set(claims.values()))

        approved = self.client.post(f"/api/enrollment/claims/{claims['Approved']}/approve", json={})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json(), {"approved": True, "device_approval_required": True})
        rejected = self.client.request(
            "DELETE", f"/api/enrollment/claims/{claims['Rejected']}", json={}
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json(), {"removed": True})

        self.assertEqual(self.client.get("/api/enrollment/claims").json()["claims"], [])
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == "approve@example.invalid"))
            self.assertEqual((member.status, member.username), ("active", "Approved"))
            self.assertIsNotNone(db.get(AccountApproval, member.id))
            waiting = db.scalar(select(Account).where(Account.email == "reject@example.invalid"))
            self.assertEqual(waiting.status, "pending")
        # An approved claim cannot be approved twice.
        again = self.client.post(f"/api/enrollment/claims/{claims['Approved']}/approve", json={})
        self.assertEqual(again.status_code, 404)

    def test_place_state_guard_rejects_two_writers_using_same_snapshot(self):
        a, b = self.pair()
        token = self.call(a, "GET", "/api/places/manifest").json()["token"]
        first = self.record(a, kind="place")
        second = self.record(b, kind="place")
        self.assertEqual(
            self.call(a, "POST", "/api/records", first, {"X-Places-State": token}).status_code, 201
        )
        self.assertEqual(
            self.call(b, "POST", "/api/records", second, {"X-Places-State": token}).status_code, 409
        )
        self.assertEqual(len(self.call(a, "GET", "/api/places/manifest").json()["places"]), 1)

    def test_place_manifest_lists_versions_without_plaintext_places(self):
        a = self.bootstrap()
        record = self.publish(
            a, kind="place", data={"name": "Private Home", "lat": 40, "lon": -74, "radius": 100}
        )
        manifest = self.call(a, "GET", "/api/places/manifest").json()
        self.assertEqual(
            manifest["places"],
            [
                {
                    "id": record["body"]["entity_id"],
                    "record_id": record["body"]["id"],
                    "operation": "upsert",
                }
            ],
        )
        self.assertNotIn("Private Home", str(manifest))
        self.assertNotIn("radius", str(manifest))

    def test_find_phone_requires_opt_in_owner_signature_and_real_ack(self):
        import base64
        import time

        from narahem.models import FindPhoneCommand

        a, b = self.pair()
        now = int(time.time())

        def command(action="ring", ident=None, expires=None):
            value = dict(
                domain="narahem.find-phone.v1",
                household=self.household,
                id=ident or secrets.token_hex(16),
                issuer=a["id"],
                target=b["id"],
                action=action,
                issued_at=now,
                expires_at=expires or now + 120,
            )
            from narahem.data_service import canonical

            return {
                "body": value,
                "signature": base64.b64encode(
                    a["signing"].sign(canonical(value)).signature
                ).decode(),
            }

        first = command()
        self.assertEqual(self.call(a, "POST", "/api/find-phone/commands", first).status_code, 409)
        self.assertEqual(
            self.call(
                b, "PUT", "/api/find-phone/capability", {"enabled": True, "platform": "android"}
            ).status_code,
            200,
        )
        self.assertEqual(self.call(a, "POST", "/api/find-phone/commands", first).status_code, 201)
        self.assertEqual(self.call(b, "GET", "/api/find-phone/command").json()["command"], first)
        self.assertEqual(
            self.client.get("/api/find-phone/status/" + b["id"]).json()["status"], "pending"
        )
        self.assertEqual(
            self.call(
                a,
                "POST",
                "/api/find-phone/report",
                {"command_id": first["body"]["id"], "status": "ringing"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.call(
                b,
                "POST",
                "/api/find-phone/report",
                {"command_id": first["body"]["id"], "status": "ringing"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/find-phone/status/" + b["id"]).json()["status"], "ringing"
        )
        # Repeating the exact signed command is idempotent, not another alarm request.
        self.assertEqual(
            self.call(a, "POST", "/api/find-phone/commands", first).json()["status"], "ringing"
        )
        stopped = command("stop")
        self.call(a, "POST", "/api/find-phone/commands", stopped)
        self.assertEqual(
            self.call(b, "GET", "/api/find-phone/command").json()["command"]["body"]["action"],
            "stop",
        )
        self.call(
            b,
            "POST",
            "/api/find-phone/report",
            {"command_id": stopped["body"]["id"], "status": "stopped", "reason": "remote_stop"},
        )
        self.assertIsNone(self.call(b, "GET", "/api/find-phone/command").json()["command"])
        self.assertEqual(
            self.call(a, "POST", "/api/find-phone/commands", command(expires=now - 1)).status_code,
            422,
        )
        with Session(self.app.state.engine) as db:
            row = db.get(FindPhoneCommand, stopped["body"]["id"])
            self.assertEqual(row.status, "stopped")

    def test_member_cannot_issue_remote_alarm(self):
        import base64
        import time

        from narahem.data_service import canonical

        a = self.bootstrap()
        member, client = self.member()
        b = self.register(client, member)
        self.call(a, "POST", "/api/roster", self.roster(a, [a, b]))
        self.call(a, "PUT", "/api/find-phone/capability", {"enabled": True, "platform": "android"})
        now = int(time.time())
        body = dict(
            domain="narahem.find-phone.v1",
            household=self.household,
            id=secrets.token_hex(16),
            issuer=b["id"],
            target=a["id"],
            action="ring",
            issued_at=now,
            expires_at=now + 60,
        )
        request = {
            "body": body,
            "signature": base64.b64encode(b["signing"].sign(canonical(body)).signature).decode(),
        }
        self.assertEqual(self.call(b, "POST", "/api/find-phone/commands", request).status_code, 403)
