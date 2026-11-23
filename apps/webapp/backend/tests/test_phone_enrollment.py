import json
import os
import secrets
import smtplib
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from nacl.public import PrivateKey
from nacl.signing import SigningKey
from sqlalchemy.orm import Session

from narahem import mobile_enrollment, review_mode, texting
from narahem.data_service import canonical
from narahem.models import Account, ClientDevice, Outbox, PhoneChallenge, Settings
from tests import test_relay, test_setup

B64 = test_relay.B64


class FailingMail(list):
    """A mail log whose delivery always fails, like an unreachable SMTP server."""

    def append(self, item):
        raise smtplib.SMTPException("Mail server unavailable")


class PhoneEnrollmentTests(unittest.TestCase):
    """Phones joining by emailed code, and phones being revoked by their owner or the admin."""

    setUp = test_relay.RelayTests.setUp
    start = test_relay.RelayTests.start
    tearDown = test_relay.RelayTests.tearDown
    setup_owner = test_relay.RelayTests.setup_owner
    login = test_relay.RelayTests.login
    configure = test_relay.RelayTests.configure
    register = test_relay.RelayTests.register
    identity = test_relay.RelayTests.identity
    call = test_relay.RelayTests.call
    roster = test_relay.RelayTests.roster
    bootstrap = test_relay.RelayTests.bootstrap
    member = test_relay.RelayTests.member

    def enable_phone_enrollment(self):
        """Trusts the admin browser, tests mail and adds the enrollment signer to the roster."""
        owner = self.bootstrap()
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        service = self.client.post("/api/enrollment/signer", json={}).json()
        reply = self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, service]))
        self.assertEqual(reply.status_code, 200, reply.text)
        return owner, service

    def register_phone(self, client, account, platform="android"):
        signing, box = SigningKey.generate(), PrivateKey.generate()
        device_id = secrets.token_hex(16)
        registration = {
            "domain": "narahem.device.v1",
            "household": self.household,
            "id": device_id,
            "account_id": account,
            "signing_key": B64(signing.verify_key),
            "box_key": B64(box.public_key),
            "platform": platform,
        }
        reply = client.post(
            "/api/devices/register",
            json={
                "id": device_id,
                "name": "Phone",
                "platform": platform,
                "signing_key": registration["signing_key"],
                "box_key": registration["box_key"],
                "signature": B64(signing.sign(canonical(registration)).signature),
            },
        )
        self.assertEqual(reply.status_code, 201, reply.text)
        return device_id, reply.json()["credential"]

    def emailed_code(self):
        return self.messages[-1][3].split("Enter ")[1][:6]

    def joined_member_phone(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        device, credential = self.register_phone(client, account)
        self.assertEqual(
            client.post("/api/phones/code", json={"device_id": device}).status_code, 202
        )
        reply = client.post(
            "/api/phones/verify", json={"device_id": device, "code": self.emailed_code()}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        return account, client, device, credential

    def test_a_phone_only_member_gets_the_code_by_text(self):
        texts = []
        self.enable_phone_enrollment()

        def send(textbelt, key, phone, message):
            texts.append((phone, message))
            return 9

        with (
            patch.object(texting.Textbelt, "quota", lambda textbelt, key: 10),
            patch.object(texting.Textbelt, "send", send),
        ):
            on = self.client.put("/api/texting", json={"key": "synthetic-key"}).json()
            self.assertTrue(on["enabled"])
            account, client = self.member()
            with Session(self.app.state.engine) as db:
                member = db.get(Account, account)
                member.email, member.phone = None, "+14155550123"
                db.commit()
            device, _ = self.register_phone(client, account)
            mails = len(self.messages)
            reply = client.post("/api/phones/code", json={"device_id": device})
            self.assertEqual(reply.status_code, 202, reply.text)
            self.assertEqual(len(self.messages), mails, "no email for a phone-only member")
            phone, message = texts[-1]
            self.assertEqual(phone, "+14155550123")
            code = message.split("code:\n")[1][:6]
            reply = client.post("/api/phones/verify", json={"device_id": device, "code": code})
            self.assertEqual(reply.status_code, 200, reply.text)

    def signed_in(self, contact):
        """Returns a new client signed in with the contact and the test password, or None."""
        client = TestClient(self.app, base_url=test_setup.PUBLIC)
        client.headers["Origin"] = test_setup.PUBLIC
        result = client.post("/api/login", json={"email": contact, "password": test_setup.PASSWORD})
        if result.status_code != 200:
            return None
        client.headers["X-CSRF-Token"] = result.json()["csrf"]
        return client

    def test_an_invited_number_registers_in_the_app_and_one_code_confirms_it(self):
        texts = []
        self.enable_phone_enrollment()

        def send(textbelt, key, phone, message):
            texts.append((phone, message))
            return 9

        with (
            patch.object(texting.Textbelt, "quota", lambda textbelt, key: 10),
            patch.object(texting.Textbelt, "send", send),
        ):
            self.client.put("/api/texting", json={"key": "synthetic-key"})
            invited = self.client.post("/api/invitations", json={"email": "(415) 555-0123"})
            self.assertEqual(invited.status_code, 201, invited.text)
            self.assertIn("Create your account using", texts[-1][1])
            app = TestClient(self.app, base_url=test_setup.PUBLIC)
            app.headers["Origin"] = test_setup.PUBLIC
            form = {"email": "415-555-0123", "password": test_setup.PASSWORD}
            # Someone else who knows the number registers first...
            first = app.post("/api/enrollment/register", json={**form, "username": "Not Them"})
            self.assertEqual(first.status_code, 201, first.text)
            squatter = self.signed_in("+14155550123")
            session = squatter.get("/api/session").json()
            self.assertFalse(session["verified"], "unconfirmed until the code")
            # ...but registering again replaces them and signs them out.
            again = app.post("/api/enrollment/register", json={**form, "username": "  John   Doe "})
            self.assertEqual(again.status_code, 201, again.text)
            self.assertEqual(squatter.get("/api/session").status_code, 401)
            member = self.signed_in("415-555-0123")
            me = member.get("/api/session").json()
            self.assertEqual((me["username"], me["verified"]), ("John Doe", False))
            device, credential = self.register_phone(member, me["id"])
            # The waiting phone can see where it stands, but not the household.
            bearer = {"Authorization": f"Bearer {credential}"}
            own = member.get("/api/device", headers=bearer)
            self.assertEqual((own.status_code, own.json()["status"]), (200, "pending"), own.text)
            self.assertEqual(member.get("/api/roster", headers=bearer).status_code, 401)
            self.assertEqual(
                member.post("/api/phones/code", json={"device_id": device}).status_code, 202
            )
            phone, message = texts[-1]
            self.assertEqual(phone, "+14155550123")
            code = message.split("code:\n")[1][:6]
            reply = member.post("/api/phones/verify", json={"device_id": device, "code": code})
            self.assertEqual(reply.status_code, 200, reply.text)
            # The one code approved the phone and confirmed the account.
            self.assertTrue(member.get("/api/session").json()["verified"])
            # Now it's taken: registering again, or registering the admin, is refused.
            taken = app.post("/api/enrollment/register", json={**form, "username": "Someone"})
            self.assertEqual(taken.status_code, 404)
            owner = app.post(
                "/api/enrollment/register",
                json={**form, "email": test_setup.OWNER, "username": "Someone"},
            )
            self.assertEqual(owner.status_code, 404)

    def test_usernames_are_one_or_two_words(self):
        self.enable_phone_enrollment()
        self.client.post("/api/invitations", json={"email": "kim@example.invalid"})
        app = TestClient(self.app, base_url=test_setup.PUBLIC)
        app.headers["Origin"] = test_setup.PUBLIC
        form = {"email": "kim@example.invalid", "password": test_setup.PASSWORD}
        for name in ("John Q Doe", "ab", "J@hn Doe"):
            reply = app.post("/api/enrollment/register", json={**form, "username": name})
            self.assertEqual(reply.status_code, 422, name)
        for name in ("Kim", "Åsa O'Neil", "kim.lee-2"):
            reply = app.post("/api/enrollment/register", json={**form, "username": name})
            self.assertEqual(reply.status_code, 201, name)
        # An invited email address registers the same way; its code comes by email.
        member = self.signed_in("kim@example.invalid")
        me = member.get("/api/session").json()
        device, _ = self.register_phone(member, me["id"])
        self.assertEqual(
            member.post("/api/phones/code", json={"device_id": device}).status_code, 202
        )
        self.assertEqual(self.messages[-1][1], "kim@example.invalid")
        reply = member.post(
            "/api/phones/verify", json={"device_id": device, "code": self.emailed_code()}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertTrue(member.get("/api/session").json()["verified"])

    def test_signer_needs_a_trusted_admin_browser_and_a_stable_key(self):
        reply = self.client.post("/api/enrollment/signer", json={})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("not yet trusted", reply.json()["detail"])
        self.bootstrap()
        first = self.client.post("/api/enrollment/signer", json={}).json()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first, self.client.post("/api/enrollment/signer", json={}).json())
        with Session(self.app.state.engine) as db:
            db.get(ClientDevice, first["id"]).signing_key = B64(SigningKey.generate().verify_key)
            db.commit()
        reply = self.client.post("/api/enrollment/signer", json={})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("key mismatch", reply.json()["detail"])

    def test_codes_need_an_active_signer_and_working_mail(self):
        owner = self.bootstrap()
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        reply = client.post("/api/phones/code", json={"device_id": device})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("activate email enrollment", reply.json()["detail"])
        service = self.client.post("/api/enrollment/signer", json={}).json()
        self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, service]))
        reply = client.post("/api/phones/code", json={"device_id": device})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("configure and test email", reply.json()["detail"])
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        self.messages = FailingMail()
        reply = client.post("/api/phones/code", json={"device_id": device})
        self.assertEqual(reply.status_code, 424)

    def test_review_accounts_get_the_fixed_code_and_nothing_is_sent(self):
        owner = self.bootstrap()
        service = self.client.post("/api/enrollment/signer", json={}).json()
        self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, service]))
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        review = {review_mode.CODE: "246810", review_mode.ACCOUNTS: "Review@Demo.example"}
        with patch.dict(os.environ, review):
            self.assertIn("REVIEW MODE IS ON", review_mode.check())
            reply = client.post("/api/phones/code", json={"device_id": device})
            self.assertEqual(reply.status_code, 409, "member@example.invalid is not listed")
        review[review_mode.ACCOUNTS] = "review@demo.example, @EXAMPLE.invalid"
        with patch.dict(os.environ, review):
            mails = len(self.messages)
            reply = client.post("/api/phones/code", json={"device_id": device})
            self.assertEqual(reply.status_code, 202, reply.text)
            self.assertEqual(len(self.messages), mails, "nothing is emailed")
            wrong = client.post("/api/phones/verify", json={"device_id": device, "code": "135790"})
            self.assertEqual(wrong.status_code, 403)
            reply = client.post("/api/phones/verify", json={"device_id": device, "code": "246810"})
            self.assertEqual(reply.status_code, 200, reply.text)
        with patch.dict(os.environ, {review_mode.CODE: "12345"}):
            with self.assertRaises(ValueError):
                review_mode.check()
        with patch.dict(os.environ, {review_mode.CODE: "", review_mode.ACCOUNTS: ""}):
            self.assertIsNone(review_mode.check())

    def test_signer_missing_from_the_latest_roster_blocks_codes(self):
        owner, service = self.enable_phone_enrollment()
        self.call(owner, "POST", "/api/roster", self.roster(owner, [owner]))
        # Removing it from the roster revokes it; this guards against the two disagreeing.
        with Session(self.app.state.engine) as db:
            db.get(ClientDevice, service["id"]).status = "approved"
            db.commit()
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        reply = client.post("/api/phones/code", json={"device_id": device})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("not in the signed roster", reply.json()["detail"])

    def test_only_the_owners_pending_phone_can_get_a_code(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        web, _ = self.register_phone(client, account, platform="web")
        for device_id in (web, "f" * 32):
            reply = client.post("/api/phones/code", json={"device_id": device_id})
            self.assertEqual(reply.status_code, 403)
        phone, _ = self.register_phone(client, account)
        reply = self.client.post("/api/phones/code", json={"device_id": phone})
        self.assertEqual(reply.status_code, 403)

    def test_wrong_codes_count_down_and_then_discard_the_phone(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        client.post("/api/phones/code", json={"device_id": device})
        right = self.emailed_code()
        wrong = f"{(int(right) + 1) % 1000000:06d}"
        for _ in range(4):
            reply = client.post("/api/phones/verify", json={"device_id": device, "code": wrong})
            self.assertEqual(reply.json()["detail"], "Code rejected. Try again.")
        reply = client.post("/api/phones/verify", json={"device_id": device, "code": wrong})
        self.assertEqual(reply.json()["detail"], "Code rejected. Registration discarded.")
        reply = client.post("/api/phones/verify", json={"device_id": device, "code": right})
        self.assertEqual(reply.status_code, 403)

    def test_expired_codes_and_unknown_phones_are_refused(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        reply = client.post("/api/phones/verify", json={"device_id": device, "code": "123456"})
        self.assertIn("expired or exhausted", reply.json()["detail"])
        reply = client.post("/api/phones/verify", json={"device_id": "e" * 32, "code": "123456"})
        self.assertEqual(reply.status_code, 403)
        web, _ = self.register_phone(client, account, platform="web")
        reply = client.post("/api/phones/verify", json={"device_id": web, "code": "123456"})
        self.assertEqual(reply.status_code, 409)

    def test_a_second_phone_cannot_finish_after_the_first_joined(self):
        account, client, _, _ = self.joined_member_phone()
        second, _ = self.register_phone(client, account)
        reply = client.post("/api/phones/verify", json={"device_id": second, "code": "123456"})
        self.assertEqual(reply.json()["detail"], "Another phone is already registered")

    def test_unfinished_registration_can_be_cancelled_by_its_owner_only(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        device, _ = self.register_phone(client, account)
        reply = self.client.request("DELETE", "/api/phones/pending", json={"device_id": device})
        self.assertEqual(reply.status_code, 404)
        reply = client.request("DELETE", "/api/phones/pending", json={"device_id": device})
        self.assertEqual(reply.json(), {"discarded": True})
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(ClientDevice, device))

    def test_self_revoke_needs_an_approved_phone_credential(self):
        owner, service = self.enable_phone_enrollment()
        reply = self.client.post("/api/phones/self-revoke", json={})
        self.assertEqual(reply.status_code, 401)
        reply = self.call(owner, "POST", "/api/phones/self-revoke", {})
        self.assertEqual(reply.status_code, 403)

    def test_admin_revokes_a_member_phone_and_the_member_is_emailed(self):
        account, _, device, credential = self.joined_member_phone()
        owner_phone = self.client.post(f"/api/phones/{'d' * 32}/revoke", json={})
        self.assertEqual(owner_phone.status_code, 404)
        reply = self.client.post(f"/api/phones/{device}/revoke", json={})
        self.assertEqual(reply.json(), {"revoked": True, "notification_queued": True})
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(ClientDevice, device).status, "revoked")
            self.assertTrue(db.query(Outbox).filter_by(account_id="p:" + account).count())
        reply = self.client.post(f"/api/phones/{device}/revoke", json={})
        self.assertEqual(reply.status_code, 409)

    def test_admin_cannot_revoke_an_admin_phone_here(self):
        self.enable_phone_enrollment()
        with Session(self.app.state.engine) as db:
            owner = db.get(Account, self.owner_id)
            owner_phone, _ = self.register_phone(self.client, owner.id)
        reply = self.client.post(f"/api/phones/{owner_phone}/revoke", json={})
        self.assertEqual(reply.status_code, 403)

    def test_revocation_without_mail_is_recorded_but_not_emailed(self):
        _, _, _, credential = self.joined_member_phone()
        with Session(self.app.state.engine) as db:
            db.get(Settings, 1).smtp = None
            db.commit()
        reply = self.call({"credential": credential}, "POST", "/api/phones/self-revoke", {})
        self.assertEqual(reply.json(), {"revoked": True, "notification_queued": False})

    def test_cleanup_removes_abandoned_registrations_and_expired_codes(self):
        self.enable_phone_enrollment()
        account, client = self.member()
        stale, _ = self.register_phone(client, account)
        expired, _ = self.register_phone(client, account)
        web, _ = self.register_phone(client, account, platform="web")
        with Session(self.app.state.engine) as db:
            for device_id in (stale, web):
                db.get(ClientDevice, device_id).created = time.time() - 7200
            db.add(
                PhoneChallenge(
                    device_id=expired,
                    account_id=account,
                    proof="x",
                    created=time.time() - 900,
                    expires=time.time() - 300,
                    attempts=0,
                )
            )
            db.commit()
        with patch.object(mobile_enrollment, "_last_cleanup", 0.0):
            mobile_enrollment.cleanup(self.app.state.engine)
            # A second call within the interval does nothing.
            mobile_enrollment.cleanup(self.app.state.engine)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(ClientDevice, stale))
            self.assertIsNone(db.get(ClientDevice, expired))
            self.assertIsNotNone(db.get(ClientDevice, web))
            self.assertEqual(db.query(PhoneChallenge).count(), 0)

    def test_unreadable_registrations_count_as_legacy_phones(self):
        device = ClientDevice(registration="not json")
        self.assertEqual(mobile_enrollment.platform(device), "legacy")
        device.registration = json.dumps({"platform": "ios"})
        self.assertEqual(mobile_enrollment.platform(device), "ios")


if __name__ == "__main__":
    unittest.main()
