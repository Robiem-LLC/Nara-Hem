"""Writes the settings built into an official image, from CI secrets.

The push and Alexa relay addresses, the store Alexa skill's ID and the app download links, so a
server works without setting them (apps/webapp/backend/narahem/image_defaults.py). Only valid
values are written to the given file (mode 0600). Relay tokens are never written: images may be
public, so each server supplies its own token. Prints a summary that names what is configured,
never values.
"""

import json
import os
import re
import sys
from urllib.parse import urlsplit


def https_url(url, path=None):
    """Returns True for an HTTPS URL without credentials, port, query or fragment, and with the
    given path if one is required.
    """
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and parts.port in (None, 443)
        and (path is None or parts.path in path)
    )


DEFAULTS = {
    "NARAHEM_PUSH_RELAY_URL": (
        "iPhone (APNs) push relay address",
        lambda v: https_url(v, ("/v1/push",)),
    ),
    "NARAHEM_FCM_RELAY_URL": (
        "Android (FCM) push relay address",
        lambda v: https_url(v, ("/v1/push",)),
    ),
    "NARAHEM_ALEXA_RELAY_URL": ("Alexa relay address", lambda v: https_url(v, ("", "/"))),
    "NARAHEM_ALEXA_STORE_SKILL_ID": (
        "Alexa store skill ID",
        lambda v: re.fullmatch(r"amzn1\.ask\.skill\.[0-9a-f-]{36}", v) is not None,
    ),
    "NARAHEM_IOS_APP_URL": ("iPhone app link", https_url),
    "NARAHEM_ANDROID_APP_URL": ("Android app link", https_url),
}


def build(environ):
    """Returns the settings to build into the image, read from the CI environment."""
    defaults, summary = {}, []
    for name, (label, valid) in DEFAULTS.items():
        value = environ.get(name, "").strip()
        if value and valid(value):
            defaults[name] = value
            summary.append(f"- {label}: built in")
        elif value:
            summary.append(f"- {label}: **not built in** (invalid secret)")
        else:
            summary.append(f"- {label}: not configured")
    return defaults, summary


def main(path):
    """Writes the defaults file with owner-only permissions and prints a summary."""
    defaults, summary = build(os.environ)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        if defaults:
            json.dump(defaults, output)
    print("Built into this image (servers supply their own relay tokens):")
    print("\n".join(summary))


if __name__ == "__main__":
    main(sys.argv[1])
