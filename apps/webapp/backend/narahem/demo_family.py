"""A made-up family that lives on a demo server, so App Store reviewers see a household in use.

Runs as its own container in the demo stack (deploy/demo-stack.yaml), from the server image:

    python -m narahem.demo_family

It waits until the administrator has set up the household in a browser, then creates the
reviewer's account and four family members with phones, shares their locations, saves places,
back-fills today's trips and keeps someone driving around town, day and night. Their phones get
the server's review code, so the server must be in review mode for the family's addresses
(review_mode.py). Everything is fictional; never point this at a real household's server.

Environment: DATABASE_URL and NARAHEM_PUBLIC_URL (the same as the server's),
NARAHEM_DEMO_SERVER (the server on the stack network, default http://narahem:8080),
NARAHEM_DEMO_PASSWORD (the reviewer's password), NARAHEM_DEMO_REVIEWER (the reviewer's
address, default review@demo.example.com), NARAHEM_REVIEW_CODE and NARAHEM_DEMO_STATE (where
phone keys are kept, default /data/demo-family.json).
"""

import json
import os
import random
import secrets
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from narahem.app import HASHER, trusted_accounts
from narahem.demo_phone import DemoPhone, Server, meters
from narahem.models import Account, AccountApproval, ClientDevice, ServiceState

DOMAIN = "demo.example.com"
SERVICE_ID = "0" * 32
PHOTOS = json.loads((Path(__file__).parent / "demo_photos.json").read_text())

PLACES = {
    "Home": (45.50045, -122.64180),
    "Lincoln Middle School": (45.50410, -122.65520),
    "Alex's office": (45.51890, -122.67900),
    "Grandma's house": (45.53390, -122.60610),
    "Laurelhurst Park": (45.52110, -122.62530),
    "Grocery store": (45.51240, -122.65310),
}

# name, platform, where they can go (the first is where they start)
MEMBERS = {
    "Alex": ("ios", ["Home", "Alex's office", "Grocery store", "Grandma's house"]),
    "Maya": ("android", ["Home", "Lincoln Middle School", "Laurelhurst Park", "Grocery store"]),
    "Leo": ("ios", ["Home", "Lincoln Middle School", "Laurelhurst Park"]),
    "Grandma Rosa": ("android", ["Grandma's house", "Laurelhurst Park", "Grocery store", "Home"]),
}

# Trips already made today: (member, from, to, hours ago it started, minutes it took)
HISTORY = [
    ("Alex", "Home", "Alex's office", 9.0, 11),
    ("Maya", "Home", "Lincoln Middle School", 8.6, 6),
    ("Leo", "Home", "Lincoln Middle School", 8.5, 7),
    ("Grandma Rosa", "Grandma's house", "Laurelhurst Park", 5.0, 8),
    ("Grandma Rosa", "Laurelhurst Park", "Grandma's house", 3.5, 9),
    ("Maya", "Lincoln Middle School", "Laurelhurst Park", 1.2, 10),
    ("Leo", "Lincoln Middle School", "Home", 0.8, 8),
]


def say(message):
    """Prints a line to the container log."""
    print(time.strftime("%H:%M:%S ") + message, flush=True)


def email(name):
    """Returns a member's made-up address."""
    return name.split()[-1].lower() + "@" + DOMAIN


