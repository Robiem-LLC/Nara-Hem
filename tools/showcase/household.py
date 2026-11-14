"""A fake household for the Nära Hem showcase.

Runs a real Nära Hem server in this process and simulated family phones that
enroll, share and publish exactly as the apps do: signed device registration,
emailed phone codes (captured here), and end-to-end encrypted records. Nothing
real is involved; every name, photo and position is made up.
"""

import base64
import io
import secrets
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/webapp/backend"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from narahem.app import HASHER, create_app, trusted_accounts  # noqa: E402
from narahem.models import Account, AccountApproval, ClientDevice, ServiceState  # noqa: E402

SERVICE_ID = "0" * 32
B64 = lambda value: base64.b64encode(bytes(value)).decode()  # noqa: E731


class ShowcaseServer:
    """A local Nära Hem server for the showcase, with outgoing email captured instead of sent."""

    def __init__(self, directory, port, maps_key="", public_url=None, mail_worker=False):
        """Starts the server on 127.0.0.1 with its data in directory. mail_worker sends queued
        email (invitations, confirmation links) as a real server does.
        """
        # public_url is an HTTPS tunnel to this server when real phone apps connect to it.
        self.directory, self.port = Path(directory), port
        self.origin = public_url or f"http://127.0.0.1:{port}"
        self.mail = []
        self.app = create_app(
            f"sqlite:///{self.directory}/showcase.db",
            self.directory,
            self.origin,
            allow_http=self.origin.startswith("http:"),
            mailer=lambda *message: self.mail.append(message),
            mail_worker=mail_worker,
            google_maps_api_key=maps_key,
        )
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning")
        )
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(200):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("Showcase server did not start")

    def stop(self):
        """Stops the server."""
        self.server.should_exit = True

    def code_for(self, email, after=0, timeout=90):
        """Returns the six-digit code from the first email to the address after message number
        after.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.mail[after:]:
                if message[1] == email and "Enter " in message[3]:
                    return message[3].split("Enter ")[1][:6]
            time.sleep(0.5)
        raise RuntimeError(f"No code was emailed to {email}")

    def client(self):
        """Returns an HTTP client for the server."""
        return httpx.Client(base_url=self.origin, headers={"Origin": self.origin}, timeout=30)

    def setup(self, household, email, password):
        """Runs first-run setup and signs in the admin."""
        token = (self.directory / "bootstrap-token").read_text().strip()
        owner = self.client()
        response = owner.post(
            "/api/setup",
            json={"token": token, "household": household, "email": email, "password": password},
        )
        response.raise_for_status()
        login = owner.post("/api/login", json={"email": email, "password": password})
        login.raise_for_status()
        owner.headers["X-CSRF-Token"] = login.json()["csrf"]
        # Mail is captured by this process, never sent; the settings only need to look real.
        owner.put(
            "/api/mail",
            json={
                "host": "smtp.example.com",
                "port": 587,
                "mode": "starttls",
                "username": email,
                "password": "showcase",
                "sender": email,
            },
        ).raise_for_status()
        owner.post("/api/mail/test", json={}).raise_for_status()
        self.owner = owner
        # Stands in for the owner clicking the emailed confirmation link; phones need it.
        # The family also "joined" a month ago: members only see others' trips from the
        # (UTC) day they joined, and today's trips started before this server existed.
        with Session(self.app.state.engine) as db:
            account = db.scalars(select(Account).where(Account.email == email)).one()
            account.verified = True
            approval = db.get(AccountApproval, account.id)
            if approval:
                approval.created = time.time() - 30 * 86400
            db.commit()
        return (self.directory / "device-bootstrap-token").read_text().strip()

    def enrollment_ready(self):
        """Returns True once the admin's browser has added the enrollment signer to the roster."""
        with Session(self.app.state.engine) as db:
            service = db.get(ClientDevice, SERVICE_ID)
            return bool(service and service.status == "approved")

    def add_member(self, email, name, password):
        """Inserts a verified member directly into the database."""
        with Session(self.app.state.engine) as db:
            account = Account(
                id=secrets.token_hex(16),
                email=email,
                username=name,
                role="member",
                status="active",
                verified=True,
                password=HASHER.hash(password),
            )
            db.add(account)
            db.commit()
            return account.id

    def account_id(self, email):
        """Returns the ID of the account with this email address."""
        with Session(self.app.state.engine) as db:
            return db.scalar(select(Account.id).where(Account.email == email))

    def owner_id(self):
        """Returns the admin's account ID."""
        with Session(self.app.state.engine) as db:
            return db.scalar(select(Account.id).where(Account.role == "admin"))

    def state(self):
        """Returns the household ID and roster revision."""
        with Session(self.app.state.engine) as db:
            state = db.get(ServiceState, 1)
            return state.household_id, state.revision

    def recipients_for(self, account_id, viewers):
        """Returns the devices a record from this account must be encrypted for."""
        with Session(self.app.state.engine) as db:
            devices = db.scalars(
                select(ClientDevice)
                .join(Account, Account.id == ClientDevice.account_id)
                .where(
                    ClientDevice.status == "approved",
                    Account.status == "active",
                    trusted_accounts(),
                )
                .order_by(ClientDevice.id)
            )
            return [
                (d.id, d.box_key)
                for d in devices
                if d.account_id == account_id or d.account_id in viewers
            ]

    def all_devices(self):
        """Returns every approved device."""
        with Session(self.app.state.engine) as db:
            devices = db.scalars(
                select(ClientDevice)
                .join(Account, Account.id == ClientDevice.account_id)
                .where(
                    ClientDevice.status == "approved",
                    Account.status == "active",
                    trusted_accounts(),
                )
                .order_by(ClientDevice.id)
            )
            return [(d.id, d.box_key) for d in devices]


def meters(a, b):
    """Returns the distance between two (lat, lon) points in metres."""
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 12_742_000 * asin(sqrt(h))


def avatar(initials, color):
    """Returns a small JPEG profile photo showing the initials on a coloured circle."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (160, 160), color)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except OSError:
        font = ImageFont.load_default(64)
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(
        ((160 - box[2] - box[0]) / 2, (160 - box[3] - box[1]) / 2),
        initials,
        fill="white",
        font=font,
    )
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
