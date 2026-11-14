"""App Store review mode, for a separate demo server only.

Apple's reviewers sign in to a demo account and cannot receive the six-digit phone code by email
or text. With NARAHEM_REVIEW_CODE set, the listed accounts get that fixed code instead: nothing
is sent, and the code is checked like any other (bound to the phone, ten minutes, five tries).

NARAHEM_REVIEW_ACCOUNTS lists email addresses, comma separated. An entry that starts with @
covers a whole domain, e.g. @demo.example.com. Never set either on a real household's server.
"""

import os
import re

ACCOUNTS = "NARAHEM_REVIEW_ACCOUNTS"
CODE = "NARAHEM_REVIEW_CODE"


def code():
    """Returns the fixed code if one is set and it is six digits, otherwise None."""
    value = os.environ.get(CODE, "").strip()
    return value if re.fullmatch(r"[0-9]{6}", value) else None


def accounts():
    """Returns the listed addresses and @domains in lower case."""
    return {e.strip().lower() for e in os.environ.get(ACCOUNTS, "").split(",") if e.strip()}


def enabled():
    """Returns True if review mode is on: a valid code and at least one account."""
    return bool(code() and accounts())


def fixed_code(account):
    """Returns the fixed code for a listed account, or None for everyone else."""
    email = (account.email or "").lower()
    listed = accounts()
    if not email or not enabled():
        return None
    if email in listed or "@" + email.rsplit("@", 1)[1] in listed:
        return code()
    return None


def check():
    """Raises if review mode is half set up, and returns the startup warning when it is on."""
    if os.environ.get(CODE, "").strip() and not code():
        raise ValueError("NARAHEM_REVIEW_CODE must be exactly six digits")
    if not enabled():
        return None
    return (
        "NARAHEM REVIEW MODE IS ON: phones of "
        + ", ".join(sorted(accounts()))
        + " are approved with a fixed code and nothing is sent. Use this only on a demo server."
    )
