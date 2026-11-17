"""Alexa: "Alexa, ask Close to Home where Maya is" and "... to find Maya's phone".

Off unless the server is started with NARAHEM_ALLOW_ALEXA=true. Households use the published Nära
Hem skill from the Alexa store and link it by signing in with their admin email and password. The
admin can revoke the link in Admin settings at any time, and changing the admin password ends it
too.

The skill's requests come through the Nära Hem Alexa relay (deploy/cloudflare/
alexa-relay-worker.mjs), which links to this server as a sign-in client with a PKCE check and
keeps no database. The relay's address and the skill's ID are built into official images
(image_defaults.py) or set with NARAHEM_ALEXA_RELAY_URL and NARAHEM_ALEXA_STORE_SKILL_ID.

Alexa answers with what the admin's browser sees: everyone sharing their location. Rings are
signed with the server's enrollment key, which the phones already accept from the admin.
"Let me know when Maya gets home" (or "leaves school") is in alexa_arrivals.py.
"""

import base64
import concurrent.futures
import hashlib
import html
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from argon2.exceptions import VerificationError
from fastapi import BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem import alexa_arrivals, alexa_speech, alexa_verify, household_alerts, image_defaults
from narahem.app import DUMMY_HASH, HASHER, digest, trusted_accounts
from narahem.data_service import audit, canonical
from narahem.models import (
    Account,
    AlexaLink,
    AlexaWatch,
    ClientDevice,
    EncryptedRecord,
    FindPhoneCapability,
    LatestState,
    ServiceState,
)
from narahem.schemas import FindCommandInput

ENVIRONMENT = "NARAHEM_ALLOW_ALEXA"
RELAY_CLIENT_ID = "nara-hem-relay"
SERVICE_ID = "0" * 32
CODE_SECONDS = 300
ACCESS_SECONDS = 3600

_zones = {}
# Alexa gives up after about 8 seconds, so the street address lookup gets at most this long.
ADDRESS_SECONDS = 2.5
_lookups = concurrent.futures.ThreadPoolExecutor(max_workers=4)

FIELDS = (
    "client_id",
    "redirect_uri",
    "state",
    "response_type",
    "code_challenge",
    "code_challenge_method",
)


def enabled():
    """Returns True if the server was started with Alexa allowed."""
    return os.environ.get(ENVIRONMENT, "").strip().lower() in ("1", "true", "yes")


def store():
    """Returns the store skill's relay address and skill ID ({} if it isn't published). The
    environment overrides the values built into the image.
    """
    relay = image_defaults.setting("NARAHEM_ALEXA_RELAY_URL")
    skill = image_defaults.setting("NARAHEM_ALEXA_STORE_SKILL_ID")
    parts = urlsplit(relay)
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or not skill:
        return {}
    return {"relay": f"https://{parts.netloc}", "skill_id": skill}


def challenge_for(verifier):
    """Returns the PKCE S256 challenge for a verifier."""
    hashed = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(hashed).decode().rstrip("=")


def client_allowed(fields):
    """Returns True for a sign-in request from the Nära Hem relay, with its return address and a
    PKCE challenge.
    """
    relay = store().get("relay")
    return bool(
        relay
        and fields["client_id"] == RELAY_CLIENT_ID
        and fields["redirect_uri"] == relay + "/callback"
        and fields.get("code_challenge_method") == "S256"
        and len(fields.get("code_challenge", "")) == 43
    )


def say(text, end=True, attributes=None, link=False):
    """Returns an Alexa response that says text."""
    response = {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end}
    if not end:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": text}}
    if link:
        response["card"] = {"type": "LinkAccount"}
    return {"version": "1.0", "sessionAttributes": attributes or {}, "response": response}


