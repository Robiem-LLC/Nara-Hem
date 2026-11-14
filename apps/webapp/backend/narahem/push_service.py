"""Generic push delivery; never accepts plaintext coordinates or place names."""

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException, Request
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from sqlalchemy import select

from narahem import image_defaults
from narahem.data_service import audit, diagnostic
from narahem.models import Account, ClientDevice, PushDelivery, PushSubscription, ServiceState
from narahem.schemas import PushConfig, PushTestInput

# Only relay URLs are built into images; relay tokens are per-server settings.

REGISTRATIONS_FILE = "relay-registrations.json"
REGISTRATION_RETRY_SECONDS = 600

# A new token can take a moment to reach every Cloudflare location, so an early rejection doesn't
# mean it's invalid.
REGISTRATION_GRACE_SECONDS = 600
_registration_dir = None
_registration_lock = threading.Lock()
_failed_registrations = {}
_failure_reasons = {}

# Each relay's label, address setting and manual token setting.
RELAYS = (
    ("iPhone (APNs)", "NARAHEM_PUSH_RELAY_URL", "NARAHEM_PUSH_RELAY_TOKEN"),
    ("Android (FCM)", "NARAHEM_FCM_RELAY_URL", "NARAHEM_FCM_RELAY_TOKEN"),
)

FCM_REASONS = frozenset(
    {
        "INVALID_ARGUMENT",
        "UNREGISTERED",
        "SENDER_ID_MISMATCH",
        "QUOTA_EXCEEDED",
        "UNAVAILABLE",
        "INTERNAL",
        "THIRD_PARTY_AUTH_ERROR",
        "PERMISSION_DENIED",
        "NOT_FOUND",
    }
)


def config_value(body):
    """Converts the push settings form into stored config, validating the FCM service account."""
    value = body.model_dump()
    try:
        if value["apns"]:
            key = serialization.load_pem_private_key(
                value["apns"]["private_key"].encode(), password=None
            )
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
                key.curve, ec.SECP256R1
            ):
                raise ValueError()
        if value["fcm"]:
            conf = value["fcm"]
            if (
                not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", conf.get("project_id", ""))
                or conf.get("token_uri") != "https://oauth2.googleapis.com/token"
            ):
                raise ValueError()
            service_account.Credentials.from_service_account_info(
                conf, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
            )
    except (ValueError, TypeError, KeyError, GoogleAuthError) as error:
        raise HTTPException(
            422, "Check the APNs P-256 key or FCM service-account credentials"
        ) from error
    return value


def enable_relay_registration(directory):
    """Sets where this server stores relay tokens it registered for itself."""
    global _registration_dir
    _registration_dir = Path(directory) if directory else None
    _failed_registrations.clear()
    _failure_reasons.clear()


