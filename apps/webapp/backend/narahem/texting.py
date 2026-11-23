"""Text messages through Textbelt: phone numbers, key checks and sending.

The household administrator turns texting on with a Textbelt key, either in Admin settings or
with the NARAHEM_TEXTBELT_KEY environment variable, which wins. Until a key is checked and has
credit, Nära Hem uses email only.
"""

import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

ENVIRONMENT_KEY = "NARAHEM_TEXTBELT_KEY"
TEXTBELT = "https://textbelt.com"
# Where the apps will be downloaded once they are in the stores.
STORE_DOMAINS = ("apps.apple.com", "play.google.com")


class TextingError(Exception):
    """A text could not be sent or the key could not be checked. The message is safe to show;
    reason is Textbelt's own words, if it gave any.
    """

    def __init__(self, message, reason=None):
        """Keeps Textbelt's reason beside the message shown."""
        super().__init__(message)
        self.reason = reason


def phone_number(value):
    """Returns the number in E.164 form (+14155550123). Ten digits are taken as US or Canada."""
    digits = re.sub(r"[\s().-]", "", value.strip())
    if re.fullmatch(r"[0-9]{10}", digits):
        digits = "+1" + digits
    elif re.fullmatch(r"1[0-9]{10}", digits):
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", digits):
        raise HTTPException(422, "Enter a phone number with its country code, e.g. +14155550123")
    return digits


def invitation(household, public_url):
    """Returns the invitation text. Textbelt only sends links from domains it has approved, so
    it names the server's address rather than linking to it, and the app texts a code instead.
    """
    name = household.strip() or "a Nära Hem"
    if not name.lower().endswith("family"):
        name += " family"
    return (
        f"You have been invited to {name} locator.\n"
        "Please download Nära Hem (Nara Hem) off your devices official store.\n"
        f"Create your account using {urlsplit(public_url).netloc} and your phone number."
    )


def code_message(code):
    """Returns the text that carries a six-digit code."""
    return f"Your Nära Hem verification code:\n{code}"


def looks_like_phone(value):
    """Returns True if the value is meant as a phone number rather than an email address."""
    return "@" not in value and bool(re.fullmatch(r"[\s()+0-9.-]{7,24}", value.strip()))


def environment_key():
    """Returns the key from the environment, or None."""
    return os.environ.get(ENVIRONMENT_KEY, "").strip() or None


def hint(key):
    """Returns a masked key that shows only its last four characters."""
    return "•" * 8 + key[-4:] if len(key) > 8 else "•" * 8


def link_domains(public_url, links=()):
    """Returns the domains this server's texts link to, for Textbelt's whitelist: the server's
    own address, the app download links in invitations and the app stores.
    """
    domains = []
    for url in (public_url, *links):
        host = urlsplit(url or "").hostname
        if host and host not in domains:
            domains.append(host)
    return domains + [d for d in STORE_DOMAINS if d not in domains]


def describe(error, domains=()):
    """Turns a Textbelt error into advice for the administrator, naming the domains to whitelist
    when links were refused.
    """
    text = str(error or "").strip() or "Textbelt did not say why"
    if re.search(r"url|link", text, re.IGNORECASE):
        listing = ", ".join(domains) or "your server's address and the app download sites"
        return (
            text + " Textbelt only sends links once your key is approved for them: request it at "
            f"textbelt.com/whitelist, listing {listing}."
        )
    return text


class Textbelt:
    """Talks to the Textbelt API."""

    def __init__(self, base=TEXTBELT, timeout=15):
        """Uses the Textbelt API at base."""
        self.base, self.timeout = base.rstrip("/"), timeout

    def quota(self, key):
        """Returns how many texts the key has left. Checking costs nothing."""
        try:
            response = httpx.get(f"{self.base}/quota/{key}", timeout=self.timeout)
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TextingError("Textbelt could not be reached") from error
        if not data.get("success"):
            raise TextingError(describe(data.get("error")), data.get("error"))
        return int(data.get("quotaRemaining", 0))

    def send(self, key, phone, message):
        """Sends one text and returns the texts left on the key."""
        try:
            response = httpx.post(
                f"{self.base}/text",
                data={"phone": phone, "message": message, "key": key},
                timeout=self.timeout,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TextingError("Textbelt could not be reached") from error
        if not data.get("success"):
            raise TextingError(describe(data.get("error")), data.get("error"))
        return int(data.get("quotaRemaining", 0))