def link_page(fields, error=""):
    """Returns the sign-in page the Alexa app shows while linking."""
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(fields.get(name, ""))}">'
        for name in FIELDS
    )
    problem = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width, initial-scale=1">'
        "<title>Link Nära Hem to Alexa</title><style>"
        "body{font:16px system-ui,sans-serif;background:#0a1c52;color:#fff;margin:0;padding:24px}"
        "main{max-width:380px;margin:auto}label{display:block;margin:16px 0 6px}"
        "input{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:0;"
        "font-size:16px}button{margin-top:22px;width:100%;padding:13px;border:0;"
        "border-radius:8px;background:#f5b335;font-size:16px;font-weight:600}"
        ".error{background:#7f1d1d;padding:10px;border-radius:8px}p{line-height:1.45}"
        "</style></head><body><main><h1>Link Nära Hem to Alexa</h1>"
        "<p>Sign in as your household's administrator. Alexa will be able to say where "
        "household members are and ring their phones. You can revoke this in Admin settings "
        f"at any time.</p>{problem}"
        '<form method=post action="/alexa/link">'
        f"{hidden}<label for=email>Administrator email</label>"
        "<input id=email name=email type=email autocomplete=username required>"
        "<label for=password>Password</label>"
        "<input id=password name=password type=password autocomplete=current-password required>"
        "<button type=submit>Link to Alexa</button></form></main></body></html>",
        status_code=400 if error and not fields.get("redirect_uri") else 200,
    )


