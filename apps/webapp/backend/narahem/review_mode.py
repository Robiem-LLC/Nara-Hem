"""App Store review mode, for a separate demo server only.

Apple's reviewers sign in to a demo account and cannot receive the six-digit phone code by email
or text. With NARAHEM_REVIEW_CODE set, the listed accounts get that fixed code instead: nothing
is sent, and the code is checked like any other (bound to the phone, ten minutes, five tries).

NARAHEM_REVIEW_ACCOUNTS lists email addresses, comma separated. An entry that starts with @
covers a whole domain, e.g. @demo.example.com. Never set either on a real household's server.

NARAHEM_DEMO_OPEN_SIGNUP=true also lets anyone register in the app without an invitation, such as
store reviewers and closed testers. It only works in review mode. Those testers' phones are
approved at once, their locations are shared with nobody, they don't appear in other members'
lists, and their accounts are deleted after 30 days unused.
"""

import os
import re

ACCOUNTS = "NARAHEM_REVIEW_ACCOUNTS"
CODE = "NARAHEM_REVIEW_CODE"
OPEN_SIGNUP = "NARAHEM_DEMO_OPEN_SIGNUP"
# A tester's account is deleted after this long with no sign-in or location.
TESTER_IDLE_SECONDS = 30 * 86400


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


def listed(account):
    """Returns True if the account is on the review list: a reviewer or the demo family."""
    email = (account.email or "").lower()
    names = accounts()
    return bool(email) and (email in names or "@" + email.rsplit("@", 1)[1] in names)


def open_signup():
    """Returns True if anyone may register without an invitation: review mode is on and
    NARAHEM_DEMO_OPEN_SIGNUP is set.
    """
    switched = os.environ.get(OPEN_SIGNUP, "").strip().lower() in ("1", "true", "yes")
    return switched and enabled()


def is_tester(account):
    """Returns True for an account that registered itself on an open demo server: not the
    administrator and not on the review list.
    """
    return bool(account and open_signup() and account.role != "admin" and not listed(account))


def check():
    """Raises if review mode is half set up, and returns the startup warning when it is on."""
    if os.environ.get(CODE, "").strip() and not code():
        raise ValueError("NARAHEM_REVIEW_CODE must be exactly six digits")
    if not enabled():
        if os.environ.get(OPEN_SIGNUP, "").strip():
            raise ValueError("NARAHEM_DEMO_OPEN_SIGNUP needs review mode: set the review code")
        return None
    return (
        "NARAHEM REVIEW MODE IS ON: phones of "
        + ", ".join(sorted(accounts()))
        + " are approved with a fixed code and nothing is sent. Use this only on a demo server."
        + (
            " OPEN SIGN-UP IS ON: anyone can register; their phones are approved at once and"
            " shared with nobody."
            if open_signup()
            else ""
        )
    )
