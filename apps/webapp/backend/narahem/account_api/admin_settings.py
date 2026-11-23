"""Administrator status and password, mail and text message settings, first-device email."""

import json
import re
import secrets
import smtplib
import time

from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem import texting
from narahem.app import (
    DUMMY_HASH,
    HASHER,
    app_links,
    client_ip,
    digest,
    email_address,
)
from narahem.data_service import (
    bootstrap_email_hash,
)
from narahem.models import (
    ClientDevice,
    DeviceBootstrapChallenge,
    LoginSession,
    NativeRefreshSession,
    Outbox,
    PasswordReset,
    Rate,
    ServiceState,
    Settings,
)
from narahem.schemas import (
    ChangePasswordInput,
    Input,
    MailInput,
)

MAIL_UNREACHABLE = (
    "Could not connect to the mail server. Check the server name, port and encryption under "
    "Advanced."
)


def install(
    app,
    *,
    admin,
    cipher,
    database,
    deliver,
    directory,
    flush_mail,
    mail_settings,
    public_url,
    rate,
    texting_key,
    check_texting,
    texting_on,
    send_text,
):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.get("/api/admin")
    def dashboard(auth=Depends(admin), db: Session = Depends(database)):
        """Returns the admin overview: household name, settings and counts."""
        settings = db.get(Settings, 1)
        return {
            "household": settings.household,
            "public_url": public_url,
            "mail_configured": bool(settings.smtp),
            "mail_tested": settings.mail_tested,
            "location_service": "encrypted_relay",
            "device_pairing": "signed_roster",
            "pending_mail": db.query(Outbox).filter_by(status="pending").count(),
        }

    @app.post("/api/admin/change-password")
    def change_admin_password(
        body: ChangePasswordInput,
        request: Request,
        auth=Depends(admin),
        db: Session = Depends(database),
    ):
        """Changes the admin password after checking the current one, and ends every other
        session.
        """
        # Requires the current password; an active session alone isn't enough.
        rate(request, "password-change", 5)
        account, current_session = auth
        try:
            valid = HASHER.verify(account.password or DUMMY_HASH, body.current_password)
        except VerificationError:
            valid = False
        if not valid:
            raise HTTPException(403, "Current password is incorrect")
        if body.new_password == body.current_password:
            raise HTTPException(422, "Choose a different new password")
        account.password = HASHER.hash(body.new_password)
        # Also invalidates any outstanding reset link.
        db.query(PasswordReset).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(Outbox).filter_by(account_id="r:" + account.id, status="pending").update(
            {Outbox.status: "expired", Outbox.payload: ""}
        )
        # Keep this session; end every other browser and phone session.
        db.query(LoginSession).filter(
            LoginSession.account_id == account.id, LoginSession.id != current_session.id
        ).delete(synchronize_session=False)
        db.query(NativeRefreshSession).filter_by(account_id=account.id).delete(
            synchronize_session=False
        )
        db.commit()
        return {"changed": True, "other_sessions_signed_out": True}

    @app.get("/api/mail")
    def get_mail(auth=Depends(admin), db: Session = Depends(database)):
        """Returns the SMTP settings without the password."""
        if not db.get(Settings, 1).smtp:
            return {"configured": False}
        config = mail_settings(db)
        config.pop("password", None)
        return {"configured": True, **config}

    @app.put("/api/mail")
    def save_mail(
        body: MailInput, request: Request, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Validates and saves the SMTP settings."""
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", body.host):
            raise HTTPException(422, "Use an SMTP hostname or IP")
        settings = db.execute(
            select(Settings).where(Settings.id == 1).with_for_update()
        ).scalar_one()
        previous = mail_settings(db) if settings.smtp else {}
        config = body.model_dump()
        config["sender"] = email_address(body.sender)
        config["password"] = (
            body.password if body.password is not None else previous.get("password", "")
        )
        if config != previous:
            settings.smtp, settings.mail_tested = (
                cipher.encrypt(json.dumps(config).encode()).decode(),
                False,
            )
            key = digest(f"{client_ip(request)}:mail")
            db.query(Rate).filter(Rate.id == key).delete()
        db.commit()
        return {"saved": True}

    @app.post("/api/mail/test")
    def test_mail(request: Request, auth=Depends(admin), db: Session = Depends(database)):
        """Sends a test email to the admin."""
        rate(request, "mail", 10)
        try:
            deliver(
                mail_settings(db),
                auth[0].email,
                "Nära Hem email test",
                "Your server's encrypted SMTP connection is working.",
            )
        except smtplib.SMTPAuthenticationError as error:
            raise HTTPException(
                424, "The mail server rejected the username or password."
            ) from error
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as error:
            raise HTTPException(424, MAIL_UNREACHABLE) from error
        except smtplib.SMTPException as error:
            # SMTP errors are also OSErrors, so they are handled before network errors.
            raise HTTPException(
                424, "The mail server refused the test email; check the email address."
            ) from error
        except OSError as error:
            raise HTTPException(424, MAIL_UNREACHABLE) from error
        db.get(Settings, 1).mail_tested = True
        db.commit()
        return {"sent": True}

    class TextingInput(Input):
        """A Textbelt key to save, or an empty one to turn texting off."""

        key: str = Field(default="", max_length=256)

    class TextTestInput(Input):
        """Where to send a test text."""

        phone: str = Field(min_length=7, max_length=32)

    def texting_status(db):
        """Returns the text message settings for the Admin settings card. Never the key."""
        settings = db.get(Settings, 1)
        key, source = texting_key(db)
        checked = bool(key) and settings.sms_checked_key == digest(key)
        return {
            "provider": "Textbelt",
            "source": source,
            "key_hint": texting.hint(key) if key else None,
            "enabled": texting_on(db) is not None,
            "quota": settings.sms_quota if checked else None,
            "error": settings.sms_error if checked else None,
            "checked_at": settings.sms_checked if checked else None,
            # What to list when asking Textbelt to allow links.
            "link_domains": texting.link_domains(public_url, app_links()),
        }

    @app.get("/api/texting")
    def get_texting(auth=Depends(admin), db: Session = Depends(database)):
        """Returns whether text messages are on, where the key comes from and its credit."""
        return texting_status(db)

    @app.put("/api/texting")
    def save_texting(
        body: TextingInput, request: Request, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Saves (or with an empty key, removes) the Textbelt key, then checks it."""
        rate(request, "texting", 10)
        if texting.environment_key():
            raise HTTPException(
                409, "The key is set by the server's NARAHEM_TEXTBELT_KEY environment variable"
            )
        key = body.key.strip()
        db.get(Settings, 1).sms = cipher.encrypt(key.encode()).decode() if key else None
        db.commit()
        check_texting(db)
        return texting_status(db)

    @app.post("/api/texting/check")
    def recheck_texting(request: Request, auth=Depends(admin), db: Session = Depends(database)):
        """Checks the key in use with Textbelt again."""
        rate(request, "texting", 10)
        check_texting(db)
        return texting_status(db)

    @app.post("/api/texting/test")
    def test_text(
        body: TextTestInput, request: Request, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Sends a test text. It has no links, like every text Nära Hem sends, since Textbelt only
        sends links from domains it has approved.
        """
        rate(request, "texting-test", 5)
        try:
            send_text(
                db,
                texting.phone_number(body.phone),
                "Nära Hem: text messages from your household's server are working.",
            )
        except texting.TextingError as error:
            db.commit()
            # 424, not 502: tunnels and proxies such as Cloudflare replace a 502 with their own
            # error page, and the reason would never reach the screen.
            raise HTTPException(424, str(error)) from error
        db.commit()
        return {"sent": True, **texting_status(db)}

    class DeviceEmailRequest(Input):
        """The device requesting a first-device email code."""

        device_id: str = Field(pattern=r"^[a-f0-9]{32}$")

    @app.post("/api/device-bootstrap/email/request", status_code=202)
    def request_device_bootstrap_code(
        body: DeviceEmailRequest,
        request: Request,
        auth=Depends(admin),
        db: Session = Depends(database),
    ):
        """Emails the verified admin a short-lived code for registering the first device."""
        if not auth[0].verified:
            raise HTTPException(403, "Confirm the administrator email before enrolling a device")
        rate(request, "device-bootstrap-email", 3)
        rate(request, "device-bootstrap-email-all", 15, shared=True)
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        if state.revision != 0 or state.anchor:
            raise HTTPException(
                409, "First device was already initialized; approve from an existing trusted device"
            )
        dev = db.get(ClientDevice, body.device_id)
        if not dev or dev.account_id != auth[0].id or dev.status != "pending":
            raise HTTPException(404, "Pending administrator device not found")
        config = mail_settings(db)
        if not db.get(Settings, 1).mail_tested:
            raise HTTPException(409, "Test the administrator email configuration first")
        code = f"{secrets.randbelow(1000000):06d}"
        try:
            deliver(
                config,
                auth[0].email,
                "Nära Hem: approve first device",
                f"Your six-digit first-device code is {code}. It expires in 10 minutes.\n\n"
                "Only enter this code in the Nära Hem app on your own device. "
                "If you did not request it, change your account password.",
            )
        except (OSError, smtplib.SMTPException) as error:
            raise HTTPException(424, "Could not send device verification email") from error
        challenge = db.get(DeviceBootstrapChallenge, dev.id)
        if challenge:
            challenge.code_hash = bootstrap_email_hash(directory, dev.id, code)
            challenge.expires, challenge.attempts = time.time() + 600, 0
        else:
            db.add(
                DeviceBootstrapChallenge(
                    device_id=dev.id,
                    account_id=auth[0].id,
                    code_hash=bootstrap_email_hash(directory, dev.id, code),
                    expires=time.time() + 600,
                    attempts=0,
                )
            )
        db.commit()
        return {"sent": True, "expires_in": 600}

    @app.post("/api/mail/retry")
    def retry_mail(request: Request, auth=Depends(admin), db: Session = Depends(database)):
        """Retries every queued email immediately."""
        rate(request, "mail", 10)
        db.query(Outbox).filter_by(status="pending").update({Outbox.retry_at: 0})
        db.commit()
        result = flush_mail(db)
        result.pop("failed", None)
        return result
