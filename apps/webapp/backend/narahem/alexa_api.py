"""Alexa: "Alexa, ask Nara Hem where Maya is" and "... to find Maya's phone".

Off unless the server is started with NARAHEM_ALLOW_ALEXA=true. The household's admin makes a
private skill in their own Amazon developer account (docs/alexa.md) and links it by signing in
with their admin email and password. The admin can revoke the link in Admin settings at any time,
and changing the admin password ends it too.

Households can also use the published Nära Hem skill from the Alexa store instead. Its requests
come through the Nära Hem Alexa relay (deploy/cloudflare/alexa-relay-worker.mjs), which links to
this server as a sign-in client with a PKCE check and keeps no database. The relay's address and
the store skill's ID are built into official images (image_defaults.py) or set with
NARAHEM_ALEXA_RELAY_URL and NARAHEM_ALEXA_STORE_SKILL_ID.

Alexa answers with what the admin's browser sees: everyone sharing their location. Rings are
signed with the server's enrollment key, which the phones already accept from the admin.
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
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem import alexa_speech, alexa_verify, household_alerts, image_defaults
from narahem.app import DUMMY_HASH, HASHER, digest, trusted_accounts
from narahem.data_service import audit, canonical
from narahem.models import (
    Account,
    AlexaLink,
    ClientDevice,
    EncryptedRecord,
    FindPhoneCapability,
    LatestState,
    ServiceState,
    Settings,
)
from narahem.schemas import FindCommandInput, Input

ENVIRONMENT = "NARAHEM_ALLOW_ALEXA"
CLIENT_ID = "nara-hem"
RELAY_CLIENT_ID = "nara-hem-relay"
SERVICE_ID = "0" * 32
CODE_SECONDS = 300
ACCESS_SECONDS = 3600

# Where Amazon's Alexa app may send the admin back after signing in (one per region).
REDIRECT_HOSTS = ("pitangui.amazon.com", "layla.amazon.com", "alexa.amazon.co.jp")
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
    """Returns "own" or "store" for a sign-in request from Amazon or the Nära Hem relay with the
    right return address, or None.
    """
    if fields["client_id"] == CLIENT_ID and redirect_allowed(fields["redirect_uri"]):
        return "own"
    relay = store().get("relay")
    if (
        relay
        and fields["client_id"] == RELAY_CLIENT_ID
        and fields["redirect_uri"] == relay + "/callback"
        and fields.get("code_challenge_method") == "S256"
        and len(fields.get("code_challenge", "")) == 43
    ):
        return "store"
    return None


def redirect_allowed(uri):
    """Returns True if uri is Amazon's account-linking return address."""
    parts = urlsplit(uri or "")
    return (
        parts.scheme == "https"
        and parts.hostname in REDIRECT_HOSTS
        and parts.port is None
        and parts.path.startswith("/api/skill/link/")
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


class SkillInput(Input):
    """The skill ID from the Alexa developer console."""

    skill_id: str = Field(pattern=r"^amzn1\.ask\.skill\.[0-9a-f-]{36}$")


def install(
    app,
    *,
    admin,
    alert_memory,
    cipher,
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

    def settings(db):
        """Returns the saved skill ID and client secret, creating the secret the first time."""
        row = db.get(Settings, 1)
        saved = json.loads(cipher.decrypt(row.alexa.encode())) if row.alexa else {}
        if not saved.get("secret"):
            saved["secret"] = secrets.token_urlsafe(32)
            row.alexa = cipher.encrypt(json.dumps(saved).encode()).decode()
            db.commit()
        return saved

    def save(db, saved):
        """Encrypts and stores the Alexa settings."""
        db.get(Settings, 1).alexa = cipher.encrypt(json.dumps(saved).encode()).decode()
        db.commit()

    def status(db):
        """Returns everything the Admin settings card shows."""
        saved = settings(db)
        base = app.state.public_url
        links = db.scalars(
            select(AlexaLink).where(AlexaLink.access.is_not(None)).order_by(AlexaLink.created)
        )
        published = store()
        return {
            "store": bool(published),
            "skill_id": saved.get("skill_id"),
            "client_id": CLIENT_ID,
            "client_secret": saved["secret"],
            "authorization_url": base + "/alexa/link",
            "token_url": base + "/alexa/token",
            "endpoint": base + "/alexa/skill",
            "links": [
                {
                    "id": link.id,
                    "kind": link.kind,
                    "created": link.created,
                    "last_used": link.last_used,
                }
                for link in links
            ],
        }

    @app.get("/api/alexa")
    def alexa_status(auth=Depends(admin), db: Session = Depends(database)):
        """Returns the Alexa skill settings and the linked Alexa accounts."""
        return status(db)

    @app.put("/api/alexa")
    def alexa_skill(body: SkillInput, auth=Depends(admin), db: Session = Depends(database)):
        """Saves the skill ID. Requests from any other skill are refused."""
        saved = settings(db)
        saved["skill_id"] = body.skill_id
        save(db, saved)
        audit(db, "alexa.skill.saved", auth[0].id)
        db.commit()
        return status(db)

    @app.post("/api/alexa/secret")
    def alexa_secret(auth=Depends(admin), db: Session = Depends(database)):
        """Makes a new client secret and ends every link, for when the old one may be known."""
        saved = settings(db)
        saved["secret"] = secrets.token_urlsafe(32)
        save(db, saved)
        db.query(AlexaLink).delete()
        audit(db, "alexa.secret.replaced", auth[0].id)
        db.commit()
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
        kind = client_allowed(fields)
        if not kind:
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
                kind=kind,
                challenge=fields["code_challenge"] if kind == "store" else None,
                password_mark=digest(account.password),
                created=time.time(),
            )
            db.add(link)
            db.query(AlexaLink).filter(
                AlexaLink.access.is_(None), AlexaLink.code_expires < time.time()
            ).delete()
            audit(db, "alexa.linked", account.id, link.id, kind=kind)
            db.commit()
        query = urlencode({"state": fields["state"], "code": code})
        joiner = "&" if "?" in fields["redirect_uri"] else "?"
        return RedirectResponse(fields["redirect_uri"] + joiner + query, status_code=303)

    def client_secret(request, form):
        """Returns the client ID and secret Amazon sent, by HTTP Basic or in the form."""
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                pair = base64.b64decode(header[6:]).decode()
                return tuple(pair.split(":", 1))
            except (ValueError, UnicodeDecodeError):
                return "", ""
        return form.get("client_id", ""), form.get("client_secret", "")

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
        client, secret = client_secret(request, form)
        relay = client == RELAY_CLIENT_ID and bool(store())
        with Session(engine) as db:
            expected = settings(db)["secret"]
            # The relay is a public client: its codes only ever go back to the relay's own
            # address, and it must prove it started the sign-in (PKCE).
            if not relay and (client != CLIENT_ID or not secrets.compare_digest(secret, expected)):
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            grant = form.get("grant_type")
            if grant == "authorization_code":
                link = db.scalar(
                    select(AlexaLink).where(AlexaLink.code == digest(form.get("code", "")))
                )
                if (
                    not link
                    or link.code_expires < time.time()
                    or link.redirect_uri != form.get("redirect_uri")
                    or (link.kind == "store") != relay
                    or (
                        relay
                        and not secrets.compare_digest(
                            challenge_for(form.get("code_verifier", "")), link.challenge or ""
                        )
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
            if link and (link.kind == "store") != relay:
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
        """Returns every active member as (account_id, name)."""
        accounts = db.scalars(
            select(Account)
            .where(Account.status == "active", trusted_accounts())
            .order_by(Account.username)
        )
        return [(a.id, member_name(db, a.id)) for a in accounts]

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

    def where_is(db, member, alexa):
        """Says where a member is, from the latest location their phone shared."""
        account_id, name = member
        latest = db.get(LatestState, ("location", account_id))
        record = db.get(EncryptedRecord, latest.record_id) if latest else None
        sender = db.get(ClientDevice, record.device_id) if record else None
        if not sender or sender.status != "approved":
            return f"I don't have a location for {name}."
        if not sender.sharing:
            return f"{name} isn't sharing a location right now."
        try:
            payload = trip_processor.open_record(json.loads(record.envelope)["body"])
        except (HTTPException, KeyError, ValueError):
            return f"I don't have a location for {name}."
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
        intent = request.get("intent", {})
        name = intent.get("name", "")
        members = household(db)
        pending = (alexa.get("session", {}).get("attributes") or {}).get("pending")
        if name == "AMAZON.YesIntent" and pending:
            member = next((m for m in members if m[0] == pending.get("account")), None)
            if member:
                return act(db, pending.get("ask"), member, alexa, link, background_tasks)
        if name in ("AMAZON.NoIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return say("Okay.")
        if name in ("WhereIsIntent", "FindPhoneIntent"):
            heard = ((intent.get("slots") or {}).get("person") or {}).get("value") or ""
            ask = "where" if name == "WhereIsIntent" else "ring"
            found, member = alexa_speech.match_name(heard, members)
            if found == "exact":
                return act(db, ask, member, alexa, link, background_tasks)
            if found == "close":
                return say(
                    f"Did you mean {member[1]}?",
                    end=False,
                    attributes={"pending": {"ask": ask, "account": member[0]}},
                )
            who = f"anyone called {heard}" if heard else "who you meant"
            return say(f"I couldn't find {who}. You can ask about {alexa_speech.names(members)}.")
        return say(
            "You can say, where is Maya, or find Maya's phone. "
            f"Your household is {alexa_speech.names(members)}.",
            end=False,
        )

    def act(db, ask, member, alexa, link, background_tasks):
        """Answers a where-is question or rings a phone."""
        if ask == "ring":
            return say(ring(db, member, link, background_tasks))
        return say(where_is(db, member, alexa))

    @app.get("/alexa/info")
    def info():
        """Tells the Nära Hem relay that this server has Alexa turned on."""
        return {"service": "nara-hem", "alexa": True, "store": bool(store())}

    @app.post("/alexa/skill")
    async def skill(request: Request, background_tasks: BackgroundTasks):
        """Answers Alexa. Requests for your own skill must be signed by Amazon. Requests for the
        store skill come through the Nära Hem relay: signed by Amazon, or from the skill's
        Amazon-hosted forwarder, which can't sign, carrying this server's own link token.
        """
        raw = await request.body()
        try:
            alexa = json.loads(raw)
            system = (alexa.get("context") or {}).get("System") or {}
            asked = (system.get("application") or {}).get("applicationId")
        except (ValueError, AttributeError):
            return JSONResponse({"detail": "Not a request from Amazon"}, 400)
        with Session(engine) as db:
            skills = {"own": settings(db).get("skill_id"), "store": store().get("skill_id")}
            kind = next((k for k, v in skills.items() if v and v == asked), None)
            if not kind:
                return JSONResponse({"detail": "This server doesn't know that skill"}, 400)
            # Through the relay, Amazon holds the relay's sealed token, and the relay passes this
            # server's own token alongside the request.
            token = (
                request.headers.get("x-narahem-alexa-token")
                if kind == "store"
                else (system.get("user") or {}).get("accessToken")
            ) or ""
            signed = request.headers.get("signature-256") or kind == "own"
            try:
                if signed:
                    alexa_verify.check(request.headers, raw, alexa)
                elif token:
                    alexa_verify.recent(alexa)
                else:
                    raise alexa_verify.NotFromAmazon("Unsigned and no link token")
            except alexa_verify.NotFromAmazon:
                return JSONResponse({"detail": "Not a request from Amazon"}, 400)
            link = db.scalar(select(AlexaLink).where(AlexaLink.access == digest(token)))
            if (
                not token
                or not link
                or link.kind != kind
                or link.access_expires < time.time()
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