class Family:
    """The family, their phones and what they are doing, kept in the state file."""

    def __init__(self, server, path, reviewer, password, code):
        """Loads the state file, if there is one."""
        self.server, self.path, self.code = server, Path(path), code
        self.reviewer, self.password = reviewer, password
        self.saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.saved.setdefault("members", {})
        self.saved.setdefault("routes", {})
        self.phones, self.driving = {}, None
        # When the family last looked for members to share with; see wait().
        self.shared_at = 0.0

    def save(self):
        """Writes the state file, readable only by this container."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.saved))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def ready(self):
        """Returns True once the household exists and the administrator's browser has turned on
        phone enrollment. Until then, says what the administrator still has to do.
        """
        with Session(self.server.engine) as db:
            state = db.get(ServiceState, 1)
            owner = db.scalar(select(Account).where(Account.role == "admin"))
            service = db.get(ClientDevice, SERVICE_ID)
            if not state or not owner:
                say("Waiting for first-run setup: open the demo server in a browser.")
                return False
            # The family "joined" a month ago: members only see trips from the day they joined.
            approval = db.get(AccountApproval, owner.id)
            if approval and approval.created > time.time() - 86400:
                approval.created = time.time() - 30 * 86400
                db.commit()
            if not service or service.status != "approved":
                say("Waiting for the administrator to sign in and trust this browser.")
                return False
            return True

    def account(self, address, name, password):
        """Creates or updates a verified member account and returns its ID."""
        with Session(self.server.engine) as db:
            account = db.scalar(select(Account).where(Account.email == address))
            if not account:
                account = Account(
                    id=secrets.token_hex(16),
                    email=address,
                    username=name,
                    role="member",
                    status="active",
                )
                db.add(account)
            account.verified, account.status = True, "active"
            account.password = HASHER.hash(password)
            db.commit()
            return account.id

    def owner(self):
        """Returns the administrator's account ID."""
        with Session(self.server.engine) as db:
            return db.scalar(select(Account.id).where(Account.role == "admin"))

    def everyone(self):
        """Returns every active, confirmed account: the administrator, reviewers, testers on an
        open demo server and the family. Anyone added later, such as a second store's reviewer, is
        shared with like a new member is. An account still waiting for its code can't be shared
        with yet; it's picked up within a minute of confirming.
        """
        with Session(self.server.engine) as db:
            return set(
                db.scalars(select(Account.id).where(Account.status == "active", trusted_accounts()))
            )

    def share_with_everyone(self):
        """Has each phone share with every other active account, if that has changed."""
        accounts = self.everyone()
        for phone in self.phones.values():
            viewers = accounts - {phone.account_id}
            if viewers != phone.viewers:
                phone.share_with(viewers)

    def phone(self, name):
        """Restores the member's phone, or enrolls a new one."""
        platform, places = MEMBERS[name]
        member = self.saved["members"].setdefault(name, {"at": places[0], "battery": 90})
        password = secrets.token_urlsafe(24)
        account_id = self.account(email(name), name, password)
        if member.get("phone") and member.get("account_id") == account_id:
            try:
                return DemoPhone(self.server, account_id, name, member["phone"])
            except (PermissionError, httpx.HTTPError) as error:
                say(f"{name}'s saved phone can't be used ({error}); enrolling a new one.")
        phone, saved = DemoPhone.enroll(
            self.server, account_id, name, email(name), password, self.code, platform
        )
        member.update(phone=saved, account_id=account_id, new=True)
        self.save()
        say(f"{name}'s {platform} phone joined.")
        return phone

    def route(self, start, end, points=40):
        """Returns positions along the streets from one place to another (straight if the
        public router can't be reached), remembered in the state file.
        """
        key = f"{start}|{end}"
        if key not in self.saved["routes"]:
            a, b = PLACES[start], PLACES[end]
            try:
                reply = httpx.get(
                    f"https://router.project-osrm.org/route/v1/driving/"
                    f"{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson",
                    timeout=15,
                    headers={"User-Agent": "NaraHem-demo"},
                ).json()
                line = [(y, x) for x, y in reply["routes"][0]["geometry"]["coordinates"]]
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                return resample([a, b], points)
            self.saved["routes"][key] = resample(line, points)
            self.save()
        return [tuple(p) for p in self.saved["routes"][key]]

    def start(self):
        """Creates the reviewer and the family, then publishes everything a new household
        would have by this afternoon.
        """
        self.account(self.reviewer, "Sam", self.password)
        self.phones = {name: self.phone(name) for name in MEMBERS}
        self.share_with_everyone()
        for name, phone in self.phones.items():
            if self.saved["members"][name].pop("new", False):
                phone.profile(PHOTOS[name])
        if not self.saved.get("places"):
            for place, (lat, lon) in PLACES.items():
                self.phones["Alex"].place(place, lat, lon)
            self.saved["places"] = True
        if not self.saved.get("history"):
            self.history()
        for name in MEMBERS:
            self.park(name)
        self.save()

    def history(self):
        """Back-fills today's trips, ending each member where their last trip did."""
        now = time.time() * 1000
        for name, start, end, hours_ago, minutes in HISTORY:
            began = now - hours_ago * 3_600_000
            path = self.route(start, end)
            self.phones[name].drive(path, began, began + minutes * 60_000, origin_name=start)
            self.saved["members"][name]["at"] = end
        self.saved["history"] = time.time()
        say("Today's trips are in.")

    def park(self, name):
        """Reports the member standing still where they are, a little off the exact spot."""
        member = self.saved["members"][name]
        lat, lon = PLACES[member["at"]]
        member["battery"] = max(20, member["battery"] - random.randint(0, 2))
        self.phones[name].location(
            lat + random.uniform(-0.00008, 0.00008),
            lon + random.uniform(-0.00008, 0.00008),
            battery=member["battery"],
        )

    def outing(self):
        """Sends one member on a drive to another of their places, in real time."""
        name = random.choice(list(MEMBERS))
        member = self.saved["members"][name]
        start = member["at"]
        end = random.choice([p for p in MEMBERS[name][1] if p != start])
        path = self.route(start, end)
        length = sum(meters(a, b) for a, b in zip(path, path[1:]))
        minutes = min(14, max(4, length / 9 / 60))
        say(f"{name} is driving from {start} to {end} ({minutes:.0f} minutes).")
        self.driving = name
        began = time.time() * 1000
        member["battery"] = min(100, member["battery"] + random.randint(0, 6))
        self.phones[name].drive(
            path,
            began,
            began + minutes * 60_000,
            origin_name=start,
            wait=self.wait,
            battery=member["battery"],
        )
        member["at"], self.driving = end, None
        self.save()

    def wait(self, seconds):
        """Waits, while the family shares with anyone new every minute and the members who
        aren't driving check in every ten minutes. Drives wait here too.
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(min(5, max(0, deadline - time.time())))
            if time.time() - self.shared_at > 60:
                self.shared_at = time.time()
                try:
                    self.share_with_everyone()
                except (RuntimeError, httpx.HTTPError) as error:
                    say(str(error))
            if time.time() - self.saved.get("checked_in", 0) > 600:
                self.saved["checked_in"] = time.time()
                for name in [n for n in MEMBERS if n != self.driving]:
                    try:
                        self.park(name)
                    except RuntimeError as error:
                        say(str(error))

    def live(self):
        """Keeps the family going: a drive, a short break, another drive."""
        while True:
            try:
                self.outing()
            except (RuntimeError, httpx.HTTPError) as error:
                self.driving = None
                say(str(error))
            self.wait(random.randint(4, 15) * 60)


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


def main():
    """Waits for the household, then runs the family until the container stops."""
    code, password = (
        os.environ.get("NARAHEM_REVIEW_CODE", ""),
        os.environ.get("NARAHEM_DEMO_PASSWORD", ""),
    )
    if not code or len(password) < 12:
        sys.exit("Set NARAHEM_REVIEW_CODE and a NARAHEM_DEMO_PASSWORD of 12 characters or more")
    server = Server(
        create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True),
        os.environ.get("NARAHEM_DEMO_SERVER", "http://narahem:8080"),
        os.environ["NARAHEM_PUBLIC_URL"].rstrip("/"),
    )
    family = Family(
        server,
        os.environ.get("NARAHEM_DEMO_STATE", "/data/demo-family.json"),
        os.environ.get("NARAHEM_DEMO_REVIEWER", "review@" + DOMAIN).strip().lower(),
        password,
        code,
    )
    while True:
        try:
            if family.ready():
                family.start()
                break
        except Exception as error:  # noqa: BLE001 - keep waiting while the server starts
            say(f"Not ready yet: {error}")
        time.sleep(60)
    say(f"The demo family is running. The reviewer signs in as {family.reviewer}.")
    family.live()


if __name__ == "__main__":
    main()
