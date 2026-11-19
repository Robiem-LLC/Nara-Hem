"""Create, update and cancel Alexa reminders for one-time location watches.

A reminder is created with consent during a voice session. The relay wakes
this skill to update or delete it later. Only the reminder ID is persisted.
"""
import datetime
from urllib.parse import quote

import httpx

# The permission Alexa asks for by voice, and the one the wake-up's token then carries.
REMINDERS = "alexa::alerts:reminders:skill:readwrite"
# Amazon's Alexa API hosts for North America, Europe and the Far East.
API_HOSTS = (
    "https://api.amazonalexa.com",
    "https://api.eu.amazonalexa.com",
    "https://api.fe.amazonalexa.com",
)
# A watch lasts a day, and each Alexa link may keep a handful at once.
WATCH_SECONDS = 86400
MAX_WATCHES = 10
# After an arrival, the relay is asked again for this long if the wake-up doesn't come back.
NOTICE_SECONDS = 600
# The reminder rings this many seconds after it is set.
REMINDER_DELAY = 10
CLEANUP_SECONDS = 600
MAX_ATTEMPTS = 6
PLACEHOLDER = "Your Nara Hem location alert expired."
DELIVERY = {
    "arrive": "Your Nara Hem arrival alert is ready. Check Nara Hem for details.",
    "leave": "Your Nara Hem departure alert is ready. Check Nara Hem for details.",
}


def system(alexa):
    """Returns the context.System part of an Alexa request."""
    return (alexa.get("context") or {}).get("System") or {}


def granted(alexa):
    """Check whether Alexa has granted reminders access."""
    sys = system(alexa)
    user = sys.get("user") or {}
    permissions = user.get("permissions") or {}
    scopes = permissions.get("scopes") or {}
    status = (scopes.get(REMINDERS) or {}).get("status")
    if status == "GRANTED":
        return True
    if not permissions.get("consentToken"):
        return False
    api = endpoint(alexa)
    token = sys.get("apiAccessToken")
    if not api or not token:
        return None
    try:
        response = httpx.get(
            api + "/v1/alerts/reminders",
            headers={"Authorization": "Bearer " + token},
            timeout=2,
        )
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code in (401, 403):
        return False
    return None


def reminders_accepted(payload):
    """Check whether Alexa accepted reminders permission."""
    scopes = payload.get("permissionScopes")
    if isinstance(scopes, dict):
        scopes = [scopes]
    if isinstance(scopes, list):
        matching = [
            scope
            for scope in scopes
            if isinstance(scope, dict) and scope.get("permissionScope") == REMINDERS
        ]
        if not matching:
            return False
        if any(scope.get("status") == "ACCEPTED" for scope in matching):
            return True
        if any(
            scope.get("status") in ("DENIED", "NOT_ANSWERED", "REDIRECT_TO_APP")
            for scope in matching
        ):
            return False
        return payload.get("status") == "ACCEPTED"
    return (
        payload.get("permissionScope") == REMINDERS
        and payload.get("status") == "ACCEPTED"
    )


def endpoint(alexa):
    """Returns the request's Alexa API address if it is one of Amazon's, else None."""
    value = system(alexa).get("apiEndpoint")
    return value if value in API_HOSTS else None


def ask_permission(token):
    """Returns the response that has Alexa ask, by voice, for permission to set reminders. Alexa
    answers with a Connections.Response request carrying the token back.
    """
    request = {
        "@type": "AskForPermissionsConsentRequest",
        "@version": "2",
        "permissionScopes": [{"permissionScope": REMINDERS, "consentLevel": "ACCOUNT"}],
    }
    directive = {"type": "Connections.SendRequest", "name": "AskFor", "payload": request}
    return {
        "version": "1.0",
        "response": {"directives": [dict(directive, token=token)], "shouldEndSession": True},
    }


def is_home(place):
    """Returns True for the place called Home, which reads without \"at\" or \"to\"."""
    return place.strip().lower() == "home"


def promise(name, place, event):
    """Returns what Alexa says when a watch starts: \"...when Maya gets home\"."""
    if event == "leave":
        return f"Okay, I'll let you know when {name} leaves {'home' if is_home(place) else place}."
    return (
        f"Okay, I'll let you know when {name} gets {'home' if is_home(place) else 'to ' + place}."
    )


