"""Time zones phones send with their locations and trips, so viewers in another zone can see the
person's own time beside theirs.
"""

import re

# An IANA zone name such as "America/New_York" or "UTC".
ZONE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}")


def zone_name(value):
    """Returns value if it looks like an IANA time zone name, otherwise None."""
    return value if isinstance(value, str) and len(value) <= 64 and ZONE.fullmatch(value) else None
