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


def invitation(household, public_url, links=False):
    """Returns the invitation text. It names the server's address (its NARAHEM_PUBLIC_URL
    without https://), where the person registers in the app: plainly once Textbelt has
    whitelisted the domain (links), otherwise with its dots written as <.>.
    """
    name = household.strip() or "a Nära Hem"
    if not name.lower().endswith("family"):
        name += " family"
    return (
        f"You have been invited to {name} locator.\n"
        "Please download Nära Hem (Nara Hem) off your devices official store.\n"
        f"Create your account using {texted_address(public_url, links)} and your phone number."
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


def texted_address(public_url, links=False):
    """Returns the server's address as texts write it: plainly once Textbelt has whitelisted the
    domain, otherwise with <.> for each dot.
    """
    return urlsplit(public_url).netloc if links else spoken_address(public_url)


def spoken_address(public_url):
    """Returns the server's address with each dot written as <.>, such as
    nara-hem<.>example<.>com. Textbelt refuses anything that looks like a link, a bare address
    included, and the apps turn <.> back into a dot.
    """
    return urlsplit(public_url).netloc.replace(".", "<.>")


def scrub(text, key=None):
    """Removes the key, and any link's query string where Textbelt puts it, from its words. Keys
    too short to be real are left alone, so ordinary words aren't masked.
    """
    text = re.sub(r"(https?://\S+?)\?\S*", r"\1", str(text or ""))
    return text.replace(key, "•" * 8) if key and len(key) >= 8 else text


def describe(error):
    """Turns a Textbelt error into advice for the administrator."""
    text = str(error or "").strip() or "Textbelt did not say why"
    if re.search(r"url|link", text, re.IGNORECASE):
        return (
            text + " Nära Hem's texts carry no links, so Textbelt took something in the text for "
            "one. Ask Textbelt at support@textbelt.com which part."
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
            reason = scrub(data.get("error"), key)
            raise TextingError(describe(reason), reason)
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
            reason = scrub(data.get("error"), key)
            raise TextingError(describe(reason), reason)
        return int(data.get("quotaRemaining", 0))
