"""The showcase family: who they are, the places they share, and where they go.

Everything here is fictional. Routes follow real streets when the public OSRM
demo router is reachable (it is on the build runner) and fall back to straight
lines otherwise, which is enough for local development.
"""

import time

import httpx
from household import meters

HOUSEHOLD = "The Rivera Family"
OWNER = ("jamie@narahem.example", "Jamie")
PASSWORD = "showcase family password"

PLACES = {
    "Home": (45.50045, -122.64180),
    "Lincoln Middle School": (45.50410, -122.65520),
    "Alex's office": (45.51890, -122.67900),
    "Grandma's house": (45.53390, -122.60610),
    "Laurelhurst Park": (45.52110, -122.62530),
}

# name, email, initials, avatar color, platform
MEMBERS = [
    ("Alex", "alex@narahem.example", "A", (37, 99, 235), "ios"),
    ("Maya", "maya@narahem.example", "M", (219, 39, 119), "android"),
    ("Leo", "leo@narahem.example", "L", (22, 163, 74), "ios"),
    ("Grandma Rosa", "rosa@narahem.example", "R", (217, 119, 6), "android"),
]

# Family members who sign in with a real phone app while it is filmed (no simulated phone).
# The owner, Jamie, uses the iPhone; Sam uses the Android phone.
APP_MEMBERS = [("Sam", "sam@narahem.example")]
# Each filmed phone's own drive: (from, to).
PHONE_ROUTES = {
    "ios": ("Grandma's house", "Home"),
    "android": ("Lincoln Middle School", "Laurelhurst Park"),
}

# Trips earlier today: (member, from, to, hours ago it started, minutes it took)
HISTORY = [
    ("Alex", "Home", "Alex's office", 9.0, 11),
    ("Maya", "Home", "Lincoln Middle School", 8.6, 6),
    ("Leo", "Home", "Lincoln Middle School", 8.5, 7),
    ("Grandma Rosa", "Grandma's house", "Laurelhurst Park", 5.0, 8),
    ("Grandma Rosa", "Laurelhurst Park", "Grandma's house", 3.5, 9),
    ("Maya", "Lincoln Middle School", "Laurelhurst Park", 1.2, 10),
]

# While the camera rolls: (member, from, to, seconds for the whole move)
LIVE = [
    ("Alex", "Alex's office", "Home", 45),
    ("Maya", "Laurelhurst Park", "Home", 45),
]
# Members who stay put during recording.
PARKED = {"Leo": "Home", "Grandma Rosa": "Grandma's house"}


# How many routes followed streets and how many fell back to straight lines.
ROUTES = {"street": 0, "straight": 0}


def road_path(start, end, points=60):
    """Returns evenly spaced positions along a street route."""
    try:
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson"
        )
        route = httpx.get(url, timeout=15, headers={"User-Agent": "NaraHem-showcase"}).json()
        line = [(lat, lon) for lon, lat in route["routes"][0]["geometry"]["coordinates"]]
        ROUTES["street"] += 1
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        line = [start, end]
        ROUTES["straight"] += 1
    return resample(line, points)


def resample(line, points):
    """Returns evenly spaced points along a line."""
    lengths = [0.0]
    for a, b in zip(line, line[1:]):
        lengths.append(lengths[-1] + meters(a, b))
    total = lengths[-1] or 1
    out, segment = [], 0
    for i in range(points):
        target = total * i / (points - 1)
        while segment < len(line) - 2 and lengths[segment + 1] < target:
            segment += 1
        span = (lengths[segment + 1] - lengths[segment]) or 1
        t = min(1, max(0, (target - lengths[segment]) / span))
        a, b = line[segment], line[segment + 1] if len(line) > 1 else line[segment]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def now_ms():
    """Returns the current time in milliseconds."""
    return int(time.time() * 1000)
