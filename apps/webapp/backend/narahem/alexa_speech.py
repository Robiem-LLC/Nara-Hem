"""What Alexa says: matching a spoken name to a household member and describing where they are.

Kept free of the database and the web so it can be tested on its own.
"""

import difflib
import re
import unicodedata
from datetime import datetime, timedelta

CLOSE_ENOUGH = 0.6
DRIVING_SPEED = 3.0  # metres per second
FRESH_MINUTES = 30
MOVING_MINUTES = 10


def normal(text):
    """Returns a name in lower case without accents, a possessive 's or punctuation."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"['’]s\b", "", text)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def forms(name):
    """Returns the ways a name may be said: in full or by any one word of it."""
    full = normal(name)
    return {full, *full.split(" ")} if full else set()


def match_name(heard, members):
    """Matches what Alexa heard to a member. members is a list of (account_id, name). Returns
    ("exact", member), ("close", member) when it is only a likely match worth asking about, or
    (None, None).
    """
    said = normal(heard)
    if not said:
        return None, None
    for member in members:
        if said in forms(member[1]):
            return "exact", member
    scored = [
        (max(difflib.SequenceMatcher(None, said, form).ratio() for form in forms(m[1])), m)
        for m in members
        if forms(m[1])
    ]
    scored.sort(key=lambda item: -item[0])
    if scored and scored[0][0] >= CLOSE_ENOUGH:
        return "close", scored[0][1]
    return None, None


def names(members):
    """Lists members' names for speech: "Maya, Alex and Leo"."""
    spoken = [m[1] for m in members]
    return spoken[0] if len(spoken) == 1 else ", ".join(spoken[:-1]) + " and " + spoken[-1]


def clock(moment):
    """Returns a time as Alexa should say it, e.g. 4:30 PM."""
    return moment.strftime("%I:%M %p").lstrip("0")


def since(at_ms, now_ms, zone):
    """Returns when something started, to follow "since": "4:30 PM", "yesterday at 4:30 PM",
    "Tuesday at 4:30 PM" or "November 3". Without a time zone, says how long ago instead.
    """
    if zone is None:
        return None
    then = datetime.fromtimestamp(at_ms / 1000, zone)
    today = datetime.fromtimestamp(now_ms / 1000, zone).date()
    if then.date() == today:
        return clock(then)
    if then.date() == today - timedelta(days=1):
        return "yesterday at " + clock(then)
    if then.date() > today - timedelta(days=7):
        return then.strftime("%A") + " at " + clock(then)
    return then.strftime("%B ") + str(then.day)


def ago(at_ms, now_ms):
    """Returns how long ago, e.g. "5 minutes ago" or "3 hours ago"."""
    minutes = max(0, round((now_ms - at_ms) / 60000))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' * (minutes != 1)} ago"
    hours = round(minutes / 60)
    if hours < 48:
        return f"{hours} hour{'s' * (hours != 1)} ago"
    return f"{round(hours / 24)} days ago"


def street(address):
    """Returns an address without "Near" or a house number, for someone driving past."""
    return re.sub(r"^\d+[a-z]?\s+", "", address.removeprefix("Near "), flags=re.IGNORECASE)


def spot(place, address):
    """Says where a fix is: "at Home", "at 12 Main St, Town" or "near Main St, Town"."""
    if place:
        return "at " + place
    if address:
        return "near " + address[5:] if address.startswith("Near ") else "at " + address
    return None


def seen(when):
    """Says when, after "last seen": "at 4:30 PM", "yesterday at 4:30 PM" or "on Tuesday at
    4:30 PM".
    """
    if when.startswith("yesterday"):
        return when
    return ("at " if when[0].isdigit() else "on ") + when


def where(name, fix, place, still_since, address, now_ms, zone):
    """Describes where a member is from their latest fix: {at, speed, trip}. place is the saved
    place they are in, if any, and address a short street address (or None).
    """
    age = (now_ms - fix["at"]) / 60000
    moving = age < MOVING_MINUTES and (fix.get("trip") or (fix.get("speed") or 0) >= DRIVING_SPEED)
    if moving:
        return f"{name} is driving near {street(address)}." if address else f"{name} is driving."
    here = spot(place, address)
    if not here:
        return f"I have a location for {name} from {ago(fix['at'], now_ms)}, but no address for it."
    if age > FRESH_MINUTES:
        when = since(fix["at"], now_ms, zone)
        return f"{name} was last seen {here} {seen(when) if when else ago(fix['at'], now_ms)}."
    if still_since and now_ms - still_since >= 5 * 60000:
        when = since(still_since, now_ms, zone)
        if when:
            return f"{name} has been {here} since {when}."
        return f"{name} has been {here} for {ago(still_since, now_ms).removesuffix(' ago')}."
    return f"{name} is {here}."
