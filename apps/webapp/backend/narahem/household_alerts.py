"""Household alerts, decided by the server from the GPS and trips it receives.

"<name> left <place>" when a phone clearly leaves a saved place (or starts a drive
from somewhere unsaved), and one combined "<name> arrived at <place> after a
7.1 mile drive, top speed 63 mph" when a drive ends. Same rules the apps used.
"""

import math

import httpx

STALE_MS = 15 * 60_000  # an alert this old is old news
MIN_TRIP_METERS = 400.0  # shorter "trips" are GPS drift or a walk to the car
BOUNDARY_MS = 120_000  # fixes this close to a trip's start or end still say where it was
# A parked phone checks in only every 15 minutes or so and GPS starts after the car does, so the
# place before a trip can be this far back, as long as nothing nearer says otherwise.
START_LOOKBACK_MS = 30 * 60_000


def meters(a_lat, a_lon, b_lat, b_lon):
    """Returns the great-circle distance between two points in metres."""
    r = math.pi / 180
    h = (
        math.sin((b_lat - a_lat) * r / 2) ** 2
        + math.cos(a_lat * r) * math.cos(b_lat * r) * math.sin((b_lon - a_lon) * r / 2) ** 2
    )
    return 12_742_000 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def match(lat, lon, places, accuracy=25.0):
    """Returns the saved place containing the point, allowing for GPS accuracy (clamped to 15-50
    m), or None.
    """
    tolerance = min(50.0, max(15.0, accuracy)) if math.isfinite(accuracy) else 25.0
    near = [(p, meters(lat, lon, p["lat"], p["lon"])) for p in places]
    near = [(p, d) for p, d in near if d <= p["radius"] + tolerance]
    near.sort(key=lambda item: (item[1] > item[0]["radius"], item[1]))
    return near[0][0] if near else None


def clearly_outside(lat, lon, place, accuracy):
    """Returns True once a point is well clear of a saved place, so GPS drift at the edge doesn't
    count as leaving.
    """
    return meters(lat, lon, place["lat"], place["lon"]) > place["radius"] + max(75.0, accuracy)


def allowed(place, member, departure):
    """Returns whether the place's alert rules allow this member's arrival or departure alert. A
    place without rules alerts for everyone.
    """
    rules = place.get("alerts") or {}
    if not rules:
        return True
    rule = rules.get(member)
    return isinstance(rule, dict) and rule.get("departure" if departure else "arrival") is True


def miles(distance):
    """Formats metres as miles: one decimal place under 10, whole numbers above."""
    value = distance / 1609.344
    return f"{value:.1f}" if value < 10 else str(int(round(value)))


def render(name, alert):
    """Returns the notification text for an alert."""
    where = alert["place"]
    if alert["kind"] == "left":
        return f"{name} left {where}"
    if alert.get("distance_m") is not None and alert.get("max_speed_mps") is not None:
        return (
            f"{name} arrived at {where} after a {miles(alert['distance_m'])} mile drive, "
            f"top speed {int(round(alert['max_speed_mps'] * 2.236936))} mph"
        )
    return f"{name} arrived at {where}"


def place_from(address):
    """Lowercases a leading "Near" so an address reads naturally mid-sentence."""
    if not address:
        return "an unsaved place"
    return "near " + address[5:] if address.startswith("Near ") else address


def fresh_memory():
    """Returns an empty alert memory for a device. Keys: inside (saved place the phone is in),
    parked ([lat, lon] when not driving), trip_id (last trip seen), departed_at (time of the
    last departure alert), last_at (newest fix used), still_at and still_since (where and
    since when the phone has been stationary).
    """
    return {
        "inside": None,
        "parked": None,
        "trip_id": None,
        "departed_at": 0,
        "last_at": 0,
        "still_at": None,
        "still_since": None,
    }


def still(memory, lat, lon, accuracy, moving, now):
    """Updates the stationary position and start time. A trip or real movement resets it."""
    anchor = memory.get("still_at")
    if moving or not anchor or meters(anchor[0], anchor[1], lat, lon) > max(100.0, 2 * accuracy):
        return dict(memory, still_at=[lat, lon], still_since=now)
    return memory


