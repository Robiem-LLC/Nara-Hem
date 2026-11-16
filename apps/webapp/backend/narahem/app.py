"""Persistent server setup. Location and cryptographic device APIs are gated."""

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import smtplib
import ssl
import time
from contextlib import asynccontextmanager
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlsplit

from argon2 import PasswordHasher
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import (
    create_engine,
    event,
    or_,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from narahem import image_defaults, review_mode, schema, texting
from narahem.models import (
    Account,
    AccountApproval,
    Challenge,
    LoginSession,
    Outbox,
    PasswordReset,
    Rate,
    Settings,
)
from narahem.trip_processing import TripProcessor

# Per-account login backoff: 1 s, 2 s, 4 s ... up to the cap after wrong passwords; a correct
# password clears it.
LOGIN_FREE_FAILURES = 3
LOGIN_MAX_DELAY_SECONDS = 300

# Per-account ceiling (failures, window seconds) against slow distributed guessing.
LOGIN_ACCOUNT_CEILING = (50, 3600)
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))

# A phone that missed the rotation response may retry its old token briefly; that is not treated as
# theft.
REFRESH_REUSE_GRACE_SECONDS = 120


def app_links():
    """Returns the iPhone and Android app download links for invitations (None to leave one out).
    Official images have them built in; NARAHEM_IOS_APP_URL and NARAHEM_ANDROID_APP_URL override
    them, and "none" leaves one out.
    """
    links = []
    for name in ("NARAHEM_IOS_APP_URL", "NARAHEM_ANDROID_APP_URL"):
        value = image_defaults.setting(name)
        links.append(None if value.lower() in ("", "none") else value)
    return tuple(links)


def account_trusted(account, db):
    """Returns True if the account has verified its email or been approved by the admin."""
    return bool(account and (account.verified or db.get(AccountApproval, account.id)))


def trusted_accounts():
    """SQL filter for accounts that pass account_trusted()."""
    return or_(Account.verified.is_(True), Account.id.in_(select(AccountApproval.account_id)))


def digest(value):
    """Returns the SHA-256 hex digest of a string. Used to store tokens without storing the
    tokens themselves.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def email_address(value):
    """Normalizes an email address to lower case and validates it, raising a 422 if invalid."""
    value = value.strip().lower()
    local, at, domain = value.partition("@")
    labels = domain.split(".")
    # Plain checks rather than a pattern, so even a long odd input is checked in one pass.
    if (
        len(value) > 254
        or not at
        or not local
        or len(labels) < 2
        or not all(labels)
        or any(c.isspace() or c in "<>@" for c in local + domain)
    ):
        raise HTTPException(422, "Enter a valid email address")
    return value


def contact(value):
    """Returns ("phone", +E.164) for a phone number or ("email", address) for an email address,
    raising a 422 if it is neither.
    """
    if texting.looks_like_phone(value):
        return "phone", texting.phone_number(value)
    return "email", email_address(value)


def find_account(db, value):
    """Returns the account with this email address or phone number, or None. Raises a 422 for
    something that is neither.
    """
    kind, normalized = contact(value)
    column = Account.phone if kind == "phone" else Account.email
    return db.scalar(select(Account).where(column == normalized))


def username(value):
    """Validates a username: 3 to 64 letters, digits, dots, dashes or underscores."""
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,64}", value):
        raise HTTPException(422, "Username: 3–64 letters, numbers, dots, dashes or underscores")
    return value


def client_ip(request):
    """Returns the direct peer address. Behind a proxy every client shares it, so security limits
    are keyed by account or token rather than IP alone.
    """
    return request.client.host if request.client else ""


def secret_file(path, generator):
    """Reads a secret file, creating it with owner-only permissions on first use."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    value = generator()
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value


