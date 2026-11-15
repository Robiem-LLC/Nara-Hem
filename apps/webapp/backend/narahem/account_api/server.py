"""Server version, health check and first-run setup."""

import hmac
import os
import re
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem import image_defaults
from narahem.app import (
    HASHER,
    digest,
    email_address,
)
from narahem.models import (
    Account,
    AccountApproval,
    ServiceState,
    Settings,
)
from narahem.schemas import (
    SetupInput,
)


def install(app, *, bootstrap_file, current, database, directory, public_url, rate, texting_on):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.get("/api/version")
    def server_version(auth=Depends(current)):
        """Returns the server build information, and where its source code is published, to
        signed-in users.
        """
        commit = os.environ.get("NARAHEM_BUILD_COMMIT", "")
        source = image_defaults.setting("NARAHEM_SOURCE_URL")
        return {
            "channel": os.environ.get("NARAHEM_BUILD_CHANNEL", "local"),
            "build": os.environ.get("NARAHEM_BUILD_NUMBER", "") or None,
            "commit": commit[:7] if re.fullmatch(r"[0-9a-f]{7,40}", commit) else None,
            "built": os.environ.get("NARAHEM_BUILD_UTC", "") or None,
            "source": source if source.startswith("https://") else None,
        }

    @app.get("/healthz")
    def health(db: Session = Depends(database)):
        """Health check: returns whether the server is up and whether setup has been completed."""
        return {"status": "ok", "stage": "setup", "configured": bool(db.get(Settings, 1).household)}

    @app.get("/api/setup")
    def setup_status(db: Session = Depends(database)):
        """Returns whether first-run setup has been completed, and whether people can sign in
        with a phone number (text messages are set up).
        """
        return {
            "configured": bool(db.get(Settings, 1).household),
            "texting": texting_on(db) is not None,
            "public_url": public_url,
            "location_service": "encrypted_relay",
        }

    @app.post("/api/setup", status_code=201)
    def setup(body: SetupInput, request: Request, db: Session = Depends(database)):
        """First-run setup: names the household and creates the admin account using the install
        token.
        """
        rate(request, "setup", 5)
        settings = db.execute(
            select(Settings).where(Settings.id == 1).with_for_update()
        ).scalar_one()
        if settings.household:
            raise HTTPException(409, "Setup is already complete")
        if not hmac.compare_digest(digest(body.token), settings.bootstrap_hash or ""):
            raise HTTPException(403, "Invalid setup token")
        name = body.household.strip()
        if not name:
            raise HTTPException(422, "Household name is required")
        owner = Account(
            id=secrets.token_hex(16),
            email=email_address(body.email),
            username=None,
            password=HASHER.hash(body.password),
            role="admin",
            status="active",
            verified=False,
        )
        db.add(owner)
        db.add(AccountApproval(account_id=owner.id, approved_by=owner.id, created=time.time()))
        state = db.get(ServiceState, 1)
        state.bootstrap_hash = digest(body.token)
        token_path = directory / "device-bootstrap-token"
        token_path.write_text(body.token)
        token_path.chmod(0o600)
        settings.household, settings.bootstrap_hash = name, None
        db.commit()
        bootstrap_file.unlink(missing_ok=True)
        return {"configured": True}