def on_fix(memory, member, lat, lon, accuracy, trip_id, now, places):
    """Processes a new fix and returns the updated memory and any alerts: leaving a saved place,
    or starting a trip from elsewhere. Each alert is {kind, place} or {kind, at: [lat, lon]}
    when an address still needs looking up.
    """
    alerts = []
    fix = accuracy if math.isfinite(accuracy) and accuracy >= 0 else 25.0
    current = match(lat, lon, places, fix)
    previous = next((p for p in places if p["id"] == memory.get("inside")), None)
    nxt = dict(memory, last_at=now)
    if previous is None:
        nxt["inside"] = None
    if previous is not None and (current or {}).get("id") != previous["id"]:
        # Only count as left once clearly outside, so GPS drift at the edge doesn't alert.
        if clearly_outside(lat, lon, previous, fix):
            if allowed(previous, member, departure=True):
                alerts.append({"kind": "left", "place": previous["name"]})
                nxt["departed_at"] = now
            nxt["inside"] = current["id"] if current else None
    elif current is not None:
        nxt["inside"] = current["id"]

    if trip_id:
        if trip_id != memory.get("trip_id"):
            nxt["trip_id"] = trip_id
            start = memory.get("parked")
            if (
                start
                and now - nxt["departed_at"] >= STALE_MS
                and previous is None
                and match(start[0], start[1], places) is None
            ):
                alerts.append({"kind": "left", "at": start})
                nxt["departed_at"] = now
            nxt["parked"] = None
    else:
        nxt["parked"] = [lat, lon]
    return still(nxt, lat, lon, fix, bool(trip_id), now), alerts


def on_trip_end(memory, member, end, distance, max_speed, places):
    """Returns the updated memory and an arrival alert with the trip's distance and top speed."""
    saved = match(end[0], end[1], places)
    nxt = dict(memory, inside=saved["id"] if saved else None, parked=list(end), still_at=list(end))
    if distance < MIN_TRIP_METERS or (saved and not allowed(saved, member, departure=False)):
        return nxt, None
    alert = {"kind": "arrived", "distance_m": distance, "max_speed_mps": max_speed}
    if saved:
        alert["place"] = saved["name"]
    else:
        alert["at"] = list(end)
    return nxt, alert


def boundary_place(point, at, fixes, places, after):
    """Returns the saved place where a trip started or ended. Recorded trip ends often fall short
    of the destination, so fixes from the following two minutes count. Before a start, the nearest
    fix in the last half hour decides, ignoring fixes from the two minutes of GPS warm-up that are
    not at a place.
    """
    if not point:
        return None
    direct = match(point[0], point[1], places)
    if direct:
        return direct
    window = BOUNDARY_MS if after else START_LOOKBACK_MS
    near = [
        f
        for f in fixes
        if f["accuracy"] <= 70 and 0 <= (f["time"] - at if after else at - f["time"]) <= window
    ]
    for fix in sorted(near, key=lambda f: abs(f["time"] - at)):
        place = match(fix["lat"], fix["lon"], places, fix["accuracy"])
        seconds = abs(fix["time"] - at) / 1000
        if (
            place
            and seconds >= 1
            and meters(point[0], point[1], fix["lat"], fix["lon"])
            <= 65 * seconds + 25 + fix["accuracy"]
        ):
            return place
        if not place and seconds > BOUNDARY_MS / 1000:
            return None  # they were somewhere else in between
    return None


def lookup_address(lat, lon, google_key=""):
    """Returns a short street address near the point, or None. Uses Google's Geocoding API when a
    key is configured, otherwise OpenStreetMap Nominatim.
    """

    with httpx.Client(timeout=5, follow_redirects=False) as client:
        if google_key:
            try:
                reply = client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"latlng": f"{lat:.6f},{lon:.6f}", "key": google_key},
                ).json()
                if reply.get("status") == "OK" and reply.get("results"):
                    result = reply["results"][0]
                    parts = {
                        t: c.get("short_name")
                        for c in result.get("address_components", [])
                        for t in c.get("types", [])
                    }
                    spot = result.get("geometry", {}).get("location", {})
                    found = (spot.get("lat"), spot.get("lng"))
                    return _label(
                        lat,
                        lon,
                        found,
                        parts.get("street_number"),
                        parts.get("route"),
                        parts.get("locality")
                        or parts.get("postal_town")
                        or parts.get("sublocality"),
                    )
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        try:
            reply = client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18},
                headers={"User-Agent": "NaraHem self-hosted household server"},
            ).json()
            parts = reply.get("address") or {}
            found = (float(reply["lat"]), float(reply["lon"]))
            return _label(
                lat,
                lon,
                found,
                parts.get("house_number"),
                parts.get("road"),
                parts.get("city")
                or parts.get("town")
                or parts.get("village")
                or parts.get("hamlet"),
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None


def _label(lat, lon, found, number, street, town):
    """Formats an address as "12 Main St, Town", or "Near ..." when there is no house number or
    the match isn't close.
    """
    if not street or None in found:
        return None
    distance = meters(lat, lon, float(found[0]), float(found[1]))
    if distance > 150:
        return None
    line = f"{number} {street}" if number else street
    text = ", ".join(part for part in (line, town) if part)[:180]
    return ("Near " if distance > 30 or not number else "") + text
