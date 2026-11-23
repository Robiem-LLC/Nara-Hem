import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from narahem import texting
from narahem.app import create_app
from narahem.models import Account, Base, ContactChange, Settings

PASSWORD = "synthetic long test password"
PUBLIC = "https://narahem.example.invalid"
OWNER = "owner@example.invalid"
KIM = "+14155550123"
MAIL = {
    "host": "smtp.example.invalid",
    "port": 587,
    "mode": "starttls",
    "username": "synthetic",
    "password": "smtp-test-secret",
    "sender": OWNER,
}


APP_LINKS = {
    "NARAHEM_IOS_APP_URL": "https://apps.example.invalid/ios",
    "NARAHEM_ANDROID_APP_URL": "https://apps.example.invalid/android.apk",
}


class FakeTextbelt:
    """Stands in for Textbelt: a key with credit, and every text it was asked to send."""

    def __init__(self):
        """Starts with one good key and no texts."""
        self.keys = {"good-textbelt-key": 40, "empty-textbelt-key": 0}
        self.sent, self.refuse = [], None

    def quota(self, key):
        """Returns the key's credit, as Textbelt's free quota check does."""
        if key not in self.keys:
            raise texting.TextingError("Invalid API key")
        return self.keys[key]

    def send(self, key, phone, message):
        """Records the text and spends one credit."""
        if self.refuse:
            raise texting.TextingError(texting.describe(self.refuse), self.refuse)
        self.sent.append((phone, message))
        self.keys[key] -= 1
        return self.keys[key]