def announcement(name, place, event):
    """Returns what the Echo says when it happens: \"From Nara Hem: Maya has arrived home\"."""
    if event == "leave":
        return f"From Nara Hem: {name} has left {'home' if is_home(place) else place}."
    return f"From Nara Hem: {name} has arrived {'home' if is_home(place) else 'at ' + place}."


def reminder(text, locale, delay=REMINDER_DELAY):
    """Returns a Reminders API body for a reminder a few seconds from now."""
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    return {
        "requestTime": now.strftime("%Y-%m-%dT%H:%M:%S.000"),
        "trigger": {"type": "SCHEDULED_RELATIVE", "offsetInSeconds": delay},
        "alertInfo": {"spokenInfo": {"content": [{"locale": locale, "text": text}]}},
        "pushNotification": {"status": "DISABLED"},
    }


def reminder_request(alexa, method, alert_token=None, body=None):
    """Call Amazon and classify the result without logging credentials or reminder text."""
    address, token = endpoint(alexa), system(alexa).get("apiAccessToken")
    if not address or not token:
        return "retry", None
    url = address + "/v1/alerts/reminders"
    if alert_token:
        url += "/" + quote(alert_token, safe="")
    options = {"json": body} if body is not None else {}
    try:
        reply = httpx.request(
            method,
            url,
            headers={"Authorization": "Bearer " + token},
            timeout=2.5,
            follow_redirects=False,
            **options,
        )
    except httpx.HTTPError:
        print(f"Alexa reminder {method}: network error", flush=True)
        return "retry", None
    try:
        data = reply.json()
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    status = reply.status_code
    if status in (200, 201, 204):
        print(f"Alexa reminder {method}: HTTP {status}", flush=True)
        return "ok", data
    code = data.get("code", "UNKNOWN")
    if not isinstance(code, str) or len(code) > 80 or not code.replace("_", "").isalnum():
        code = "UNKNOWN"
    # Do not log untrusted response bodies or identifiers.
    print(f"Alexa reminder {method}: HTTP {status}, code={code}", flush=True)
    if status == 404:
        return "gone", None
    if status in (408, 409, 429) or status >= 500 or code == "EXPIRED_BEARER_TOKEN":
        return "retry", None
    return "failed", None


def create_reminder(alexa):
    """Create the disclosed expiry reminder while the user is in-session."""
    locale = (alexa.get("request") or {}).get("locale") or "en-US"
    result, data = reminder_request(
        alexa, "POST", body=reminder(PLACEHOLDER, locale, WATCH_SECONDS + CLEANUP_SECONDS)
    )
    token = data.get("alertToken") if result == "ok" else None
    return token if isinstance(token, str) and token else None


def finish_reminder(alexa, alert_token, event, cancel=False, label=None):
    """Update or delete an active placeholder; reconcile retries with Amazon first."""
    result, data = reminder_request(alexa, "GET", alert_token)
    if result != "ok":
        return result
    contents = ((data.get("alertInfo") or {}).get("spokenInfo") or {}).get("content") or []
    current = contents[0] if contents and isinstance(contents[0], dict) else {}
    text = current.get("text")
    # A user may have deleted or edited the reminder, or a previous PUT may have
    # succeeded even when its response timed out. Never repurpose such a reminder.
    if data.get("status") != "ON" or text != PLACEHOLDER:
        return "gone"
    if cancel:
        return reminder_request(alexa, "DELETE", alert_token)[0]
    locale = current.get("locale") or (alexa.get("request") or {}).get("locale") or "en-US"
    return reminder_request(
        alexa, "PUT", alert_token, reminder(label or DELIVERY[event], locale, REMINDER_DELAY)
    )[0]


def retry_delay(attempts):
    """Bound exponential backoff, including failed relay requests."""
    return min(120, 10 * 2 ** min(max(attempts - 1, 0), 4))


def wake(relay, watch):
    """Classify the relay result without exposing user identifiers."""
    try:
        reply = httpx.post(
            relay + "/v1/notify",
            json={"user": watch.alexa_user, "endpoint": watch.api_endpoint, "watch": watch.id},
            timeout=10,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return "retry"
    if reply.status_code == 202:
        return "ok"
    if reply.status_code in (408, 409, 429) or reply.status_code >= 500:
        return "retry"
    print(f"Alexa relay rejected wake-up: HTTP {reply.status_code}", flush=True)
    return "failed"
