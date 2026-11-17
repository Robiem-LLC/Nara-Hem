"""Alexa: "Alexa, ask Close to Home to let me know when Maya gets home" (or "leaves school").

The first time, Alexa asks out loud whether the skill may set reminders; one spoken "yes" is the
household's consent, and nothing has to be done in the Alexa app. The server then keeps a
one-day watch. When Maya's phone is next inside the place (or clearly away from it, for a
departure), the server asks the Nära Hem Alexa
relay to wake the skill for that Alexa user (Amazon's Skill Messaging), and in that wake-up the
server sets a reminder a few seconds ahead, which the Echo chimes and speaks: "From Nara Hem:
Maya has arrived home." Amazon hears that sentence; nothing else about the household.

This module holds the pieces that talk to Amazon and the relay; alexa_api.py decides when.
"""

import datetime

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
RETRY_SECONDS = 60
# The reminder rings this many seconds after it is set.
REMINDER_DELAY = 10


def system(alexa):
    """Returns the context.System part of an Alexa request."""
    return (alexa.get("context") or {}).get("System") or {}


def granted(alexa):
    """Returns True if the user has let the skill set reminders."""
    scopes = ((system(alexa).get("user") or {}).get("permissions") or {}).get("scopes") or {}
    return (scopes.get(REMINDERS) or {}).get("status") == "GRANTED"


def reminders_accepted(payload):

def reminders_accepted(payload):
    """Check whether Alexa accepted reminders permission."""
    scopes = payload.get("permissionScopes")

    if isinstance(scopes, dict):
        scopes = [scopes]

    if isinstance(scopes, list):
        matching = [
            scope
            for scope in scopes
            if isinstance(scope, dict)
            and scope.get("permissionScope") == REMINDERS
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
    """Returns True for the place called Home, which reads without "at" or "to"."""
    return place.strip().lower() == "home"


def promise(name, place, event):
    """Returns what Alexa says when a watch starts: "...when Maya gets home"."""
    if event == "leave":
        return f"Okay, I'll let you know when {name} leaves {'home' if is_home(place) else place}."
    return (
        f"Okay, I'll let you know when {name} gets {'home' if is_home(place) else 'to ' + place}."
    )


def announcement(name, place, event):
    """Returns what the Echo says when it happens: "From Nara Hem: Maya has arrived home"."""
    if event == "leave":
        return f"From Nara Hem: {name} has left {'home' if is_home(place) else place}."
    return f"From Nara Hem: {name} has arrived {'home' if is_home(place) else 'at ' + place}."


def reminder(text, locale):
    """Returns a Reminders API body for a reminder a few seconds from now."""
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    return {
        "requestTime": now.strftime("%Y-%m-%dT%H:%M:%S.000"),
        "trigger": {"type": "SCHEDULED_RELATIVE", "offsetInSeconds": REMINDER_DELAY},
        "alertInfo": {"spokenInfo": {"content": [{"locale": locale, "text": text}]}},
        "pushNotification": {"status": "ENABLED"},
    }


def set_reminder(alexa, text):
    """Sets the reminder with the wake-up request's own token. Returns True if Amazon took it."""
    address, token = endpoint(alexa), system(alexa).get("apiAccessToken")
    if not address or not token:
        return False
    locale = (alexa.get("request") or {}).get("locale") or "en-US"
    try:
        reply = httpx.post(
            address + "/v1/alerts/reminders",
            json=reminder(text, locale),
            headers={"Authorization": "Bearer " + token},
            timeout=5,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return False
    return reply.status_code in (200, 201)


def wake(relay, watch):
    """Asks the relay to wake the skill for the Alexa user who asked. Returns True if it took
    the request.
    """
    try:
        reply = httpx.post(
            relay + "/v1/notify",
            json={"user": watch.alexa_user, "endpoint": watch.api_endpoint, "watch": watch.id},
            timeout=10,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return False
    return reply.status_code == 202