def create_app(
    database_url=None,
    data_dir=None,
    public_url=None,
    allow_http=None,
    mailer=None,
    mail_worker=True,
    texter=None,
    notifier=None,
    google_maps_api_key=None,
):
    """Creates the FastAPI app: database, encryption key, middleware, routes and background
    workers.
    """
    from narahem import mobile_enrollment, web_pages
    from narahem.account_api import (
        admin_settings,
        contact_change,
        enrollment,
        members,
        revocation,
        server,
        sessions,
    )
    from narahem.data_service import (
        initialize_service,
    )
    from narahem.device_api import install

    database_url = database_url or os.environ["DATABASE_URL"]
    texter = texter or texting.Textbelt()

    directory = Path(data_dir or os.environ.get("NARAHEM_DATA_DIR", "/data"))

    public_url = (public_url or os.environ["NARAHEM_PUBLIC_URL"]).rstrip("/")

    allow_http = (
        allow_http if allow_http is not None else os.environ.get("NARAHEM_ALLOW_HTTP") == "1"
    )

    maps_key = (
        google_maps_api_key
        if google_maps_api_key is not None
        else os.environ.get("NARAHEM_GOOGLE_MAPS_API_KEY", "")
    ).strip()

    url = urlsplit(public_url)

    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
        or (url.scheme == "http" and not allow_http)
    ):
        raise ValueError(
            "NARAHEM_PUBLIC_URL must be an HTTPS origin (HTTP requires explicit development opt-in)"
        )

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    engine = create_engine(database_url, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            """Enables foreign key enforcement for SQLite connections."""
            connection.execute("PRAGMA foreign_keys=ON")

    key_file = directory / "server.key"

    # Never create a new encryption key for an existing database.
    from sqlalchemy import inspect

    if not key_file.exists() and inspect(engine).has_table("settings"):
        raise RuntimeError("Server key is missing; restore the server data volume")

    cipher = Fernet(secret_file(key_file, lambda: Fernet.generate_key().decode()).encode())

    trip_processor = TripProcessor(directory)

    bootstrap_file = directory / "bootstrap-token"

    def initialize():
        """Runs migrations and first-run setup at startup."""
        schema.upgrade(engine)
        with Session(engine) as db:
            settings = db.get(Settings, 1)
            configured_token = (
                (os.environ.get("NARAHEM_SETUP_TOKEN") or None)
                if not settings or not settings.household
                else None
            )
            if configured_token is not None:
                if (
                    not 8 <= len(configured_token) <= 256
                    or configured_token.strip() != configured_token
                ):
                    raise ValueError(
                        "NARAHEM_SETUP_TOKEN must contain 8–256 characters without surrounding "
                        "whitespace"
                    )
                # A configured token may replace an unused one; after setup it is ignored.
                fd = os.open(bootstrap_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(configured_token)
                bootstrap_file.chmod(0o600)
                if settings:
                    settings.bootstrap_hash = digest(configured_token)
                    db.commit()
            if settings is None:
                fresh_generated_token = not bootstrap_file.exists()
                token = secret_file(bootstrap_file, lambda: secrets.token_urlsafe(32))
                db.add(Settings(id=1, bootstrap_hash=digest(token)))
                db.commit()
                if fresh_generated_token:
                    print("NARAHEM FIRST-RUN SETUP TOKEN: " + token, flush=True)
                    print(
                        "Enter this token on the setup page. Keep container logs private.",
                        flush=True,
                    )
            elif settings.household:
                bootstrap_file.unlink(missing_ok=True)
            elif not bootstrap_file.exists():
                raise RuntimeError(
                    "Bootstrap token file is missing; restore the server data volume"
                )
            if settings and settings.smtp:
                try:
                    cipher.decrypt(settings.smtp.encode())
                except InvalidToken:
                    raise RuntimeError(
                        "Server key does not match stored credentials; restore the matching server "
                        "data volume"
                    ) from None

        warning = review_mode.check()
        if warning:
            print(warning, flush=True)
        try:
            initialize_service(engine, directory, cipher)
        except InvalidToken:
            raise RuntimeError(
                "Server key does not match stored credentials; restore matching server data"
            ) from None

    @asynccontextmanager
    async def lifespan(app):
        """Initializes the app, then runs the background workers until shutdown."""
        initialize()

        async def worker(*jobs):
            """Runs the jobs every few seconds, logging failures without details that could leak
            secrets.
            """
            while True:
                await asyncio.sleep(5)
                try:
                    for job in jobs:
                        await asyncio.to_thread(job)
                except (SQLAlchemyError, OSError, smtplib.SMTPException):
                    # Log only the exception type: messages can contain addresses or credentials.
                    pass

        tasks = (
            [
                asyncio.create_task(worker(worker_batch, app.state.deliveries)),
                asyncio.create_task(worker(app.state.place_names)),
            ]
            if mail_worker
            else []
        )
        yield
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if trip_processor and trip_processor.roads:
            trip_processor.roads.stop()
        engine.dispose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    app.state.engine, app.state.initialize, app.state.cipher = engine, initialize, cipher

    app.state.trip_processor = trip_processor
    app.state.public_url = public_url

    @app.middleware("http")
    async def boundaries(request, call_next):
        """Middleware that checks the Host header, limits request sizes and adds security
        headers.
        """
        if request.url.path != "/healthz":
            if request.headers.get("host", "").lower() != url.netloc.lower():
                return JSONResponse({"detail": "Unrecognized server address"}, 400)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                native = request.headers.get("authorization", "").startswith("Bearer ") or (
                    request.headers.get("x-narahem-client") == "native"
                    and request.url.path
                    in (
                        "/api/login",
                        "/api/enrollment/request",
                        "/api/enrollment/verify",
                        "/api/enrollment/claim",
                        "/api/invitation-requests",
                        "/api/native/session/refresh",
                        "/api/native/session/revoke",
                    )
                )
                # Amazon calls the Alexa token and skill addresses from its own servers.
                amazon = request.url.path in ("/alexa/token", "/alexa/skill")
                if origin != public_url and not (origin is None and (native or amazon)):
                    return JSONResponse({"detail": "Origin rejected"}, 403)
                length = request.headers.get("content-length", "")
                # Large enough for a 12-record GPS batch sealed for every recipient.
                maximum = (
                    1048576
                    if request.url.path in ("/api/records", "/api/records/batch")
                    else 32768
                    if request.url.path == "/api/push/config"
                    else 16384
                    if request.url.path in ("/api/roster", "/alexa/skill")
                    else 8192
                )
                if not length.isdecimal() or int(length) > maximum:
                    return JSONResponse({"detail": "Request size rejected"}, 413)
                if len(await request.body()) > maximum:
                    return JSONResponse({"detail": "Request size rejected"}, 413)
                # The Alexa sign-in page and Amazon's token requests are forms.
                form = request.url.path in ("/alexa/link", "/alexa/token")
                if not form and not request.headers.get("content-type", "").startswith(
                    "application/json"
                ):
                    return JSONResponse({"detail": "JSON required"}, 415)
        request.state.maps_nonce = secrets.token_urlsafe(24) if maps_key else ""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'wasm-unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://tile.openstreetmap.org; "
            "connect-src 'self' https://nominatim.openstreetmap.org "
            "https://tile.openstreetmap.org; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )
        if maps_key:
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'nonce-{request.state.maps_nonce}' 'strict-dynamic' 'unsafe-eval' "
                "https: blob:; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: blob: https://tile.openstreetmap.org "
                "https://*.googleapis.com https://*.gstatic.com https://*.google.com "
                "https://*.googleusercontent.com; "
                "connect-src 'self' https://nominatim.openstreetmap.org "
                "https://tile.openstreetmap.org https://*.googleapis.com https://*.gstatic.com "
                "https://*.google.com data: blob:; "
                "font-src 'self' https://fonts.gstatic.com; "
                "frame-src https://*.google.com; "
                "worker-src blob:; "
                "frame-ancestors 'none'; "
                "base-uri 'none'; "
                "form-action 'self'"
            )
        if url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path == "/alexa/link":
            from narahem import alexa_api

            # After the admin signs in, the form sends the Alexa app back to the Nära Hem relay.
            relay = alexa_api.store().get("relay")
            response.headers["Content-Security-Policy"] = response.headers[
                "Content-Security-Policy"
            ].replace("form-action 'self'", f"form-action 'self' {relay or ''}".strip())
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        """Returns a generic 503 for database errors."""
        return JSONResponse({"detail": "Database operation unavailable"}, 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        """Returns a 422 listing the invalid fields without echoing the submitted values."""
        fields = []
        for issue in error.errors():
            location = [str(part) for part in issue["loc"] if part != "body"]
            kind, context = issue["type"], issue.get("ctx", {})
            message = "Enter a valid value."
            if kind == "missing":
                message = "This field is required."
            elif kind == "string_too_short":
                message = f"Use at least {context['min_length']} characters."
            elif kind == "string_too_long":
                message = f"Use no more than {context['max_length']} characters."
            elif kind == "string_pattern_mismatch":
                message = "Check the allowed characters."
            elif kind == "json_invalid":
                message = "The request must contain valid JSON."
            fields.append({"field": ".".join(location), "message": message})
        return JSONResponse(
            {"detail": "Please correct the highlighted fields.", "fields": fields}, 422
        )

    def database():
        """Yields a database session for one request."""
        with Session(engine) as db:
            yield db

    def rate(request, scope, limit=10, shared=False):
        """Raises a 429 once a client exceeds limit requests for scope in the current window.
        With shared, the limit applies to all clients together.
        """
        key = digest(f"{'all-clients' if shared else client_ip(request)}:{scope}")
        with Session(engine) as db:
            db.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
            item, now = db.get(Rate, key), time.time()
            if item is None:
                item = Rate(id=key, started=now, count=0)
                db.add(item)
            elif now - item.started >= 900:
                item.started, item.count = now, 0
            if item.count >= limit:
                raise HTTPException(429, "Too many requests; try again later")
            item.count += 1
            db.query(Rate).filter(Rate.started < now - 86400).delete()
            db.commit()

    def login_keys(address):
        """Returns the backoff and ceiling rate-limit keys for an account's logins."""
        return digest(f"login-backoff:{address}"), digest(f"login-account:{address}")

    def login_guard(address):
        """Raises a 429 while the account is in backoff or past its failure ceiling. Only
        failures count, and limits are per account.
        """
        backoff_key, account_key = login_keys(address)
        with Session(engine) as db:
            db.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
            now = time.time()
            backoff = db.get(Rate, backoff_key)
            if backoff and backoff.count >= LOGIN_FREE_FAILURES:
                wait = min(LOGIN_MAX_DELAY_SECONDS, 2 ** (backoff.count - LOGIN_FREE_FAILURES)) - (
                    now - backoff.started
                )
                if wait > 0:
                    raise HTTPException(
                        429,
                        "Too many incorrect attempts; try again shortly",
                        headers={"Retry-After": str(math.ceil(wait))},
                    )
            limit, window = LOGIN_ACCOUNT_CEILING
            row = db.get(Rate, account_key)
            if row and now - row.started < window and row.count >= limit:
                raise HTTPException(
                    429,
                    "Too many incorrect attempts; try again later",
                    headers={"Retry-After": str(math.ceil(window - (now - row.started)))},
                )

    def login_outcome(address, succeeded):
        """Records a login result: success clears the backoff, failure increases it."""
        backoff_key, account_key = login_keys(address)
        with Session(engine) as db:
            db.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
            now = time.time()
            if succeeded:
                db.query(Rate).filter(Rate.id == backoff_key).delete()
            else:
                backoff = db.get(Rate, backoff_key)
                if backoff is None:
                    backoff = Rate(id=backoff_key, started=now, count=0)
                    db.add(backoff)
                backoff.started, backoff.count = now, backoff.count + 1
                window = LOGIN_ACCOUNT_CEILING[1]
                row = db.get(Rate, account_key)
                if row is None:
                    row = Rate(id=account_key, started=now, count=0)
                    db.add(row)
                elif now - row.started >= window:
                    row.started, row.count = now, 0
                row.count += 1
            db.query(Rate).filter(Rate.started < now - 86400).delete()
            db.commit()

    def current(request: Request, db: Session = Depends(database)):
        """Returns the signed-in account and session from the session cookie or a bearer token.
        Raises a 401 if there is none.
        """
        bearer = request.headers.get("authorization", "")
        token = (
            bearer[7:]
            if bearer.startswith("Bearer ")
            else request.cookies.get("narahem_session", "")
        )
        session = db.get(LoginSession, digest(token))
        if not session or session.expires <= time.time():
            raise HTTPException(401, "Sign in required")
        account = db.get(Account, session.account_id)
        if not account or account.status != "active":
            raise HTTPException(401, "Sign in required")
        if (
            not bearer.startswith("Bearer ")
            and request.method not in ("GET", "HEAD")
            and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf)
        ):
            raise HTTPException(403, "Session confirmation required")
        return account, session

    def admin(auth=Depends(current)):
        """Returns the signed-in account and session, raising a 403 unless it is the admin."""
        if auth[0].role != "admin":
            raise HTTPException(403, "Administrator required")
        return auth

    def mail_settings(db):
        """Returns the decrypted SMTP settings, or None if mail is not configured."""
        settings = db.get(Settings, 1)
        if not settings.smtp:
            raise HTTPException(409, "Configure email first")
        return json.loads(cipher.decrypt(settings.smtp.encode()))

    def deliver(config, recipient, subject, body):
        """Sends one email over SMTP, or through the test mailer when set."""
        if mailer:
            mailer(config, recipient, subject, body)
            return
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = config["sender"], recipient, subject
        message.set_content(body)
        context = ssl.create_default_context()
        client = (
            smtplib.SMTP_SSL(config["host"], config["port"], timeout=10, context=context)
            if config["mode"] == "tls"
            else smtplib.SMTP(config["host"], config["port"], timeout=10)
        )
        with client:
            if config["mode"] == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if config["username"]:
                client.login(config["username"], config["password"] or "")
            client.send_message(message)

    def texting_key(db):
        """Returns the Textbelt key in use and where it came from. The environment wins."""
        key = texting.environment_key()
        if key:
            return key, "environment"
        settings = db.get(Settings, 1)
        if settings and settings.sms:
            return cipher.decrypt(settings.sms.encode()).decode(), "settings"
        return None, None

    def check_texting(db):
        """Checks the key in use with Textbelt, records the result and returns the settings."""
        settings = db.get(Settings, 1)
        key, _ = texting_key(db)
        settings.sms_checked = time.time()
        settings.sms_checked_key = digest(key) if key else None
        settings.sms_valid, settings.sms_quota, settings.sms_error = False, None, None
        if key:
            try:
                settings.sms_quota = texter.quota(key)
                settings.sms_valid = settings.sms_quota > 0
                if not settings.sms_valid:
                    settings.sms_error = (
                        "This key has no texts left, or Textbelt doesn't recognize it."
                    )
            except texting.TextingError as error:
                settings.sms_error = str(error)
        db.commit()
        return settings

    def texting_on(db):
        """Returns the key if texting is set up and its last check passed, otherwise None."""
        key, _ = texting_key(db)
        settings = db.get(Settings, 1)
        if key and settings.sms_valid and settings.sms_checked_key == digest(key):
            return key
        return None

    def channels(db, account):
        """Returns how the server can reach this account: "email", "text" or both."""
        found = []
        if account.email and db.get(Settings, 1).smtp:
            found.append("email")
        if account.phone and texting_on(db):
            found.append("text")
        return found

    def notice(db, key, channel, recipient, subject, body):
        """Queues one email or text to a given address or number, whatever the account has now.
        Skipped if that channel isn't set up.
        """
        if channel == "email" and not db.get(Settings, 1).smtp:
            return
        if channel == "text" and not texting_on(db):
            return
        payload = {"channel": channel, "recipient": recipient, "subject": subject, "body": body}
        db.add(
            Outbox(
                id=secrets.token_hex(16),
                account_id=key,
                payload=cipher.encrypt(json.dumps(payload).encode()).decode(),
                created=time.time(),
            )
        )

    def notify(db, account, key, subject, email_body, text_body):
        """Queues the message by email and by text, wherever the account can be reached. Older
        pending messages under the same key are dropped. Returns the channels used.
        """
        db.query(Outbox).filter_by(account_id=key, status="pending").update(
            {Outbox.status: "expired", Outbox.payload: ""}
        )
        used = channels(db, account)
        for channel in used:
            payload = {
                "channel": channel,
                "recipient": account.email if channel == "email" else account.phone,
                "subject": subject,
                "body": email_body if channel == "email" else text_body,
            }
            db.add(
                Outbox(
                    id=secrets.token_hex(16),
                    account_id=key,
                    payload=cipher.encrypt(json.dumps(payload).encode()).decode(),
                    created=time.time(),
                )
            )
        return used

    def send_now(db, account, subject, email_body, text_body):
        """Sends the message straight away by email and by text, wherever the account can be
        reached. Returns the channels that worked; raises a 409 or 502 if none did.
        """
        # Codes only go through email the administrator has tested.
        tested = db.get(Settings, 1).mail_tested
        used = [c for c in channels(db, account) if c == "text" or tested]
        sent = []
        if not used:
            raise HTTPException(
                409,
                "The administrator must configure and test email, or set up text messages, "
                "before codes can be sent",
            )
        for channel in used:
            try:
                if channel == "email":
                    deliver(mail_settings(db), account.email, subject, email_body)
                else:
                    send_text(db, account.phone, text_body)
                sent.append(channel)
            except (OSError, smtplib.SMTPException, texting.TextingError):
                continue
        if not sent:
            raise HTTPException(502, "Could not send the code; try again shortly")
        return sent

    def send_text(db, phone, body):
        """Sends one text with the key in use and records the credit left."""
        key = texting_on(db)
        if not key:
            raise texting.TextingError("Text messages are not set up")
        settings = db.get(Settings, 1)
        try:
            settings.sms_quota = texter.send(key, phone, body)
        except texting.TextingError as error:
            settings.sms_error = str(error)
            raise

    def queue(db, account):
        """Queues an invitation with a new verification link, by email and by text wherever the
        account can be reached. Returns the channels used.
        """
        db.query(Challenge).filter_by(account_id=account.id, used=False).delete()
        token = secrets.token_urlsafe(32)
        db.add(Challenge(id=digest(token), account_id=account.id, expires=time.time() + 1800))
        shown = (
            f"email={quote(account.email, safe='')}"
            if account.email
            else f"phone={quote(account.phone, safe='')}"
        )
        link = f"{public_url}/#verify={token}&{shown}"
        household = db.get(Settings, 1).household or "your household"
        ios, android = app_links()
        sign_in = f"Email: {account.email}" if account.email else f"Phone: {account.phone}"
        apps = "\n".join(
            line
            for line in (
                f"  iPhone (TestFlight): {ios}" if ios else "",
                f"  Android: {android}" if android else "",
            )
            if line
        )
        get_app = f"2. Get the Nära Hem app:\n{apps}\n\n" if apps else ""
        text_apps = " ".join(
            part
            for part in (f"iPhone: {ios}" if ios else "", f"Android: {android}" if android else "")
            if part
        )
        return notify(
            db,
            account,
            account.id,
            f"Nära Hem: you're invited to {household}",
            (
                f"You're invited to {household} on Nära Hem.\n\n"
                f"1. Set up your account within 30 minutes:\n{link}\n\n"
                f"{get_app}"
                f"{3 if apps else 2}. Sign in to the app with:\n"
                f"  Server: {public_url}\n"
                f"  {sign_in}\n"
                "  Password: the one you choose in step 1\n\n"
                "Setting up your account doesn't approve a phone or share anyone's location."
            ),
            f"You're invited to {household} on Nära Hem. Set up your account within 30 minutes: "
            f"{link} "
            + (f"Get the app: {text_apps} " if text_apps else "")
            + f"Then sign in with server {public_url} and "
            + (f"email {account.email}." if account.email else f"phone {account.phone}."),
        )

    def issue_password_reset(db, account):
        """Queues a password reset link to the account's own email and phone. The link is never
        returned to the caller.
        """
        if (
            not account
            or account.status != "active"
            or not account.password
            or not channels(db, account)
        ):
            return False
        db.query(PasswordReset).filter_by(account_id=account.id).delete(synchronize_session=False)
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(id=digest(token), account_id=account.id, expires=time.time() + 1800))
        link = f"{public_url}/#reset={token}"
        notify(
            db,
            account,
            "r:" + account.id,
            "Nära Hem: reset your password",
            (
                f"A password reset was requested for your Nära Hem account.\n"
                f"Use this link within 30 minutes:\n{link}\n\n"
                "If you did not request it, ignore this email.\n"
                "This does not change your encrypted device keys."
            ),
            f"Nära Hem password reset, valid for 30 minutes: {link} "
            "If you didn't ask for it, ignore this text.",
        )
        return True

    def flush_mail(db):
        """Sends queued emails and texts, backing off after failures. Also returns, per outbox
        key, why each channel failed this time: Textbelt's reason for a text, and for email only
        that it will be retried, so mail server details stay out of replies.
        """
        config, sent, waiting, failed = None, 0, False, {}
        for item in db.scalars(
            select(Outbox)
            .where(Outbox.status == "pending", Outbox.retry_at <= time.time())
            .order_by(Outbox.created)
            .limit(20)
            .with_for_update(skip_locked=True)
        ).all():
            if item.created < time.time() - 1800:
                item.status, item.payload = "expired", ""
                continue
            payload = json.loads(cipher.decrypt(item.payload.encode()))
            item.attempts += 1
            try:
                if payload.get("channel") == "text":
                    send_text(db, payload["recipient"], payload["body"])
                else:
                    config = config or mail_settings(db)
                    deliver(config, payload["recipient"], payload["subject"], payload["body"])
            except (OSError, smtplib.SMTPException, texting.TextingError, HTTPException) as error:
                item.retry_at = time.time() + min(300, 2 ** min(item.attempts, 8))
                waiting = True
                channel = "text" if payload.get("channel") == "text" else "email"
                if isinstance(error, texting.TextingError):
                    reason = str(error)
                elif isinstance(error, HTTPException):
                    reason = str(error.detail)
                else:
                    reason = "The mail server didn't accept it."
                failed.setdefault(item.account_id, {})[channel] = reason
                continue
            item.status, item.payload = "sent", ""
            sent += 1
        db.commit()
        return {"sent": sent, "delivery": "pending" if waiting else "sent", "failed": failed}

    def worker_batch():
        """Background job: cleans up phone enrollment, rechecks the texting key now and then,
        and sends queued email and texts.
        """
        mobile_enrollment.cleanup(engine)
        with Session(engine) as db:
            settings = db.get(Settings, 1)
            key, _ = texting_key(db)
            # A new key (say, a changed environment variable) is checked at once; a failed check
            # is retried after 10 minutes, a good one every 6 hours to keep the credit current.
            age = time.time() - (settings.sms_checked or 0)
            if key and (
                settings.sms_checked_key != digest(key)
                or age > (21600 if settings.sms_valid else 600)
            ):
                check_texting(db)
            if settings.smtp or texting_on(db):
                flush_mail(db)

    server.install(
        app,
        bootstrap_file=bootstrap_file,
        current=current,
        database=database,
        directory=directory,
        public_url=public_url,
        rate=rate,
        texting_on=texting_on,
    )

    sessions.install(
        app,
        current=current,
        database=database,
        issue_password_reset=issue_password_reset,
        login_guard=login_guard,
        login_outcome=login_outcome,
        rate=rate,
        url=url,
    )

    admin_settings.install(
        app,
        admin=admin,
        cipher=cipher,
        database=database,
        deliver=deliver,
        directory=directory,
        flush_mail=flush_mail,
        mail_settings=mail_settings,
        public_url=public_url,
        rate=rate,
        texting_key=texting_key,
        check_texting=check_texting,
        texting_on=texting_on,
        send_text=send_text,
    )

    members.install(
        app,
        admin=admin,
        cipher=cipher,
        current=current,
        database=database,
        flush_mail=flush_mail,
        issue_password_reset=issue_password_reset,
        public_url=public_url,
        queue=queue,
        rate=rate,
        texting_on=texting_on,
    )

    enrollment.install(app, admin=admin, database=database, queue=queue, rate=rate)

    revocation.install(app, admin=admin, database=database)

    contact_change.install(
        app,
        current=current,
        database=database,
        directory=directory,
        rate=rate,
        deliver=deliver,
        mail_settings=mail_settings,
        send_text=send_text,
        texting_on=texting_on,
        notice=notice,
    )

    install(
        app,
        engine,
        directory,
        cipher,
        database,
        current,
        admin,
        rate,
        notifier,
        trip_processor,
        maps_key,
    )

    mobile_enrollment.install(
        app,
        directory,
        cipher,
        database,
        current,
        admin,
        rate,
        notify,
        send_now,
        lambda db: db.get(Settings, 1),
    )

    from narahem.push_service import install_push

    install_push(app, cipher, database, admin, rate, notifier, directory)

    web_pages.install(app, current=current, maps_key=maps_key)

    return app
