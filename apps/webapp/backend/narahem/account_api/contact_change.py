"""Changing a signed-in account's email address or phone number, confirmed by a code sent to it."""

import hmac
import secrets
import smtplib
import time

from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from narahem import texting
from narahem.app import HASHER, contact, digest
from narahem.data_service import audit
from narahem.models import Account, ContactChange, Settings
from narahem.schemas import Input

CODE_MINUTES = 10


class ContactChangeInput(Input):
    """The new email address or phone number, and the account's password."""

    value: str = Field(min_length=3, max_length=254)
    password: str = Field(max_length=128)
    # Which one the app is changing; when given, the value must be that kind.
    kind: str | None = Field(default=None, pattern="^(email|phone)$")


class ContactCodeInput(Input):
    """The code sent to the new email address or phone number."""

    code: str = Field(pattern=r"^[0-9]{6}$")


def install(app, *, current, database, rate, deliver, mail_settings, send_text, texting_on, notice):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    def proof(account_id, kind, value, code):
        """Returns the stored form of a code, tied to the account and the new contact."""
        return digest(f"{account_id}:{kind}:{value}:{code}")

    def taken(db, account, kind, value):
        """Returns True if another account already uses this email address or phone number."""
        column = Account.email if kind == "email" else Account.phone
        return db.scalar(select(Account.id).where(column == value, Account.id != account.id))

    @app.post("/api/account/contact", status_code=202)
    def request_contact_change(
        body: ContactChangeInput,
        request: Request,
        auth=Depends(current),
        db: Session = Depends(database),
    ):
        """Sends a six-digit code to a new email address or phone number. Nothing changes until
        the code is entered.
        """
        account = auth[0]
        rate(request, "contact-change:" + account.id, 5, shared=True)
        try:
            valid = bool(account.password) and HASHER.verify(account.password, body.password)
        except VerificationError:
            valid = False
        if not valid:
            raise HTTPException(401, "Password not accepted")
        kind, value = contact(body.value)
        if body.kind and body.kind != kind:
            raise HTTPException(
                422, "Enter a phone number" if body.kind == "phone" else "Enter an email address"
            )
        if value == (account.email if kind == "email" else account.phone):
            raise HTTPException(
                409, f"That's already your {'email' if kind == 'email' else 'number'}"
            )
        if taken(db, account, kind, value):
            raise HTTPException(409, "Another account already uses that")
        settings = db.get(Settings, 1)
        if kind == "phone" and not texting_on(db):
            raise HTTPException(409, "This server doesn't have text messages set up")
        if kind == "email" and not (settings.smtp and settings.mail_tested):
            raise HTTPException(409, "This server doesn't have email set up")
        code = f"{secrets.randbelow(1000000):06d}"
        try:
            if kind == "email":
                deliver(
                    mail_settings(db),
                    value,
                    "Nära Hem: confirm your new email",
                    f"Enter {code} in Nära Hem to use this email address for your account.\n"
                    f"It expires in {CODE_MINUTES} minutes. If you didn't ask for this, ignore it.",
                )
            else:
                send_text(
                    db,
                    value,
                    f"Nära Hem code: {code}. Enter it to use this number for your account. "
                    f"It expires in {CODE_MINUTES} minutes.",
                )
        except (OSError, smtplib.SMTPException, texting.TextingError) as error:
            db.commit()
            raise HTTPException(502, "Could not send the code; check it and try again") from error
        row = db.get(ContactChange, account.id) or ContactChange(account_id=account.id)
        row.kind, row.value = kind, value
        row.code_hash = proof(account.id, kind, value, code)
        row.expires, row.attempts = time.time() + CODE_MINUTES * 60, 0
        db.merge(row)
        db.commit()
        return {"sent_to": kind, "to": value}

    @app.post("/api/account/contact/verify")
    def confirm_contact_change(
        body: ContactCodeInput,
        request: Request,
        auth=Depends(current),
        db: Session = Depends(database),
    ):
        """Applies the new email address or phone number once its code is entered, and tells
        the old one about the change.
        """
        account = auth[0]
        rate(request, "contact-verify:" + account.id, 10, shared=True)
        row = db.get(ContactChange, account.id)
        if not row or row.expires <= time.time():
            raise HTTPException(400, "That code has expired. Ask for a new one")
        row.attempts += 1
        if row.attempts > 5:
            db.delete(row)
            db.commit()
            raise HTTPException(429, "Too many tries. Ask for a new code")
        if not hmac.compare_digest(
            row.code_hash, proof(account.id, row.kind, row.value, body.code)
        ):
            db.commit()
            raise HTTPException(400, "That code isn't right")
        if taken(db, account, row.kind, row.value):
            db.delete(row)
            db.commit()
            raise HTTPException(409, "Another account already uses that")
        old = account.email if row.kind == "email" else account.phone
        if row.kind == "email":
            account.email = row.value
        else:
            account.phone = row.value
        db.delete(row)
        if old:
            what = "email address" if row.kind == "email" else "phone number"
            notice(
                db,
                "c:" + account.id,
                "email" if row.kind == "email" else "text",
                old,
                f"Nära Hem: your {what} was changed",
                f"Your Nära Hem account's {what} was changed from this one to {row.value}. "
                "If you didn't do this, contact your household administrator.",
            )
        audit(db, f"account.{row.kind}_changed", account.id, account.id)
        db.commit()
        return {"email": account.email, "phone": account.phone}