class TextingTests(unittest.TestCase):
    """Text messages: the settings card, phone invitations, sign-in and codes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db_url = os.environ.get("NARAHEM_TEST_DATABASE_URL", f"sqlite:///{self.path}/test.db")
        if os.environ.get("NARAHEM_TEST_DATABASE_URL"):
            engine = create_engine(self.db_url)
            Base.metadata.drop_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
            engine.dispose()
        self.mail, self.texts = [], FakeTextbelt()
        self.app = create_app(
            self.db_url,
            self.path,
            PUBLIC,
            mailer=lambda *args: self.mail.append(args),
            mail_worker=False,
            texter=self.texts,
        )
        self.client = TestClient(self.app, base_url=PUBLIC)
        self.client.__enter__()
        self.client.headers["Origin"] = PUBLIC
        token = (self.path / "bootstrap-token").read_text()
        self.client.post(
            "/api/setup",
            json={
                "token": token,
                "household": "Test household",
                "email": OWNER,
                "password": PASSWORD,
            },
        )
        self.sign_in(OWNER)
        self.client.put("/api/mail", json=MAIL)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def sign_in(self, who, password=PASSWORD):
        result = self.client.post("/api/login", json={"email": who, "password": password})
        if result.status_code == 200:
            self.client.headers["X-CSRF-Token"] = result.json()["csrf"]
        return result

    def turn_on(self, key="good-textbelt-key"):
        return self.client.put("/api/texting", json={"key": key}).json()

    def link(self, message):
        return re.search(r"#verify=([^&\s]+)", message).group(1)

    def test_a_saved_key_is_checked_and_never_shown(self):
        off = self.client.get("/api/texting").json()
        self.assertFalse(off["enabled"])
        self.assertIsNone(off["source"])
        status = self.turn_on()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["source"], "settings")
        self.assertEqual(status["quota"], 40)
        self.assertEqual(status["key_hint"], "••••••••-key")
        self.assertNotIn("good-textbelt-key", str(self.client.get("/api/texting").json()))
        with Session(self.app.state.engine) as db:
            self.assertNotIn("good-textbelt-key", db.get(Settings, 1).sms)
        empty = self.turn_on("empty-textbelt-key")
        self.assertFalse(empty["enabled"])
        self.assertIn("no texts left", empty["error"])
        wrong = self.turn_on("wrong-textbelt-key")
        self.assertFalse(wrong["enabled"])
        self.assertEqual(wrong["error"], "Invalid API key")
        self.assertFalse(self.turn_on("")["enabled"])

    def test_the_environment_key_wins(self):
        self.turn_on("empty-textbelt-key")
        with patch.dict(os.environ, {texting.ENVIRONMENT_KEY: "good-textbelt-key"}):
            status = self.client.post("/api/texting/check", json={}).json()
            self.assertEqual(status["source"], "environment")
            self.assertTrue(status["enabled"])
            refused = self.client.put("/api/texting", json={"key": "other-key"})
            self.assertEqual(refused.status_code, 409)
            self.assertIn("NARAHEM_TEXTBELT_KEY", refused.json()["detail"])

    def test_a_phone_invitation_is_texted_and_the_number_signs_in(self):
        self.turn_on()
        invited = self.client.post("/api/invitations", json={"email": "(415) 555-0123"})
        self.assertEqual(invited.status_code, 201, invited.text)
        self.assertEqual(invited.json()["channels"], ["text"])
        phone, message = self.texts.sent[-1]
        self.assertEqual(phone, KIM)
        # Textbelt refuses links it hasn't approved, so the text names the server instead.
        self.assertEqual(
            message,
            "You have been invited to Test household family locator.\n"
            "Please download Nära Hem (Nara Hem) off your devices official store.\n"
            "Create your account using narahem<.>example<.>invalid and your phone number.",
        )
        # The app registers the account; the text carries no link or code.
        verified = self.client.post(
            "/api/enrollment/register",
            json={"email": "(415) 555-0123", "username": "kim", "password": PASSWORD},
        )
        self.assertEqual(verified.status_code, 201, verified.text)
        self.client.post("/api/logout", json={})
        self.assertEqual(self.sign_in("415-555-0123").status_code, 200)
        session = self.client.get("/api/session").json()
        self.assertEqual(session["phone"], KIM)
        self.assertIsNone(session["email"])

    def test_the_administrator_can_resend_the_invitation_text(self):
        self.turn_on()
        self.client.post("/api/invitations", json={"email": KIM})
        pending = next(a for a in self.client.get("/api/accounts").json() if a["phone"] == KIM)
        texts = len(self.texts.sent)
        resent = self.client.post(f"/api/accounts/{pending['id']}/invitation", json={})
        self.assertEqual(resent.status_code, 202, resent.text)
        self.assertEqual(resent.json()["channels"], ["text"])
        self.assertEqual(len(self.texts.sent), texts + 1)
        self.assertIn("family locator", self.texts.sent[-1][1])
        missing = self.client.post("/api/accounts/nobody/invitation", json={})
        self.assertEqual(missing.status_code, 404)

    def test_an_email_invitation_can_also_be_texted(self):
        self.turn_on()
        invited = self.client.post(
            "/api/invitations", json={"email": "kim@example.invalid", "phone": "+1 415 555 0123"}
        )
        self.assertEqual(invited.json()["channels"], ["email", "text"])
        self.assertEqual(self.mail[-1][1], "kim@example.invalid")
        self.assertEqual(self.texts.sent[-1][0], KIM)
        # The email has the link; the text has none.
        self.assertTrue(self.link(self.mail[-1][3]))
        self.assertNotIn("http", self.texts.sent[-1][1])
        again = self.client.post("/api/invitations", json={"email": "4155550123"})
        self.assertEqual(again.status_code, 409)
        listed = {a["email"]: a for a in self.client.get("/api/accounts").json()}
        self.assertEqual(listed["kim@example.invalid"]["phone"], KIM)

    def test_the_invite_screen_hears_why_a_text_was_refused(self):
        self.turn_on()
        self.texts.refuse = "Sorry, URLs are not allowed for this key."
        invited = self.client.post(
            "/api/invitations", json={"email": "kim@example.invalid", "phone": "+1 415 555 0123"}
        ).json()
        self.assertEqual(invited["channels"], ["email", "text"])
        self.assertEqual(self.mail[-1][1], "kim@example.invalid", "the email still went")
        self.assertEqual(list(invited["problems"]), ["text"])
        self.assertIn("carry no links", invited["problems"]["text"])
        self.assertEqual(invited["delivery"], "pending")
        # Once Textbelt takes it, a retry sends it and the reply has no problems.
        self.texts.refuse = None
        self.assertEqual(self.client.post("/api/mail/retry", json={}).json()["sent"], 1)
        self.assertEqual(self.texts.sent[-1][0], KIM)
        fine = self.client.post("/api/invitations", json={"email": "ash@example.invalid"}).json()
        self.assertEqual((fine["problems"], fine["delivery"]), ({}, "sent"))

    @patch.dict(os.environ, APP_LINKS)
    def test_invitations_say_where_to_get_the_app_and_how_to_sign_in(self):
        self.turn_on()
        self.client.post(
            "/api/invitations", json={"email": "kim@example.invalid", "phone": "+1 415 555 0123"}
        )
        subject, mail = self.mail[-1][2], self.mail[-1][3]
        self.assertEqual(subject, "Nära Hem: you're invited to Test household")
        self.assertIn(APP_LINKS["NARAHEM_IOS_APP_URL"], mail)
        self.assertIn(APP_LINKS["NARAHEM_ANDROID_APP_URL"], mail)
        self.assertIn(f"Server: {PUBLIC}", mail)
        self.assertIn("Email: kim@example.invalid", mail)
        text = self.texts.sent[-1][1]
        self.assertNotIn("http", text)
        self.assertIn("official store", text)
        self.assertIn("using narahem<.>example<.>invalid and your phone number", text)
        # A household already called a family isn't a "family family".
        self.assertIn("to The Lees family locator.", texting.invitation("The Lees family", PUBLIC))
        self.assertIn("to The Lees family locator.", texting.invitation("The Lees", PUBLIC))

    def test_password_reset_goes_by_email_only(self):
        self.turn_on()
        self.client.post("/api/invitations", json={"email": "kim@example.invalid", "phone": KIM})
        self.client.post(
            "/api/enrollment/verify",
            json={"token": self.link(self.mail[-1][3]), "username": "kim", "password": PASSWORD},
        )
        mails, texts = len(self.mail), len(self.texts.sent)
        self.client.post("/api/password/forgot", json={"email": KIM})
        self.assertEqual(self.client.post("/api/mail/retry", json={}).status_code, 200)
        # The reset is a link, which Textbelt won't send, so it goes by email only.
        self.assertEqual(len(self.texts.sent), texts)
        self.assertEqual(len(self.mail), mails + 1)
        self.assertIn("#reset=", self.mail[-1][3])
        self.assertEqual(self.mail[-1][1], "kim@example.invalid")

    def test_texting_off_means_email_only(self):
        self.turn_on()
        self.client.post("/api/invitations", json={"email": KIM})
        self.turn_on("")
        resend = self.client.post("/api/enrollment/request", json={"email": KIM})
        self.assertEqual(resend.status_code, 202)
        self.assertEqual(len(self.texts.sent), 1)

    @patch.dict(os.environ, APP_LINKS)
    def test_a_test_text_shows_why_links_are_refused(self):
        self.turn_on()
        sent = self.client.post("/api/texting/test", json={"phone": KIM})
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertNotIn("http", self.texts.sent[-1][1])
        self.assertEqual(sent.json()["quota"], 39)
        self.texts.refuse = "Sorry, URLs are not allowed for this key."
        refused = self.client.post("/api/texting/test", json={"phone": KIM})
        self.assertEqual(refused.status_code, 424)
        self.assertIn("Nära Hem's texts carry no links", refused.json()["detail"])
        self.assertNotIn("link_domains", self.client.get("/api/texting").json())
        # Textbelt's refusal links to its whitelist with the key in it; the key never shows.
        said = (
            "Sorry, URLs are limited. Please go to https://textbelt.com/whitelist?key=secret-key "
            "or email support@textbelt.com."
        )
        cleaned = texting.scrub(said, "secret-key")
        self.assertNotIn("secret-key", cleaned)
        self.assertIn("https://textbelt.com/whitelist or email", cleaned)
        self.assertEqual(
            texting.scrub("Key secret-key is bad", "secret-key"), "Key •••••••• is bad"
        )

    def test_a_whitelisted_domain_is_texted_plainly(self):
        self.turn_on()
        status = self.client.get("/api/texting").json()
        self.assertEqual(
            (status["links_allowed"], status["texted_address"]),
            (False, "narahem<.>example<.>invalid"),
        )
        self.client.post("/api/invitations", json={"email": KIM})
        self.assertIn("using narahem<.>example<.>invalid and", self.texts.sent[-1][1])
        self.client.post("/api/texting/test", json={"phone": KIM})
        self.assertIn("from narahem<.>example<.>invalid are working", self.texts.sent[-1][1])
        # Once Textbelt whitelists the domain, the address is the server's own, without https://.
        saved = self.client.put("/api/texting/links", json={"allowed": True}).json()
        self.assertEqual(
            (saved["links_allowed"], saved["texted_address"]), (True, "narahem.example.invalid")
        )
        self.client.post("/api/invitations", json={"email": "+1 415 555 0199"})
        self.assertIn("using narahem.example.invalid and", self.texts.sent[-1][1])
        self.assertNotIn("https://", self.texts.sent[-1][1])
        self.client.post("/api/texting/test", json={"phone": KIM})
        self.assertIn("from narahem.example.invalid are working", self.texts.sent[-1][1])
        # Only the administrator can change it.
        self.client.post("/api/logout", json={})
        self.assertEqual(
            self.client.put("/api/texting/links", json={"allowed": False}).status_code, 401
        )

    def test_phone_numbers_are_stored_in_one_form(self):
        for given in ("4155550123", "14155550123", "+1 (415) 555-0123", "415.555.0123"):
            self.assertEqual(texting.phone_number(given), KIM)
        for bad in ("123", "+000001123", "+1-abc"):
            with self.assertRaises(HTTPException):
                texting.phone_number(bad)
        self.assertTrue(texting.looks_like_phone("(415) 555-0123"))
        self.assertFalse(texting.looks_like_phone("kim@example.invalid"))
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.scalar(select(Account).where(Account.phone == KIM)))

    def account_ids(self):
        with Session(self.app.state.engine) as db:
            return list(db.scalars(select(Account.id)))

    def test_changing_email_takes_effect_only_with_the_code(self):
        self.client.post("/api/mail/test", json={})
        wrong = self.client.post(
            "/api/account/contact", json={"value": "new@example.invalid", "password": "nope"}
        )
        self.assertEqual(wrong.status_code, 401)
        sent = self.client.post(
            "/api/account/contact",
            json={"value": "New@Example.invalid", "password": PASSWORD},
        )
        self.assertEqual(sent.status_code, 202, sent.text)
        self.assertEqual(self.mail[-1][1], "new@example.invalid")
        code = re.search(r"Enter (\d{6})", self.mail[-1][3]).group(1)
        # Stored only as a peppered HMAC: a copy of the database can't be tried against all
        # million codes.
        with Session(self.app.state.engine) as db:
            stored = db.scalar(select(ContactChange.code_hash))
        plain = [
            hashlib.sha256(f"{a}:email:new@example.invalid:{code}".encode()).hexdigest()
            for a in self.account_ids()
        ]
        self.assertNotIn(stored, plain)
        self.assertNotIn(code, stored)
        self.assertEqual(self.client.get("/api/session").json()["email"], OWNER)
        bad = self.client.post("/api/account/contact/verify", json={"code": "000000"})
        self.assertEqual(bad.status_code, 400)
        done = self.client.post("/api/account/contact/verify", json={"code": code})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.client.get("/api/session").json()["email"], "new@example.invalid")
        self.client.post("/api/mail/retry", json={})
        self.assertEqual(self.mail[-1][1], OWNER, "the old address hears about the change")
        self.client.post("/api/logout", json={})
        self.assertEqual(self.sign_in("new@example.invalid").status_code, 200)

    def test_adding_a_phone_needs_texting_and_the_texted_code(self):
        refused = self.client.post(
            "/api/account/contact", json={"value": KIM, "password": PASSWORD}
        )
        self.assertEqual(refused.status_code, 409)
        self.turn_on()
        sent = self.client.post(
            "/api/account/contact", json={"value": "415 555 0123", "password": PASSWORD}
        )
        self.assertEqual(sent.json(), {"sent_to": "phone", "to": KIM})
        code = re.search(r"code:\n(\d{6})$", self.texts.sent[-1][1]).group(1)
        for _ in range(5):
            self.client.post("/api/account/contact/verify", json={"code": "111111"})
        locked = self.client.post("/api/account/contact/verify", json={"code": code})
        self.assertEqual(locked.status_code, 429, "five wrong tries end the request")
        self.client.post("/api/account/contact", json={"value": KIM, "password": PASSWORD})
        code = re.search(r"code:\n(\d{6})$", self.texts.sent[-1][1]).group(1)
        done = self.client.post("/api/account/contact/verify", json={"code": code})
        self.assertEqual(done.json()["phone"], KIM)
        self.client.post("/api/logout", json={})
        self.assertEqual(self.sign_in(KIM).status_code, 200)

    def test_a_contact_in_use_cannot_be_taken(self):
        self.turn_on()
        self.client.post("/api/invitations", json={"email": KIM})
        taken = self.client.post("/api/account/contact", json={"value": KIM, "password": PASSWORD})
        self.assertEqual(taken.status_code, 409)
        same = self.client.post("/api/account/contact", json={"value": OWNER, "password": PASSWORD})
        self.assertEqual(same.status_code, 409)

    def test_the_app_says_which_one_it_is_changing(self):
        self.turn_on()
        wrong = self.client.post(
            "/api/account/contact",
            json={"value": "new@example.invalid", "password": PASSWORD, "kind": "phone"},
        )
        self.assertEqual(wrong.status_code, 422)
        self.assertIn("phone number", wrong.json()["detail"])
