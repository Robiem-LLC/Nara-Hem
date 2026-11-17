import base64
import datetime
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from nacl.signing import VerifyKey
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from narahem import alexa_api, alexa_arrivals, alexa_speech, alexa_verify, demo_family
from narahem.app import HASHER
from narahem.data_service import canonical
from narahem.models import (
    Account,
    AlexaLink,
    AlexaWatch,
    FindPhoneCommand,
    RosterRevision,
    ServiceState,
)
from tests import test_demo_family, test_relay, test_setup

STORE_SKILL = "amzn1.ask.skill.aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
RELAY = "https://alexa-relay.example.invalid"
STORE = {"NARAHEM_ALEXA_RELAY_URL": RELAY, "NARAHEM_ALEXA_STORE_SKILL_ID": STORE_SKILL}
VERIFIER = "v" * 43
LINK = {
    "client_id": alexa_api.RELAY_CLIENT_ID,
    "redirect_uri": RELAY + "/callback",
    "state": "sealed-relay-state",
    "response_type": "code",
    "code_challenge": alexa_api.challenge_for(VERIFIER),
    "code_challenge_method": "S256",
}


def now():
    """Returns the current time as Alexa writes it."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def amazon(app):
    """Returns a client that calls like Amazon's servers: no Origin header."""
    return TestClient(app, base_url=test_setup.PUBLIC)


class AlexaOffTests(unittest.TestCase):
    """Without NARAHEM_ALLOW_ALEXA the server has no Alexa addresses at all."""

    setUp = test_relay.RelayTests.setUp
    start = test_relay.RelayTests.start
    tearDown = test_relay.RelayTests.tearDown
    setup_owner = test_relay.RelayTests.setup_owner
    login = test_relay.RelayTests.login
    configure = test_relay.RelayTests.configure

    def test_alexa_is_off_unless_allowed(self):
        self.assertEqual(self.client.get("/api/alexa").status_code, 404)
        reply = amazon(self.app).post("/alexa/skill", json={})
        self.assertEqual(reply.status_code, 404)