def _registrations():
    """Returns stored relay tokens by relay URL."""
    if _registration_dir is None:
        return {}
    try:
        value = json.loads((_registration_dir / REGISTRATIONS_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_registrations(value):
    """Writes the relay tokens file atomically."""
    fd, temporary = tempfile.mkstemp(prefix=".relay-", dir=_registration_dir)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
    os.chmod(temporary, 0o600)
    os.replace(temporary, _registration_dir / REGISTRATIONS_FILE)


def register_relay(url):
    """Returns this server's token for the relay at url, registering with the relay if needed."""
    if _registration_dir is None:
        return None
    with _registration_lock:
        entry = _registrations().get(url)
        if isinstance(entry, dict) and isinstance(entry.get("token"), str):
            return entry["token"]
        if time.time() - _failed_registrations.get(url, 0) < REGISTRATION_RETRY_SECONDS:
            return None
        token = None
        reason = "The relay could not be reached"
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.post(url[: -len("/v1/push")] + "/v1/register", json={})
            reason = f"The relay answered HTTP {response.status_code}"
            if response.status_code == 201:
                token = response.json().get("token")
                reason = "The relay sent an unexpected reply"
            else:
                error = response.json().get("error")
                if isinstance(error, str) and len(error) <= 100:
                    reason += ": " + error
        except (httpx.HTTPError, ValueError, AttributeError):
            token = None
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            _failed_registrations[url] = time.time()
            _failure_reasons[url] = reason
            return None
        _failure_reasons.pop(url, None)
        registrations = _registrations()
        registrations[url] = {"token": token, "registered_at": time.time()}
        _save_registrations(registrations)
        return token


def forget_relay_registration(url):
    """Deletes a stored relay token the relay rejected, so the next use registers again."""
    if _registration_dir is None:
        return
    with _registration_lock:
        registrations = _registrations()
        entry = registrations.get(url)
        if (
            isinstance(entry, dict)
            and time.time() - entry.get("registered_at", 0) > REGISTRATION_GRACE_SECONDS
        ):
            del registrations[url]
            _save_registrations(registrations)


def relay_status():
    """Returns each relay's address and whether this server is signed up with it. Never tokens."""
    stored = _registrations()
    status = []
    for label, url_name, token_name in RELAYS:
        url = image_defaults.setting(url_name)
        entry = stored.get(url) if url else None
        failed = _failed_registrations.get(url) if url else None
        status.append(
            {
                "name": label,
                "address": url or None,
                "built_in": bool(url) and not os.environ.get(url_name, "").strip(),
                "manual_token": bool(image_defaults.setting(token_name)),
                "registered": isinstance(entry, dict) and isinstance(entry.get("token"), str),
                "registered_at": entry.get("registered_at") if isinstance(entry, dict) else None,
                "last_error": _failure_reasons.get(url) if failed else None,
                "retry_in": (
                    max(0, int(REGISTRATION_RETRY_SECONDS - (time.time() - failed)))
                    if failed
                    else 0
                ),
            }
        )
    return status


def register_relays_now():
    """Signs up with any relay this server isn't registered with, skipping the retry wait."""
    for _, url_name, token_name in RELAYS:
        url = image_defaults.setting(url_name)
        if url:
            _failed_registrations.pop(url, None)
            try:
                _relay(url_name, token_name)
            except ValueError:
                pass
    return relay_status()


def _relay(url_name, token_name):
    """Returns a relay's URL and token if the URL is a plain HTTPS URL, otherwise None."""
    url = image_defaults.setting(url_name)
    if not url:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/push"
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Invalid " + url_name)
    token = image_defaults.setting(token_name)
    if token:
        return {"url": url, "token": token}
    token = register_relay(url)
    return {"url": url, "token": token, "registered": True} if token else None


def relay_settings():
    """Returns the APNs relay URL and token."""
    return _relay("NARAHEM_PUSH_RELAY_URL", "NARAHEM_PUSH_RELAY_TOKEN")


def fcm_relay_settings():
    """Returns the FCM relay URL and token."""
    return _relay("NARAHEM_FCM_RELAY_URL", "NARAHEM_FCM_RELAY_TOKEN")


def available_config(state, cipher):
    """Returns the push routes that are currently configured."""
    conf = json.loads(cipher.decrypt(state.push_config.encode())) if state.push_config else {}
    relay = relay_settings()
    if relay:
        conf["relay"] = relay
        if not conf.get("apns"):
            conf["apns"] = {"relay": True}
    fcm_relay = fcm_relay_settings()
    if fcm_relay:
        conf["fcm_relay"] = fcm_relay
        if not conf.get("fcm"):
            conf["fcm"] = {"relay": True}
    return conf


def parse_apns_registration(token, fallback):
    """Splits a stored APNs token into the token and its environment (sandbox or production)."""
    if token.startswith("sandbox:"):
        return token[len("sandbox:") :], "sandbox"
    if token.startswith("production:"):
        return token[len("production:") :], "production"
    return token, "sandbox" if fallback else "production"


class PushRelayFailure(OSError):
    """A relay rejection. Carries only known, non-secret fields so it can be logged for the
    admin.
    """

    KNOWN_STAGES = frozenset(
        {
            "signing_configuration",
            "signing_key_decode",
            "signing_key_import",
            "signing_jwt",
            "signing_unknown",
            "apns_transport",
            "apns_response",
        }
    )
    KNOWN_CODES = frozenset(
        {
            "TypeError",
            "DataError",
            "NotSupportedError",
            "OperationError",
            "InvalidAccessError",
            "SyntaxError",
            "Error",
            "NetworkError",
            "UnknownError",
        }
    )
    KNOWN_REASONS = frozenset(
        {
            "BadDeviceToken",
            "DeviceTokenNotForTopic",
            "BadTopic",
            "MissingTopic",
            "TopicDisallowed",
            "BadCertificateEnvironment",
            "InvalidProviderToken",
            "ExpiredProviderToken",
            "Forbidden",
            "Unregistered",
            "BadPriority",
            "BadPushType",
            "PayloadTooLarge",
            "TooManyRequests",
            "BadPath",
            "MethodNotAllowed",
            "BadMessageId",
            "InvalidPushType",
        }
    )

    def __init__(self, response_status, details):
        """Keeps only recognised fields from the relay's response."""
        super().__init__("APNs relay did not accept notification")
        details = details if isinstance(details, dict) else {}
        self.relay_status = (
            response_status
            if isinstance(response_status, int) and 100 <= response_status <= 599
            else None
        )
        stage = details.get("stage")
        self.stage = (
            stage if isinstance(stage, str) and stage in self.KNOWN_STAGES else "relay_response"
        )
        code = details.get("errorCode")
        self.error_code = code if isinstance(code, str) and code in self.KNOWN_CODES else None
        status = details.get("apnsStatus")
        self.apns_status = status if type(status) is int and 100 <= status <= 599 else None
        reason = details.get("reason")
        self.apns_reason = (
            reason
            if self.stage == "apns_response"
            and isinstance(reason, str)
            and reason in self.KNOWN_REASONS
            else None
        )


def relay_deliver(token, environment, record_id, expires_at, relay, kind="update"):
    """Sends an APNs push through the relay. Only the token and a fixed message type are sent; no
    IDs, places, names or coordinates.
    """
    lifetime = max(0, min(3600, int((expires_at or time.time() + 3600) - time.time())))
    payload = {
        "deviceToken": token,
        "environment": environment,
        "intent": kind if kind in ("find-phone", "alert") else "update",
        "expiresInSeconds": min(lifetime, 120) if kind == "find-phone" else lifetime,
    }
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        response = client.post(
            relay["url"],
            headers={
                "Authorization": "Bearer " + relay["token"],
                "Content-Type": "application/json",
            },
            json=payload,
        )
    # APNs returns 410 for an unregistered token; other errors are kept for retry.
    try:
        result = response.json()
    except (ValueError, TypeError):
        result = {}
    if response.status_code == 200 and result.get("acceptedByApns") is True:
        return "sent"
    if result.get("apnsStatus") == 410 and result.get("reason") == "Unregistered":
        return "invalid"
    if response.status_code == 401 and relay.get("registered"):
        forget_relay_registration(relay["url"])
    raise PushRelayFailure(response.status_code, result)


def fcm_relay_deliver(token, expires_at, relay, kind="update"):
    """Sends an FCM push through the relay. Only the token and a fixed intent are sent. "alert"
    is data-only: the app fetches alerts and Find My Phone commands from this server.
    """
    lifetime = max(0, min(3600, int((expires_at or time.time() + 3600) - time.time())))
    payload = {"deviceToken": token, "expiresInSeconds": lifetime}
    if kind in ("alert", "find-phone"):
        payload["intent"] = "alert"
    if kind == "find-phone":
        payload["expiresInSeconds"] = min(lifetime, 120)
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        response = client.post(
            relay["url"],
            headers={
                "Authorization": "Bearer " + relay["token"],
                "Content-Type": "application/json",
            },
            json=payload,
        )
    try:
        result = response.json()
    except (ValueError, TypeError):
        result = {}
    if response.status_code == 200 and result.get("acceptedByFcm") is True:
        return "sent"
    # INVALID_ARGUMENT can mean a bad request or configuration, not a dead token, so the token is
    # kept.
    if result.get("reason") == "UNREGISTERED" and result.get("fcmStatus") == 404:
        return "invalid"
    if response.status_code == 401 and relay.get("registered"):
        forget_relay_registration(relay["url"])
    error = OSError("FCM relay rejected delivery")
    error.relay_status = response.status_code
    reason = result.get("reason")
    error.provider_reason = reason if reason in FCM_REASONS else None
    raise error


def deliver(provider, token, record_id, delivery_id, config, expires_at=None, kind="update"):
    """Sends one push through the configured route. The find-phone type is only used for a signed
    Find My Phone command.
    """
    if kind not in ("update", "find-phone", "alert"):
        raise ValueError("Unsupported push category")
    expires_at = expires_at or time.time() + 3600
    if provider == "apns":
        c = config["apns"]
        token, environment = parse_apns_registration(token, c.get("sandbox", False))
        if config.get("relay"):
            return relay_deliver(
                token, environment, record_id, expires_at, config["relay"], kind=kind
            )
        jwt_token = jwt.encode(
            {"iss": c["team_id"], "iat": int(time.time())},
            c["private_key"],
            algorithm="ES256",
            headers={"kid": c["key_id"]},
        )
        host = (
            "https://api.sandbox.push.apple.com"
            if environment == "sandbox"
            else "https://api.push.apple.com"
        )
        aps = {
            "alert": {"title": "Nära Hem", "body": "A household update is available."},
            "sound": "default",
        }
        if kind == "alert":
            # Placeholder text: the iOS notification extension replaces it with the alert fetched
            # from this server.
            aps = {
                "alert": {"title": "Nära Hem", "body": "Household alert"},
                "sound": "default",
                "mutable-content": 1,
            }
        if kind == "find-phone":
            # Time Sensitive can break through Focus if the user allows it, but not Silent Mode.
            aps = {
                "alert": {
                    "title": "Find My Phone",
                    "body": "An approved household administrator requested a phone-finding alert.",
                },
                "sound": "narahem-find-phone-v1.wav",
                "interruption-level": "time-sensitive",
                "category": "narahem-find-phone",
            }
        with httpx.Client(http2=True, timeout=10, follow_redirects=False) as client:
            response = client.post(
                f"{host}/3/device/{token}",
                headers={
                    "authorization": f"bearer {jwt_token}",
                    "apns-topic": c["topic"],
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                    "apns-expiration": str(int(expires_at)),
                    "apns-id": str(uuid.UUID(delivery_id)),
                },
                json={"aps": aps, "record_id": record_id if kind == "update" else "0" * 32},
            )
        if response.status_code == 410:
            return "invalid"
        if response.status_code not in (200,):
            raise OSError("Push provider rejected delivery")
    else:
        if config.get("fcm_relay"):
            return fcm_relay_deliver(token, expires_at, config["fcm_relay"], kind=kind)
        c = config["fcm"]
        credentials = service_account.Credentials.from_service_account_info(
            c, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        request = GoogleRequest()

        def bounded_request(*args, **kwargs):
            """Google auth transport request with a timeout."""
            kwargs["timeout"] = 10
            return request(*args, **kwargs)

        credentials.refresh(bounded_request)
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            longest = 120 if kind == "find-phone" else 3600
            ttl = f"{max(0, min(longest, int(expires_at - time.time())))}s"
            message = {
                "token": token,
                "notification": {"title": "Nära Hem", "body": "A household update is available."},
                "data": {"record_id": record_id},
                "android": {"ttl": ttl},
            }
            if kind in ("alert", "find-phone"):
                message = {
                    "token": token,
                    "data": {"intent": "alert"},
                    "android": {"ttl": ttl, "priority": "HIGH"},
                }
            response = client.post(
                f"https://fcm.googleapis.com/v1/projects/{c['project_id']}/messages:send",
                headers={"authorization": f"Bearer {credentials.token}"},
                json={"message": message},
            )
        if response.status_code != 200:
            try:
                invalid = any(
                    x.get("errorCode") == "UNREGISTERED"
                    for x in response.json().get("error", {}).get("details", [])
                )
            except (ValueError, TypeError, AttributeError):
                invalid = False
            if invalid:
                return "invalid"
            raise OSError("Push provider rejected delivery")
    return "sent"


def send_queued(db, cipher, notifier=None):
    """Sends queued alert pushes and deletes tokens the provider reports as unregistered."""
    state = db.get(ServiceState, 1)
    config = available_config(state, cipher)
    if not config.get("apns") and not config.get("fcm"):
        return
    rows = list(
        db.scalars(
            select(PushDelivery)
            .where(PushDelivery.retry_at <= time.time())
            .order_by(PushDelivery.created)
            .limit(4)
            .with_for_update(skip_locked=True)
        )
    )
    for item in rows:
        sub, device = db.get(PushSubscription, item.device_id), db.get(ClientDevice, item.device_id)
        account = db.get(Account, device.account_id) if device else None
        if (
            item.expires_at <= time.time()
            or not sub
            or not device
            or device.status != "approved"
            or not account
            or account.status != "active"
        ):
            diagnostic(
                db,
                "notification",
                "push.result",
                device.account_id if device else None,
                item.device_id,
                "expired" if item.expires_at <= time.time() else "invalid",
                record_id=item.record_id,
                source="server",
                reason="Expired or recipient unavailable",
            )
            db.delete(item)
            continue
        if not config.get(sub.provider):
            continue
        try:
            status = (notifier or deliver)(
                sub.provider,
                cipher.decrypt(sub.token.encode()).decode(),
                item.record_id,
                item.id,
                config,
                item.expires_at,
                kind="alert",
            )
        except (OSError, httpx.HTTPError, GoogleAuthError, jwt.PyJWTError, ValueError, TypeError):
            diagnostic(
                db,
                "notification",
                "push.result",
                device.account_id,
                device.id,
                "failed",
                record_id=item.record_id,
                provider=sub.provider,
                attempt=item.attempts + 1,
                reason="Provider request failed; scheduled retry",
                source="server",
            )
            item.attempts += 1
            item.retry_at = time.time() + min(300, 2 ** min(item.attempts, 8))
            continue
        diagnostic(
            db,
            "notification",
            "push.result",
            device.account_id,
            device.id,
            "invalid" if status == "invalid" else "accepted",
            record_id=item.record_id,
            provider=sub.provider,
            source="server",
            confirmed_delivery=False,
        )
        if status == "invalid":
            db.delete(sub)
        db.delete(item)
    db.commit()


def install_push(app, cipher, database, admin, rate, notifier=None, directory=None):
    """Registers the admin push settings and test routes."""
    enable_relay_registration(directory)

    @app.get("/api/push/config")
    def get_config(auth=Depends(admin), db=Depends(database)):
        """Returns the push settings without secrets."""
        state = db.get(ServiceState, 1)
        conf = json.loads(cipher.decrypt(state.push_config.encode())) if state.push_config else {}
        return {
            "apns": {
                key: value for key, value in conf.get("apns", {}).items() if key != "private_key"
            }
            if conf.get("apns")
            else None,
            "fcm_project": (conf.get("fcm") or {}).get("project_id"),
            "cloudflare_relay_configured": relay_settings() is not None,
            "cloudflare_fcm_relay_configured": fcm_relay_settings() is not None,
        }

    @app.put("/api/push/config")
    def save_config(body: PushConfig, auth=Depends(admin), db=Depends(database)):
        """Saves the push settings, encrypted."""
        conf = config_value(body)
        db.get(ServiceState, 1).push_config = cipher.encrypt(json.dumps(conf).encode()).decode()
        audit(db, "push.configured", auth[0].id)
        db.commit()
        return {"saved": True}

    def eligible_devices(db):
        """Returns approved devices on active accounts, the only valid test push targets."""
        return list(
            db.scalars(
                select(ClientDevice)
                .join(Account, Account.id == ClientDevice.account_id)
                .where(ClientDevice.status == "approved", Account.status == "active")
                .order_by(ClientDevice.created)
            )
        )

    @app.get("/api/push/relays")
    def relays(auth=Depends(admin)):
        """Returns each push relay's address and whether this server is signed up with it."""
        return {"relays": relay_status()}

    @app.post("/api/push/relays/register")
    def register_relays(request: Request, auth=Depends(admin)):
        """Signs up with the push relays now instead of waiting. Rate limited."""
        rate(request, "relay-register", 10)
        return {"relays": register_relays_now()}

    @app.get("/api/push/status")
    def push_status(auth=Depends(admin), db=Depends(database)):
        """Returns which devices have push registered. Metadata only, never tokens or keys."""
        return {
            "devices": [
                {
                    "id": device.id,
                    "name": device.name,
                    "account_id": device.account_id,
                    "provider": sub.provider if sub else None,
                    "registered": sub is not None,
                }
                for device in eligible_devices(db)
                for sub in [db.get(PushSubscription, device.id)]
            ]
        }

    @app.post("/api/push/test")
    def test_push(body: PushTestInput, request: Request, auth=Depends(admin), db=Depends(database)):
        """Sends a test push to one device or the admin's own devices. Rate limited."""
        sent = 0
        rate(request, "push-test", 10)
        state = db.get(ServiceState, 1)
        config = available_config(state, cipher)
        if not config.get("apns") and not config.get("fcm"):
            raise HTTPException(409, "Configure push first")
        eligible = eligible_devices(db)
        if body.device_id is not None:
            devices = [device for device in eligible if device.id == body.device_id]
            if not devices:
                raise HTTPException(404, "Approved household device not found")
        else:
            devices = [device for device in eligible if device.account_id == auth[0].id]
        try:
            for device in devices:
                sub = db.get(PushSubscription, device.id)
                if sub and config.get(sub.provider):
                    result = (notifier or deliver)(
                        sub.provider,
                        cipher.decrypt(sub.token.encode()).decode(),
                        "0" * 32,
                        uuid.uuid4().hex,
                        config,
                    )
                    # Only count tokens the provider accepted; acceptance still doesn't prove the
                    # phone received it.
                    if result == "sent":
                        sent += 1
                    else:
                        diagnostic(
                            db,
                            "notification",
                            "push.test",
                            device.account_id,
                            device.id,
                            "invalid" if result == "invalid" else "failed",
                            provider=sub.provider,
                            source="server",
                            confirmed_delivery=False,
                            reason="Provider did not accept diagnostic notification",
                        )
                        db.commit()
        except (
            OSError,
            httpx.HTTPError,
            GoogleAuthError,
            jwt.PyJWTError,
            ValueError,
            TypeError,
        ) as error:
            # 424, not 5xx: Cloudflare replaces 5xx responses with its own error page.
            status = getattr(error, "relay_status", None)
            provider = getattr(error, "apns_reason", None) or getattr(
                error, "provider_reason", None
            )
            reason = (
                "the push relay does not recognise this server"
                if status == 401
                else f"the push relay answered HTTP {status}"
                if status
                else "check provider credentials and device registration"
            )
            if provider:
                platform = "Apple" if getattr(error, "apns_reason", None) else "Firebase"
                reason += f" ({platform}: {provider})"
            raise HTTPException(424, "Push test failed: " + reason) from error
        return {"sent": sent}
