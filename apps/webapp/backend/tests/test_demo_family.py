import os
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from narahem import demo_family, review_mode
from narahem.demo_phone import DemoPhone, Server
from narahem.models import Account, ClientDevice, EncryptedRecord
from tests import test_relay, test_setup

REVIEW = {review_mode.CODE: "246810", review_mode.ACCOUNTS: "@" + demo_family.DOMAIN}
REVIEWER = "review@" + demo_family.DOMAIN


class TestServer(Server):
    """The demo server, reached through the test client instead of the stack network."""

    def __init__(self, app):
        super().__init__(app.state.engine, test_setup.PUBLIC, test_setup.PUBLIC)
        self.app = app

    def client(self, token=None):
        client = TestClient(self.app, base_url=test_setup.PUBLIC)
        client.headers["Origin"] = test_setup.PUBLIC
        if token:
            client.headers["Authorization"] = "Bearer " + token
        return client


def offline(*args, **kwargs):
    raise httpx.ConnectError("no router in tests")


@patch.dict(os.environ, REVIEW)
@patch.object(demo_family.httpx, "get", offline)
class DemoFamilyTests(unittest.TestCase):
    """The made-up family that keeps a demo server busy for App Store review."""

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

    def family(self):
        return demo_family.Family(
            TestServer(self.app),
            self.path / "demo" / "family.json",
            REVIEWER,
            "a long review password",
            "246810",
        )

    def count(self, *where):
        with Session(self.app.state.engine) as db:
            return db.scalar(select(func.count()).select_from(EncryptedRecord).where(*where))

    def phones(self):
        with Session(self.app.state.engine) as db:
            return db.scalar(
                select(func.count())
                .select_from(ClientDevice)
                .where(ClientDevice.status == "approved", ClientDevice.name != "")
            )

    def test_the_family_moves_in_and_the_reviewer_sees_them(self):
        family = self.family()
        self.assertFalse(family.ready(), "waits for the administrator's browser")
        owner = self.bootstrap()
        service = self.client.post("/api/enrollment/signer", json={}).json()
        self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, service]))
        self.assertTrue(family.ready())
        family.start()
        trips = self.count(EncryptedRecord.kind == "event")
        self.assertEqual(trips, len(demo_family.HISTORY))
        self.assertEqual(self.count(EncryptedRecord.kind == "place"), len(demo_family.PLACES))
        self.assertEqual(self.count(EncryptedRecord.kind == "profile"), len(demo_family.MEMBERS))
        phones = self.phones()

        # A real drive spreads its fixes out; here they all land at once, so make room under
        # the server's limit of 120 records per phone per minute.
        with Session(self.app.state.engine) as db:
            db.execute(
                update(EncryptedRecord).values(received_at=EncryptedRecord.received_at - 120)
            )
            db.commit()
        family.wait = lambda seconds: None
        family.outing()
        self.assertEqual(self.count(EncryptedRecord.kind == "event"), trips + 1)
        self.assertIsNone(family.driving)

        again = self.family()
        again.start()
        self.assertEqual(self.phones(), phones, "a restart keeps the same phones")
        self.assertEqual(self.count(EncryptedRecord.kind == "event"), trips + 1)
        self.assertEqual(self.count(EncryptedRecord.kind == "profile"), len(demo_family.MEMBERS))

        with Session(self.app.state.engine) as db:
            reviewer = db.scalar(select(Account.id).where(Account.email == REVIEWER))
        server = TestServer(self.app)
        phone, _ = DemoPhone.enroll(
            server, reviewer, "Sam", REVIEWER, "a long review password", "246810", "ios"
        )
        view = phone.device.get("/api/view").json()["records"]
        names = {r["data"]["name"] for r in view if r["kind"] == "profile"}
        self.assertEqual(names, set(demo_family.MEMBERS))
        seen = {r["entity_id"] for r in view if r["kind"] == "location"}
        self.assertEqual(seen, {p.account_id for p in again.phones.values()})
        maya = again.phones["Maya"].account_id
        now = int(time.time() * 1000)
        window = {"account_id": maya, "start": now - 86_400_000, "end": now}
        reply = phone.device.get("/api/trips", params=window)
        self.assertEqual(reply.status_code, 200, reply.text)
        listed = reply.json()["trips"]
        made = sum(1 for trip in demo_family.HISTORY if trip[0] == "Maya")
        self.assertGreaterEqual(len(listed), made, "the reviewer sees the family's trips")