@patch.dict(os.environ, {**test_demo_family.REVIEW, alexa_api.ENVIRONMENT: "true", **STORE})
@patch.object(demo_family.httpx, "get", test_demo_family.offline)
@patch.object(alexa_api.household_alerts, "lookup_address", lambda *a: "Near 400 Elm St, Portland")
@patch.object(alexa_verify, "check", lambda headers, body, request: None)
class AlexaTests(unittest.TestCase):
    """Linking the store skill through the relay (played here by the test) with the admin's
    sign-in, asking where someone is and ringing a phone.
    """

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
    family = test_demo_family.DemoFamilyTests.family

    def setUp(self):
        # The server decides at start-up whether it has Alexa addresses.
        with patch.dict(os.environ, {alexa_api.ENVIRONMENT: "true", **STORE}):
            test_relay.RelayTests.setUp(self)

    def move_in(self):
        """Moves the demo family in, so there are phones with locations to ask about."""
        owner = self.bootstrap()
        service = self.client.post("/api/enrollment/signer", json={}).json()
        self.call(owner, "POST", "/api/roster", self.roster(owner, [owner, service]))
        family = self.family()
        family.start()
        return family

    def link(self):
        """Links Alexa as the relay does and returns the access and refresh tokens."""
        page = self.client.get("/alexa/link", params=LINK)
        self.assertIn("Link Nära Hem to Alexa", page.text)
        self.assertIn(RELAY, page.headers["content-security-policy"])
        form = dict(LINK, email=test_setup.OWNER, password=test_setup.PASSWORD)
        signed = self.client.post(
            "/alexa/link",
            content="&".join(f"{k}={v}" for k, v in form.items()).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(signed.status_code, 303, signed.text)
        back = urlsplit(signed.headers["location"])
        self.assertEqual(f"https://{back.hostname}{back.path}", RELAY + "/callback")
        query = {k: v[0] for k, v in parse_qs(back.query).items()}
        self.assertEqual(query["state"], "sealed-relay-state")
        swap = dict(
            grant_type="authorization_code",
            code=query["code"],
            redirect_uri=RELAY + "/callback",
            code_verifier=VERIFIER,
        )
        tokens = self.exchange(**swap)
        self.assertEqual(tokens.status_code, 200, tokens.text)
        self.assertEqual(self.exchange(**swap).status_code, 400, "a code works once")
        return tokens.json()

    def exchange(self, client_id=alexa_api.RELAY_CLIENT_ID, **form):
        """Calls the token address as the relay does: a form, no Origin."""
        return amazon(self.app).post(
            "/alexa/token",
            content="&".join(
                f"{k}={v}" for k, v in dict(form, client_id=client_id).items()
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def ask(self, token, intent=None, person=None, attributes=None, kind="IntentRequest"):
        """Sends Alexa's request for an intent and returns the speech and the response."""
        request = {"type": kind, "timestamp": now()}
        if intent:
            request["intent"] = {"name": intent, "slots": {"person": {"value": person}}}
        body = {
            "version": "1.0",
            "session": {"attributes": attributes or {}},
            "context": {
                "System": {
                    "application": {"applicationId": STORE_SKILL},
                    "user": {"accessToken": "sealed-by-the-relay"},
                }
            },
            "request": request,
        }
        # As from the skill's Amazon-hosted forwarder: the relay adds this server's own token.
        headers = {"X-Narahem-Alexa-Token": token}
        reply = amazon(self.app).post("/alexa/skill", json=body, headers=headers)
        self.assertEqual(reply.status_code, 200, reply.text)
        response = reply.json()
        return response["response"].get("outputSpeech", {}).get("text", ""), response

    def test_alexa_links_with_the_admin_sign_in_and_answers(self):
        family = self.move_in()
        tokens = self.link()
        access = tokens["access_token"]
        self.assertIn("where someone is", self.ask(access, kind="LaunchRequest")[0])

        said, _ = self.ask(access, "WhereIsIntent", "Maya")
        self.assertTrue(said.startswith("Maya has been at Laurelhurst Park for"), said)
        said, response = self.ask(access, "WhereIsIntent", "Mya's")
        self.assertEqual(said, "Did you mean Maya?")
        self.assertFalse(response["response"]["shouldEndSession"])
        said, _ = self.ask(access, "AMAZON.YesIntent", attributes=response["sessionAttributes"])
        self.assertTrue(said.startswith("Maya has been at Laurelhurst Park"), said)
        said, _ = self.ask(access, "WhereIsIntent", "Zed")
        self.assertIn("I couldn't find anyone called Zed", said)
        self.assertIn("Maya", said)

        said, _ = self.ask(access, "FindPhoneIntent", "maya")
        self.assertEqual(said, "Maya's phone doesn't have Find my phone turned on.")
        maya = family.phones["Maya"]
        maya.device.put(
            "/api/find-phone/capability", json={"enabled": True, "platform": "android"}
        ).raise_for_status()
        said, _ = self.ask(access, "FindPhoneIntent", "Maya")
        self.assertEqual(said, "Ringing Maya's phone now.")
        with Session(self.app.state.engine) as db:
            command = db.scalar(select(FindPhoneCommand))
            envelope = json.loads(command.envelope)
            state = db.get(ServiceState, 1)
            devices = json.loads(db.get(RosterRevision, state.revision).payload)["devices"]
            owner = db.scalar(select(Account).where(Account.role == "admin"))
        # What the phones check: signed by a device in the roster that belongs to the admin.
        signer = next(d for d in devices if d["id"] == envelope["body"]["issuer"])
        self.assertEqual(signer["account_id"], owner.id)
        VerifyKey(base64.b64decode(signer["signing_key"])).verify(
            canonical(envelope["body"]), base64.b64decode(envelope["signature"])
        )
        self.assertEqual(envelope["body"]["target"], maya.id)
        self.assertEqual(envelope["body"]["action"], "ring")
        fetched = maya.device.get("/api/find-phone/command").json()
        self.assertEqual(fetched["command"]["body"]["id"], envelope["body"]["id"], fetched)

        refreshed = self.exchange(grant_type="refresh_token", refresh_token=tokens["refresh_token"])
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        said, response = self.ask(access, "WhereIsIntent", "Maya")
        self.assertEqual(response["response"]["card"], {"type": "LinkAccount"}, "old token ends")
        access = refreshed.json()["access_token"]
        self.assertIn("Maya", self.ask(access, "WhereIsIntent", "Maya")[0])

        links = self.client.get("/api/alexa").json()["links"]
        self.assertEqual(len(links), 1)
        self.assertIsNotNone(links[0]["last_used"])
        self.client.post(f"/api/alexa/links/{links[0]['id']}/revoke", json={})
        said, response = self.ask(access, "WhereIsIntent", "Maya")
        self.assertIn("link Nara Hem", said)
        self.assertEqual(response["response"]["card"], {"type": "LinkAccount"})

    def tell(self, link_token, kind="IntentRequest", granted=True, **request):
        """Sends an Alexa request for the arrival and departure watches and returns the reply."""
        permissions = (
            {"scopes": {alexa_arrivals.REMINDERS: {"status": "GRANTED"}}} if granted else {}
        )
        body = {
            "version": "1.0",
            "session": {"attributes": {}},
            "context": {
                "System": {
                    "application": {"applicationId": STORE_SKILL},
                    "user": {
                        "userId": "amzn1.ask.account.synthetic",
                        "accessToken": "sealed-by-the-relay",
                        "permissions": permissions,
                    },
                    "apiEndpoint": "https://api.amazonalexa.com",
                    "apiAccessToken": "synthetic-alexa-api-token",
                }
            },
            "request": dict(request, type=kind, timestamp=now(), locale="en-US"),
        }
        reply = amazon(self.app).post(
            "/alexa/skill", json=body, headers={"X-Narahem-Alexa-Token": link_token}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def watch(self, token, intent, person, place=None, granted=True):
        """Asks to be told when someone arrives at or leaves a place; returns what Alexa says."""
        slots = {"person": {"value": person}}
        if place:
            slots["place"] = {"value": place}
        reply = self.tell(token, granted=granted, intent={"name": intent, "slots": slots})
        return reply["response"].get("outputSpeech", {}).get("text", ""), reply

    def watches(self):
        with Session(self.app.state.engine) as db:
            return [
                (w.place_name, w.event, w.happened is not None)
                for w in db.scalars(select(AlexaWatch))
            ]

    def test_alexa_lets_you_know_when_someone_arrives_or_leaves(self):
        family = self.move_in()
        access = self.link()["access_token"]
        maya = family.phones["Maya"]

        # The first time, Alexa asks by voice for permission to set reminders.
        said, reply = self.watch(access, "NotifyArrivalIntent", "Maya", granted=False)
        directive = reply["response"]["directives"][0]
        self.assertEqual(
            (directive["type"], directive["name"]), ("Connections.SendRequest", "AskFor")
        )
        scope = directive["payload"]["permissionScopes"][0]["permissionScope"]
        self.assertEqual(scope, alexa_arrivals.REMINDERS)
        self.assertEqual(self.watches(), [])
        # "Yes" comes back as a Connections.Response carrying the request.
        reply = self.tell(
            access,
            kind="Connections.Response",
            name="AskFor",
            payload={
                "permissionScopes": [
                    {
                        "permissionScope": alexa_arrivals.REMINDERS,
                        "status": "ACCEPTED",
                    }
                ]
            },
            token=directive["token"],
        )
        said = reply["response"]["outputSpeech"]["text"]
        self.assertEqual(said, "Okay, I'll let you know when Maya gets home.")
        self.assertEqual(self.watches(), [("Home", "arrive", False)])
        # "No" sets nothing.
        reply = self.tell(
            access,
            kind="Connections.Response",
            name="AskFor",
            payload={"status": "DENIED"},
            token=directive["token"],
        )
        self.assertIn(
            "only let you know if I may set reminders", reply["response"]["outputSpeech"]["text"]
        )

        # Already there, or not there to leave: said at once, nothing to wait for.
        said, _ = self.watch(access, "NotifyArrivalIntent", "Maya", "Laurelhurst Park")
        self.assertEqual(said, "Maya is already at Laurelhurst Park.")
        said, _ = self.watch(access, "NotifyLeaveIntent", "Maya", "home")
        self.assertEqual(said, "Maya isn't home right now.")
        said, _ = self.watch(access, "NotifyArrivalIntent", "Maya", "Mars")
        self.assertEqual(said, "You don't have a saved place called Mars.")
        said, _ = self.watch(access, "NotifyLeaveIntent", "Maya", "Laurelhurst Park")
        self.assertEqual(said, "Okay, I'll let you know when Maya leaves Laurelhurst Park.")
        self.assertEqual(
            sorted(self.watches()),
            [("Home", "arrive", False), ("Laurelhurst Park", "leave", False)],
        )

        # Maya leaves the park: the departure happens; the arrival waits.
        park = demo_family.PLACES["Laurelhurst Park"]
        maya.location(park[0] + 0.01, park[1])
        self.assertEqual(
            sorted(self.watches()),
            [("Home", "arrive", False), ("Laurelhurst Park", "leave", True)],
        )
        # She gets home: the arrival happens too.
        maya.location(*demo_family.PLACES["Home"])
        self.assertEqual(
            sorted(self.watches()),
            [("Home", "arrive", True), ("Laurelhurst Park", "leave", True)],
        )

        # The background job asks the relay to wake the skill for each.
        woken = []

        def relay(url, json=None, **kwargs):
            woken.append((url, json))
            return type("Reply", (), {"status_code": 202})()

        with patch.object(alexa_arrivals.httpx, "post", relay):
            self.app.state.deliveries()
        self.assertEqual(len(woken), 2)
        self.assertEqual({u for u, _ in woken}, {RELAY + "/v1/notify"})
        sent = {w["user"] for _, w in woken}, {w["endpoint"] for _, w in woken}
        self.assertEqual(sent, ({"amzn1.ask.account.synthetic"}, {"https://api.amazonalexa.com"}))

        # Amazon wakes the skill: it sets a reminder that speaks a few seconds later.
        reminders = []

        def amazon_reminders(url, json=None, headers=None, **kwargs):
            reminders.append((url, json, headers))
            return type("Reply", (), {"status_code": 201})()

        # The second wake-up comes after the link's access token has expired: Amazon may send the
        # token it last had, and that still counts for a wake-up (but not for questions).
        for number, (_, wake) in enumerate(woken):
            if number:
                with Session(self.app.state.engine) as db:
                    db.execute(update(AlexaLink).values(access_expires=time.time() - 60))
                    db.commit()
            with patch.object(alexa_arrivals.httpx, "post", amazon_reminders):
                reply = self.tell(
                    access, kind="Messaging.MessageReceived", message={"watch": wake["watch"]}
                )
            self.assertEqual(reply["response"], {})
        spoken = sorted(r[1]["alertInfo"]["spokenInfo"]["content"][0]["text"] for r in reminders)
        self.assertEqual(
            spoken,
            [
                "From Nara Hem: Maya has arrived home.",
                "From Nara Hem: Maya has left Laurelhurst Park.",
            ],
        )
        url, body, headers = reminders[0]
        self.assertEqual(url, "https://api.amazonalexa.com/v1/alerts/reminders")
        self.assertEqual(headers["Authorization"], "Bearer synthetic-alexa-api-token")
        self.assertEqual(body["trigger"]["type"], "SCHEDULED_RELATIVE")
        self.assertEqual(self.watches(), [], "each watch is used once")
        intent = {"name": "WhereIsIntent", "slots": {"person": {"value": "Maya"}}}
        expired = self.tell(access, intent=intent)
        self.assertIn("link", expired["response"]["outputSpeech"]["text"])

        # A wake-up for a watch that isn't there, or another link's, does nothing.
        with patch.object(alexa_arrivals.httpx, "post", amazon_reminders):
            reply = self.tell(access, kind="Messaging.MessageReceived", message={"watch": "0" * 32})
        self.assertEqual((reply["response"], len(reminders)), ({}, 2))

    def test_watches_expire_and_give_up(self):
        self.move_in()
        access = self.link()["access_token"]
        self.watch(access, "NotifyArrivalIntent", "Maya")
        with patch("time.time", return_value=time.time() + alexa_arrivals.WATCH_SECONDS + 1):
            self.app.state.deliveries()
        self.assertEqual(self.watches(), [], "a day later the watch is gone")

    def test_only_the_admin_can_link_and_a_new_password_ends_it(self):
        self.move_in()
        tokens = self.link()
        form = dict(LINK, email="alex@" + demo_family.DOMAIN, password="anything at all")
        refused = self.client.post(
            "/alexa/link",
            content="&".join(f"{k}={v}" for k, v in form.items()).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(refused.status_code, 200)
        self.assertIn("isn&#x27;t the administrator", refused.text)
        own = dict(
            LINK,
            client_id="nara-hem",
            redirect_uri="https://pitangui.amazon.com/api/skill/link/x",
        )
        self.assertIn("Start linking", self.client.get("/alexa/link", params=own).text)
        refused = self.exchange(client_id="nara-hem", grant_type="refresh_token")
        self.assertEqual(refused.status_code, 401, "only the relay may swap codes")
        with Session(self.app.state.engine) as db:
            owner = db.scalar(select(Account).where(Account.role == "admin"))
            owner.password = HASHER.hash("a brand new admin password")
            db.commit()
        said, _ = self.ask(tokens["access_token"], "WhereIsIntent", "Maya")
        self.assertIn("link Nara Hem", said)
        retry = self.exchange(grant_type="refresh_token", refresh_token=tokens["refresh_token"])
        self.assertEqual(retry.status_code, 400)
        self.assertEqual(self.client.get("/api/alexa").json()["links"], [])

    def test_requests_for_another_skill_are_refused(self):
        self.move_in()
        tokens = self.link()
        body = {
            "context": {
                "System": {
                    "application": {"applicationId": STORE_SKILL.replace("aaaa", "9999")},
                    "user": {"accessToken": "sealed-by-the-relay"},
                }
            },
            "request": {"type": "LaunchRequest", "timestamp": now()},
        }
        token = {"X-Narahem-Alexa-Token": tokens["access_token"]}
        reply = amazon(self.app).post("/alexa/skill", json=body, headers=token)
        self.assertEqual(reply.status_code, 400)


@patch.dict(os.environ, {**test_demo_family.REVIEW, alexa_api.ENVIRONMENT: "true", **STORE})
@patch.object(demo_family.httpx, "get", test_demo_family.offline)
@patch.object(alexa_verify, "check", lambda headers, body, request: None)
class AlexaStoreTests(unittest.TestCase):
    """The published skill, linked through the Nära Hem relay (played here by the test)."""

    setUp = AlexaTests.setUp
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
    family = test_demo_family.DemoFamilyTests.family
    move_in = AlexaTests.move_in

    def relay_link(self):
        fields = LINK
        page = self.client.get("/alexa/link", params=fields)
        self.assertIn("Administrator email", page.text)
        self.assertIn(RELAY, page.headers["content-security-policy"])
        form = dict(fields, email=test_setup.OWNER, password=test_setup.PASSWORD)
        signed = self.client.post(
            "/alexa/link",
            content="&".join(f"{k}={v}" for k, v in form.items()).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        self.assertEqual(signed.status_code, 303, signed.text)
        back = urlsplit(signed.headers["location"])
        self.assertEqual(f"https://{back.hostname}{back.path}", RELAY + "/callback")
        return {k: v[0] for k, v in parse_qs(back.query).items()}["code"]

    def relay_token(self, **form):
        return amazon(self.app).post(
            "/alexa/token",
            content="&".join(f"{k}={v}" for k, v in form.items()).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_the_store_skill_links_through_the_relay(self):
        self.move_in()
        info = amazon(self.app).get("/alexa/info").json()
        self.assertEqual(info, {"service": "nara-hem", "alexa": True, "store": True})
        code = self.relay_link()
        swap = dict(
            grant_type="authorization_code",
            code=code,
            redirect_uri=RELAY + "/callback",
            client_id=alexa_api.RELAY_CLIENT_ID,
        )
        self.assertEqual(
            self.relay_token(**swap, code_verifier="w" * 43).status_code,
            400,
            "only the relay that started the sign-in can finish it",
        )
        code = self.relay_link()
        tokens = self.relay_token(**dict(swap, code=code), code_verifier="v" * 43)
        self.assertEqual(tokens.status_code, 200, tokens.text)
        server_token = tokens.json()["access_token"]
        body = {
            "context": {
                "System": {
                    "application": {"applicationId": STORE_SKILL},
                    "user": {"accessToken": "sealed-by-the-relay"},
                }
            },
            "request": {
                "type": "IntentRequest",
                "timestamp": now(),
                "intent": {"name": "WhereIsIntent", "slots": {"person": {"value": "Leo"}}},
            },
        }
        # From the Amazon-hosted forwarder: no Amazon signature, but the link token.
        token = {"X-Narahem-Alexa-Token": server_token}
        reply = amazon(self.app).post("/alexa/skill", json=body, headers=token)
        self.assertIn("Leo", reply.json()["response"]["outputSpeech"]["text"])
        refused = amazon(self.app).post("/alexa/skill", json=body)
        self.assertEqual(refused.status_code, 400, "unsigned needs the link token")
        stale = dict(body, request=dict(body["request"], timestamp="2026-01-01T00:00:00Z"))
        old = amazon(self.app).post("/alexa/skill", json=stale, headers=token)
        self.assertEqual(old.status_code, 400, "an old request can't be replayed")
        wrong = amazon(self.app).post(
            "/alexa/skill", json=body, headers={"X-Narahem-Alexa-Token": "not-the-token"}
        )
        self.assertEqual(wrong.json()["response"]["card"], {"type": "LinkAccount"})
        links = self.client.get("/api/alexa").json()
        self.assertTrue(links["store"])
        self.assertEqual(len(links["links"]), 1)
        refresh = self.relay_token(
            grant_type="refresh_token",
            refresh_token=tokens.json()["refresh_token"],
            client_id=alexa_api.RELAY_CLIENT_ID,
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)

    def test_relay_codes_only_go_back_to_the_relay(self):
        bad = {
            "client_id": alexa_api.RELAY_CLIENT_ID,
            "redirect_uri": "https://elsewhere.example/callback",
            "response_type": "code",
            "code_challenge": "c" * 43,
            "code_challenge_method": "S256",
        }
        self.assertIn("Start linking", self.client.get("/alexa/link", params=bad).text)
        bad.update(redirect_uri=RELAY + "/callback", code_challenge_method="plain")
        self.assertIn("Start linking", self.client.get("/alexa/link", params=bad).text)


@patch.dict(os.environ, {alexa_api.ENVIRONMENT: "true"})
class AlexaWithoutRelayTests(unittest.TestCase):
    """A server built without the Alexa relay can't be linked or asked anything."""

    start = test_relay.RelayTests.start
    tearDown = test_relay.RelayTests.tearDown
    setup_owner = test_relay.RelayTests.setup_owner
    login = test_relay.RelayTests.login
    configure = test_relay.RelayTests.configure

    def setUp(self):
        with patch.dict(os.environ, {alexa_api.ENVIRONMENT: "true"}):
            test_relay.RelayTests.setUp(self)

    def test_nothing_links_or_answers(self):
        status = self.client.get("/api/alexa").json()
        self.assertEqual((status["store"], status["links"]), (False, []))
        self.assertIn("Start linking", self.client.get("/alexa/link", params=LINK).text)
        body = {
            "context": {"System": {"application": {"applicationId": STORE_SKILL}, "user": {}}},
            "request": {"type": "LaunchRequest", "timestamp": now()},
        }
        reply = amazon(self.app).post(
            "/alexa/skill", json=body, headers={"X-Narahem-Alexa-Token": "anything"}
        )
        self.assertEqual(reply.status_code, 400)


class AlexaSpeechTests(unittest.TestCase):
    """The words Alexa says."""

    members = [("a", "Sam"), ("k", "Madelyn Rivera"), ("r", "Grandma Rosa")]
    zone = ZoneInfo("America/Los_Angeles")

    def at(self, day, hour, minute):
        moment = datetime.datetime(2026, 11, day, hour, minute, tzinfo=self.zone)
        return int(moment.timestamp() * 1000)

    def test_names_match_exactly_closely_or_not_at_all(self):
        self.assertEqual(alexa_speech.match_name("sam's", self.members), ("exact", ("a", "Sam")))
        self.assertEqual(alexa_speech.match_name("Madelyn", self.members)[0], "exact")
        self.assertEqual(alexa_speech.match_name("rosa", self.members)[0], "exact")
        self.assertEqual(alexa_speech.match_name("rossa", self.members)[0], "close")
        self.assertEqual(
            alexa_speech.match_name("madalyn", self.members),
            ("close", ("k", "Madelyn Rivera")),
        )
        self.assertEqual(alexa_speech.match_name("Zed", self.members), (None, None))
        self.assertEqual(alexa_speech.names(self.members), "Sam, Madelyn Rivera and Grandma Rosa")

    def test_where_someone_is(self):
        now = self.at(13, 18, 0)
        fix = {"at": now - 60000, "speed": 0, "trip": None}
        where = alexa_speech.where
        self.assertEqual(
            where("Sam", fix, "Home", self.at(13, 16, 30), None, now, self.zone),
            "Sam has been at Home since 4:30 PM.",
        )
        self.assertEqual(
            where("Sam", fix, "Home", self.at(12, 16, 30), None, now, self.zone),
            "Sam has been at Home since yesterday at 4:30 PM.",
        )
        self.assertEqual(
            where("Sam", fix, "Home", self.at(13, 16, 30), None, now, None),
            "Sam has been at Home for 2 hours.",
        )
        driving = dict(fix, speed=24)
        self.assertEqual(
            where("Madelyn", driving, None, None, "Near 12 Route 9, Springfield", now, None),
            "Madelyn is driving near Route 9, Springfield.",
        )
        self.assertEqual(
            where("Sam", fix, None, None, "12 Main St, Springfield", now, self.zone),
            "Sam is at 12 Main St, Springfield.",
        )
        old = dict(fix, at=self.at(10, 9, 5))
        self.assertEqual(
            where("Sam", old, "Work", None, None, now, self.zone),
            "Sam was last seen at Work on Tuesday at 9:05 AM.",
        )
        self.assertIn("no address", where("Sam", fix, None, None, None, now, self.zone))


class AmazonSignatureTests(unittest.TestCase):
    """Only signed, recent requests from Amazon's certificate are accepted."""

    def certificate(self, issuer_key, subject, key, issuer=None, ca=False, names=()):
        now = datetime.datetime.now(datetime.UTC)
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer or subject)]))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        ).add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
        if ca:
            builder = builder.add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                critical=True,
            )
        else:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False
            ).add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
        return builder.sign(issuer_key, hashes.SHA256())

    def setUp(self):
        alexa_verify._certificates.clear()
        self.root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.root = self.certificate(self.root_key, "Test root", self.root_key, ca=True)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def pem(self, names=("echo-api.amazon.com",)):
        from cryptography.hazmat.primitives.serialization import Encoding

        leaf = self.certificate(self.root_key, "echo", self.key, issuer="Test root", names=names)
        return leaf.public_bytes(Encoding.PEM)

    def key_for(self, pem):
        store = alexa_verify.Store([self.root])
        return lambda url: alexa_verify.signing_key(url, store=store, download=lambda u: pem)

    def signed(self, body):
        signature = self.key.sign(body, padding.PKCS1v15(), hashes.SHA256())
        return {
            "signaturecertchainurl": "https://s3.amazonaws.com/echo.api/echo-api-cert.pem",
            "signature-256": base64.b64encode(signature).decode(),
        }

    def test_certificate_addresses(self):
        good = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"
        self.assertEqual(alexa_verify.certificate_url(good), good)
        for bad in (
            "http://s3.amazonaws.com/echo.api/echo-api-cert.pem",
            "https://notamazon.com/echo.api/echo-api-cert.pem",
            "https://s3.amazonaws.com/EcHo.aPi/echo-api-cert.pem",
            "https://s3.amazonaws.com/invalid.path/echo-api-cert.pem",
            "https://s3.amazonaws.com:563/echo.api/echo-api-cert.pem",
            "https://s3.amazonaws.com/echo.api/../invalid.path/cert.pem",
        ):
            with self.assertRaises(alexa_verify.NotFromAmazon, msg=bad):
                alexa_verify.certificate_url(bad)

    def test_signatures_and_timestamps(self):
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        request = {"request": {"timestamp": stamp}}
        body = json.dumps(request).encode()
        key_for = self.key_for(self.pem())
        alexa_verify.check(self.signed(body), body, request, key_for=key_for)
        with self.assertRaises(alexa_verify.NotFromAmazon):
            alexa_verify.check(self.signed(body), body + b" ", request, key_for=key_for)
        with self.assertRaises(alexa_verify.NotFromAmazon):
            alexa_verify.check(
                self.signed(body), body, request, now=time.time() + 600, key_for=key_for
            )
        with self.assertRaises(alexa_verify.NotFromAmazon):
            alexa_verify.check({}, body, request, key_for=key_for)
        alexa_verify._certificates.clear()
        with self.assertRaises(alexa_verify.NotFromAmazon):
            alexa_verify.check(
                self.signed(body), body, request, key_for=self.key_for(self.pem(("evil.com",)))
            )