def install(
    app,
    *,
    admin,
    alert_memory,
    database,
    engine,
    maps_key,
    member_name,
    rate,
    server_places,
    store_command,
    trip_processor,
):
    """Registers the Alexa routes. Only called when the server allows Alexa."""

    def status(db):
        """Returns everything the Admin settings card shows."""
        links = db.scalars(
            select(AlexaLink)
            .where(AlexaLink.access.is_not(None), AlexaLink.kind == "store")
            .order_by(AlexaLink.created)
        )
        return {
            "store": bool(store()),
            "address": app.state.public_url,
            "links": [
                {"id": link.id, "created": link.created, "last_used": link.last_used}
                for link in links
            ],
        }

    @app.get("/api/alexa")
    def alexa_status(auth=Depends(admin), db: Session = Depends(database)):
        """Returns whether the store skill can link, and the linked Alexa accounts."""
        return status(db)

    @app.post("/api/alexa/links/{link_id}/revoke")
    def alexa_revoke(link_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Ends a linked Alexa account straight away."""
        link = db.get(AlexaLink, link_id)
        if not link:
            raise HTTPException(404, "That Alexa link no longer exists")
        db.delete(link)
        audit(db, "alexa.revoked", auth[0].id, link_id)
        db.commit()
        return status(db)

    def link_fields(source):
        """Returns the account-linking fields from a query string or form."""
        return {k: source.get(k, "") for k in FIELDS}

    @app.get("/alexa/link")
    def link_form(request: Request):
        """Shows the sign-in page, after checking the request came from the Alexa app."""
        fields = link_fields(request.query_params)
        if fields["response_type"] != "code" or not client_allowed(fields):
            return link_page({}, "Start linking from the Nära Hem skill in the Alexa app.")
        return link_page(fields)

    @app.post("/alexa/link")
    async def link_submit(request: Request):
        """Checks the admin's email and password and sends Alexa back with a one-time code."""
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        fields = link_fields(form)
        if not client_allowed(fields):
            return link_page({}, "Start linking from the Nära Hem skill in the Alexa app.")
        rate(request, "alexa-link", 10)
        with Session(engine) as db:
            account = db.scalar(
                select(Account).where(
                    Account.email == form.get("email", "").strip().lower(),
                    Account.role == "admin",
                    Account.status == "active",
                )
            )
            try:
                valid = HASHER.verify(
                    account.password if account and account.password else DUMMY_HASH,
                    form.get("password", ""),
                )
            except VerificationError:
                valid = False
            if not valid or not account:
                return link_page(fields, "That isn't the administrator's email and password.")
            code = secrets.token_urlsafe(32)
            link = AlexaLink(
                id=secrets.token_hex(16),
                account_id=account.id,
                code=digest(code),
                code_expires=time.time() + CODE_SECONDS,
                redirect_uri=fields["redirect_uri"],
                kind="store",
                challenge=fields["code_challenge"],
                password_mark=digest(account.password),
                created=time.time(),
            )
            db.add(link)
            db.query(AlexaLink).filter(
                AlexaLink.access.is_(None), AlexaLink.code_expires < time.time()
            ).delete()
            audit(db, "alexa.linked", account.id, link.id)
            db.commit()
        query = urlencode({"state": fields["state"], "code": code})
        joiner = "&" if "?" in fields["redirect_uri"] else "?"
        return RedirectResponse(fields["redirect_uri"] + joiner + query, status_code=303)

    def refused(error="invalid_grant"):
        """Returns an OAuth error."""
        return JSONResponse({"error": error}, status_code=400)

    def current_link(db, link):
        """Returns the link's admin if the link is still good: same password, still admin."""
        account = db.get(Account, link.account_id) if link else None
        if (
            not account
            or account.role != "admin"
            or account.status != "active"
            or link.password_mark != digest(account.password or "")
        ):
            return None
        return account

    @app.post("/alexa/token")
    async def token(request: Request):
        """Amazon swaps the one-time code, or a refresh token, for an access token."""
        rate(request, "alexa-token", 120, shared=True)
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        # The relay is a public client: its codes only ever go back to the relay's own address,
        # and it must prove it started the sign-in (PKCE).
        if form.get("client_id") != RELAY_CLIENT_ID or not store():
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        with Session(engine) as db:
            grant = form.get("grant_type")
            if grant == "authorization_code":
                link = db.scalar(
                    select(AlexaLink).where(AlexaLink.code == digest(form.get("code", "")))
                )
                if (
                    not link
                    or link.code_expires < time.time()
                    or link.redirect_uri != form.get("redirect_uri")
                    or link.kind != "store"
                    or not secrets.compare_digest(
                        challenge_for(form.get("code_verifier", "")), link.challenge or ""
                    )
                ):
                    return refused()
                link.code = None
            elif grant == "refresh_token":
                link = db.scalar(
                    select(AlexaLink).where(
                        AlexaLink.refresh == digest(form.get("refresh_token", ""))
                    )
                )
            else:
                return refused("unsupported_grant_type")
            if link and link.kind != "store":
                return refused()
            if not current_link(db, link):
                if link:
                    db.delete(link)
                    db.commit()
                return refused()
            access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            link.access, link.refresh = digest(access), digest(refresh)
            link.access_expires = time.time() + ACCESS_SECONDS
            db.commit()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": ACCESS_SECONDS,
        }

    def household(db):
        """Returns every active member with a name as (account_id, name)."""
        accounts = db.scalars(
            select(Account)
            .where(Account.status == "active", trusted_accounts())
            .order_by(Account.username)
        )
        named = [(a.id, member_name(db, a.id, fallback=None)) for a in accounts]
        return [member for member in named if member[1]]

    def time_zone(alexa):
        """Returns the Echo's time zone from Alexa's settings, remembered for an hour."""
        system = alexa.get("context", {}).get("System", {})
        device = system.get("device", {}).get("deviceId", "")
        endpoint, token = system.get("apiEndpoint", ""), system.get("apiAccessToken", "")
        cached = _zones.get(device)
        if cached and cached[1] > time.time():
            return cached[0]
        host = urlsplit(endpoint).hostname or ""
        if not device or not token or not host.endswith(".amazonalexa.com"):
            return None
        try:
            reply = httpx.get(
                f"{endpoint}/v2/devices/{device}/settings/System.timeZone",
                headers={"Authorization": "Bearer " + token},
                timeout=1.5,
            )
            zone = ZoneInfo(reply.json()) if reply.status_code == 200 else None
        except (httpx.HTTPError, ValueError, TypeError, ZoneInfoNotFoundError):
            zone = None
        _zones[device] = (zone, time.time() + 3600)
        return zone

    def street_address(lat, lon):
        """Looks up a street address, giving up after ADDRESS_SECONDS so Alexa isn't kept
        waiting.
        """
        lookup = _lookups.submit(household_alerts.lookup_address, lat, lon, maps_key)
        try:
            return lookup.result(timeout=ADDRESS_SECONDS)
        except concurrent.futures.TimeoutError:
            return None

    def latest(db, account_id):
        """Returns a member's phone and its latest shared location, decrypted: (None, None) when
        there is none to use, and (phone, None) when the phone isn't sharing.
        """
        state = db.get(LatestState, ("location", account_id))
        record = db.get(EncryptedRecord, state.record_id) if state else None
        sender = db.get(ClientDevice, record.device_id) if record else None
        if not sender or sender.status != "approved":
            return None, None
        if not sender.sharing:
            return sender, None
        try:
            return sender, trip_processor.open_record(json.loads(record.envelope)["body"])
        except (HTTPException, KeyError, ValueError):
            return None, None

    def where_is(db, member, alexa):
        """Says where a member is, from the latest location their phone shared."""
        account_id, name = member
        sender, payload = latest(db, account_id)
        if not sender:
            return f"I don't have a location for {name}."
        if payload is None:
            return f"{name} isn't sharing a location right now."
        data = payload["data"]
        lat, lon = float(data["lat"]), float(data["lon"])
        place = household_alerts.match(
            lat, lon, server_places(db), float(data.get("accuracy") or 25)
        )
        address = None if place else street_address(lat, lon)
        fix = {"at": payload["captured_at"], "speed": data.get("speed_mps"), "trip": None}
        fix["trip"] = data.get("trip_id")
        return alexa_speech.where(
            name,
            fix,
            place["name"] if place else None,
            alert_memory(db, sender.id)[1].get("still_since"),
            address,
            int(time.time() * 1000),
            time_zone(alexa),
        )

    def ring(db, member, link, background_tasks):
        """Rings a member's phone with a command signed by the server's enrollment key."""
        account_id, name = member
        phones = [
            d
            for d in db.scalars(
                select(ClientDevice).where(
                    ClientDevice.account_id == account_id, ClientDevice.status == "approved"
                )
            )
            if json.loads(d.registration).get("platform") in ("ios", "android")
        ]
        if not phones:
            return f"{name} doesn't have a phone set up."
        phone = phones[0]
        capability = db.get(FindPhoneCapability, phone.id)
        if not capability or not capability.enabled:
            return f"{name}'s phone doesn't have Find my phone turned on."
        service = db.get(ClientDevice, SERVICE_ID)
        if not service or service.status != "approved":
            return "Phone enrollment isn't set up on your server yet, so I can't ring phones."
        now = int(time.time())
        body = {
            "domain": "narahem.find-phone.v1",
            "household": db.get(ServiceState, 1).household_id,
            "id": secrets.token_hex(16),
            "issuer": SERVICE_ID,
            "target": phone.id,
            "action": "ring",
            "issued_at": now,
            "expires_at": now + 120,
        }
        signature = app.state.enrollment_signer.sign(canonical(body)).signature
        command = FindCommandInput.model_validate(
            {"body": body, "signature": base64.b64encode(signature).decode()}
        )
        store_command(db, command, link.account_id, phone, background_tasks)
        return f"Ringing {name}'s phone now."

    def answer(db, alexa, link, background_tasks):
        """Works out what to say to one Alexa request."""
        request = alexa.get("request", {})
        kind = request.get("type")
        if kind == "SessionEndedRequest":
            return {"version": "1.0", "response": {}}
        if kind == "LaunchRequest":
            return say("Ask me where someone is, or to find someone's phone.", end=False)
        if kind == "Connections.Response":
            return permission_answer(db, alexa, link)
        if kind == "Messaging.MessageReceived":
            return wake_up(db, alexa, link)
        intent = request.get("intent", {})
        name = intent.get("name", "")
        members = household(db)
        pending = (alexa.get("session", {}).get("attributes") or {}).get("pending")
        if name == "AMAZON.YesIntent" and pending:
            member = next((m for m in members if m[0] == pending.get("account")), None)
            if member:
                return act(db, pending, member, alexa, link, background_tasks)
        if name in ("AMAZON.NoIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return say("Okay.")
        if name in ("WhereIsIntent", "FindPhoneIntent", "NotifyArrivalIntent", "NotifyLeaveIntent"):
            slots = intent.get("slots") or {}
            heard = (slots.get("person") or {}).get("value") or ""
            ask = {"WhereIsIntent": "where", "FindPhoneIntent": "ring"}.get(name, "notify")
            pending = {"ask": ask}
            if ask == "notify":
                pending["event"] = "leave" if name == "NotifyLeaveIntent" else "arrive"
                place = place_named(db, (slots.get("place") or {}).get("value"))
                if not place:
                    spoken = (slots.get("place") or {}).get("value") or "home"
                    return say(f"You don't have a saved place called {spoken}.")
                pending["place"] = place["id"]
            found, member = alexa_speech.match_name(heard, members)
            if found == "exact":
                return act(db, pending, member, alexa, link, background_tasks)
            if found == "close":
                return say(
                    f"Did you mean {member[1]}?",
                    end=False,
                    attributes={"pending": dict(pending, account=member[0])},
                )
            who = f"anyone called {heard}" if heard else "who you meant"
            return say(f"I couldn't find {who}. You can ask about {alexa_speech.names(members)}.")
        return say(
            "You can say, where is Maya, or find Maya's phone. "
            f"Your household is {alexa_speech.names(members)}.",
            end=False,
        )

    def act(db, pending, member, alexa, link, background_tasks):
        """Answers a where-is question, rings a phone or starts an arrival watch."""
        if pending.get("ask") == "ring":
            return say(ring(db, member, link, background_tasks))
        if pending.get("ask") == "notify":
            place = next((p for p in server_places(db) if p["id"] == pending.get("place")), None)
            if not place:
                return say("That place isn't saved any more.")
            event = "leave" if pending.get("event") == "leave" else "arrive"
            return notify_when(db, alexa, link, member, place, event)
        return say(where_is(db, member, alexa))

    def place_named(db, heard):
        """Returns the saved place Alexa heard ("home" when none was said), or None."""
        places = server_places(db)
        found, match = alexa_speech.match_name(
            heard or "home", [(p["id"], p["name"]) for p in places]
        )
        return next((p for p in places if p["id"] == match[0]), None) if found else None

    def inside(place, payload):
        """Returns True if a decrypted location is inside a saved place."""
        data = payload["data"]
        accuracy = float(data.get("accuracy") or 25)
        return bool(
            household_alerts.match(float(data["lat"]), float(data["lon"]), [place], accuracy)
        )

    def notify_when(db, alexa, link, member, place, event):
        """Starts a watch for a member reaching or leaving a place, asking for reminders
        permission first.
        """
        account_id, name = member
        _, payload = latest(db, account_id)
        where = "home" if alexa_arrivals.is_home(place["name"]) else f"at {place['name']}"
        if event == "arrive" and payload and inside(place, payload):
            return say(f"{name} is already {where}.")
        if event == "leave" and not payload:
            return say(f"I don't know where {name} is right now.")
        if event == "leave" and not inside(place, payload):
            return say(f"{name} isn't {where} right now.")
        if not alexa_arrivals.granted(alexa):
            asked = {"m": account_id, "p": place["id"], "e": event}
            return alexa_arrivals.ask_permission(json.dumps(asked))
        address = alexa_arrivals.endpoint(alexa)
        user = (alexa_arrivals.system(alexa).get("user") or {}).get("userId") or ""
        if not address or not user or len(user) > 300:
            return say("I can't set that up from this device.")
        watches = db.scalars(select(AlexaWatch).where(AlexaWatch.link_id == link.id)).all()
        for watch in watches:
            if (watch.member_id, watch.place_id, watch.event) == (account_id, place["id"], event):
                db.delete(watch)
        if len(watches) >= alexa_arrivals.MAX_WATCHES:
            return say("You're already waiting on too many people. Try again later.")
        now = time.time()
        db.add(
            AlexaWatch(
                id=secrets.token_hex(16),
                link_id=link.id,
                member_id=account_id,
                place_id=place["id"],
                place_name=place["name"][:80],
                event=event,
                alexa_user=user,
                api_endpoint=address,
                created=now,
                expires=now + alexa_arrivals.WATCH_SECONDS,
                attempts=0,
            )
        )
        db.commit()
        return say(alexa_arrivals.promise(name, place["name"], event))

    def permission_answer(db, alexa, link):
        """Carries on after Alexa asked by voice for permission to set reminders."""
        request = alexa.get("request") or {}
        
        if request.get("name") != "AskFor":
            return say("Okay.")
        
        payload = request.get("payload") or {}
        scopes = payload.get("permissionScopes") or []
        
        accepted = any(
            scope.get("permissionScope") == alexa_arrivals.REMINDERS
            and scope.get("status") == "ACCEPTED"
            for scope in scopes
        )
        
        if not accepted:
            return say("Reminder permission was not granted.")
        try:
            asked = json.loads(request.get("token") or "")
        except ValueError:
            asked = {}
        member = next((m for m in household(db) if m[0] == asked.get("m")), None)
        place = next((p for p in server_places(db) if p["id"] == asked.get("p")), None)
        if not member or not place:
            return say("Please ask me again.")
        event = "leave" if asked.get("e") == "leave" else "arrive"
        return notify_when(db, alexa, link, member, place, event)

    def wake_up(db, alexa, link):
        """Amazon woke the skill because a watched member arrived or left: sets the spoken
        reminder.
        """
        message = (alexa.get("request") or {}).get("message") or {}
        watch = db.get(AlexaWatch, str(message.get("watch") or ""))
        user = (alexa_arrivals.system(alexa).get("user") or {}).get("userId")
        if watch and watch.link_id == link.id and watch.alexa_user == user and watch.happened:
            name = member_name(db, watch.member_id)
            text = alexa_arrivals.announcement(name, watch.place_name, watch.event)
            if alexa_arrivals.set_reminder(alexa, text):
                db.delete(watch)
            else:
                watch.notified = None  # let the next round ask the relay again
            db.commit()
        return {"version": "1.0", "response": {}}

    def watch_fix(db, device, lat, lon, accuracy):
        """Marks this member's watches as happened when a new location is inside the place (an
        arrival) or clearly away from it (a departure). Called for every location the server
        reads; the caller commits.
        """
        now = time.time()
        watches = db.scalars(
            select(AlexaWatch).where(
                AlexaWatch.member_id == device.account_id,
                AlexaWatch.happened.is_(None),
                AlexaWatch.expires > now,
            )
        ).all()
        if not watches:
            return
        places = {p["id"]: p for p in server_places(db)}
        for watch in watches:
            place = places.get(watch.place_id)
            if not place:
                continue
            if watch.event == "leave":
                done = household_alerts.clearly_outside(lat, lon, place, accuracy)
            else:
                done = household_alerts.match(lat, lon, [place], accuracy) is not None
            if done:
                watch.happened = now

    def send_wake_ups(db):
        """Background job: asks the relay to wake the skill for watches that happened, and clears
        ones that expired or never got through.
        """
        relay, now = store().get("relay"), time.time()
        for watch in db.scalars(select(AlexaWatch)).all():
            if watch.happened is None:
                if watch.expires < now:
                    db.delete(watch)
                continue
            if now - watch.happened > alexa_arrivals.NOTICE_SECONDS or not relay:
                db.delete(watch)
                continue
            if watch.notified and now - watch.notified < alexa_arrivals.RETRY_SECONDS:
                continue
            watch.attempts += 1
            if alexa_arrivals.wake(relay, watch):
                watch.notified = now
        db.commit()

    @app.get("/alexa/info")
    def info():
        """Tells the Nära Hem relay that this server has Alexa turned on."""
        return {"service": "nara-hem", "alexa": True, "store": bool(store())}

    @app.post("/alexa/skill")
    async def skill(request: Request, background_tasks: BackgroundTasks):
        """Answers Alexa. Requests come through the Nära Hem relay: signed by Amazon, or from the
        skill's Amazon-hosted forwarder, which can't sign, carrying this server's own link token.
        """
        raw = await request.body()
        try:
            alexa = json.loads(raw)
            system = (alexa.get("context") or {}).get("System") or {}
            asked = (system.get("application") or {}).get("applicationId")
        except (ValueError, AttributeError):
            return JSONResponse({"detail": "Not a request from Amazon"}, 400)
        with Session(engine) as db:
            skill_id = store().get("skill_id")
            if not skill_id or asked != skill_id:
                return JSONResponse({"detail": "This server doesn't know that skill"}, 400)
            # Amazon holds the relay's sealed token, and the relay passes this server's own token
            # alongside the request.
            token = request.headers.get("x-narahem-alexa-token") or ""
            try:
                if request.headers.get("signature-256"):
                    alexa_verify.check(request.headers, raw, alexa)
                elif token:
                    alexa_verify.recent(alexa)
                else:
                    raise alexa_verify.NotFromAmazon("Unsigned and no link token")
            except alexa_verify.NotFromAmazon:
                return JSONResponse({"detail": "Not a request from Amazon"}, 400)
            link = db.scalar(select(AlexaLink).where(AlexaLink.access == digest(token)))
            # A wake-up can come hours after anyone last spoke to the skill, with the token Amazon
            # last had. It can only speak for a watch this link set up, so an expired token still
            # counts for it.
            wake = (alexa.get("request") or {}).get("type") == "Messaging.MessageReceived"
            if (
                not token
                or not link
                or link.kind != "store"
                or (link.access_expires < time.time() and not wake)
                or not current_link(db, link)
            ):
                return say(
                    "Please link Nara Hem to your account in the Alexa app, signing in as your "
                    "household's administrator.",
                    link=True,
                )
            if time.time() - (link.last_used or 0) > 60:
                link.last_used = time.time()
                db.commit()
            return answer(db, alexa, link, background_tasks)

    return {"fix": watch_fix, "send": send_wake_ups}
