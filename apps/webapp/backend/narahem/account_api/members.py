"""Accounts, household members, invitations and admin password resets."""

import json
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem.app import account_trusted, contact, digest, email_address
from narahem.models import (
    Account,
    Outbox,
    Settings,
)
from narahem.schemas import (
    InvitationInput,
    InvitationRequestInput,
)
from narahem.texting import phone_number


def install(
    app,
    *,
    admin,
    cipher,
    current,
    database,
    flush_mail,
    issue_password_reset,
    public_url,
    queue,
    rate,
    texting_on,
):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.get("/api/accounts")
    def accounts(auth=Depends(admin), db: Session = Depends(database)):
        """Returns every account for the admin's member list."""
        return [
            {
                "id": a.id,
                "email": a.email,
                "phone": a.phone,
                "username": a.username,
                "role": a.role,
                "status": a.status,
                "verified": account_trusted(a, db),
                "email_verified": a.verified,
            }
            for a in db.scalars(select(Account).order_by(Account.email))
        ]

    @app.get("/api/household/members")
    def household_members(auth=Depends(current), db: Session = Depends(database)):
        """Returns active members' IDs and names, the caller first. The administrator is listed
        only to themselves, so their own phone can show their own trips. Location data is never
        included.
        """
        if not account_trusted(auth[0], db):
            raise HTTPException(403, "Wait for account approval before viewing household members")
        others = db.scalars(
            select(Account)
            .where(Account.status == "active", Account.role != "admin", Account.id != auth[0].id)
            .order_by(Account.username)
        ).all()
        members = [auth[0], *others]
        return {
            "members": [
                {
                    "id": member.id,
                    "username": member.username or ("Me" if member.id == auth[0].id else "Member"),
                    "role": member.role,
                    "email": member.email if auth[0].role == "admin" else None,
                    "phone": member.phone if auth[0].role == "admin" else None,
                }
                for member in members
            ]
        }

    @app.post("/api/invitations", status_code=201)
    def invite(
        body: InvitationInput,
        request: Request,
        auth=Depends(admin),
        db: Session = Depends(database),
    ):
        """Invites someone by email, phone number or both. The invitation goes to each."""
        rate(request, "invite", 20)
        kind, value = contact(body.email)
        email = value if kind == "email" else None
        phone = value if kind == "phone" else None
        if body.phone and body.phone.strip():
            if phone:
                raise HTTPException(422, "Enter the email address first, then the phone number")
            phone = phone_number(body.phone)
        if phone and not texting_on(db):
            raise HTTPException(
                409, "Set up text messages in Admin settings to invite by phone number"
            )
        if (email and db.scalar(select(Account).where(Account.email == email))) or (
            phone and db.scalar(select(Account).where(Account.phone == phone))
        ):
            raise HTTPException(409, "Account already exists; use resend for pending accounts")
        account = Account(id=secrets.token_hex(16), email=email, phone=phone)
        db.add(account)
        db.flush()
        sent_to = queue(db, account)
        db.commit()
        if not sent_to:
            return {"invited": True, "channels": sent_to, "delivery": "not_requested"}
        result = flush_mail(db)
        # Only this invitation's problems, e.g. Textbelt refusing the text, for the invite screen.
        problems = result.pop("failed", {}).get(account.id, {})
        return {"invited": True, "channels": sent_to, **result, "problems": problems}

    @app.post("/api/invitation-requests", status_code=202)
    def request_invitation(
        body: InvitationRequestInput, request: Request, db: Session = Depends(database)
    ):
        """Records a request from someone without an account to be invited, and emails the admin."""
        rate(request, "invitation-request", 3)
        rate(request, "invitation-request-global", 20, shared=True)
        address = email_address(body.email)
        name, relationship = body.name.strip(), body.relationship.strip()
        if not name or not relationship:
            raise HTTPException(422, "Enter your name and how you know the household")
        settings = db.get(Settings, 1)
        owner = db.scalar(
            select(Account).where(Account.role == "admin", Account.status == "active")
        )
        if not settings.household or not settings.smtp or not owner or not owner.verified:
            raise HTTPException(
                503,
                "This server is not ready to receive invitation requests. Contact the household "
                "administrator",
            )
        request_id = "req-" + digest(address)[:32]
        if not db.scalar(
            select(Outbox.id).where(
                Outbox.account_id == request_id, Outbox.created > time.time() - 900
            )
        ):
            payload = {
                "recipient": owner.email,
                "subject": "Nära Hem: invitation request",
                "body": (
                    f"A person has requested an invitation. These details are self-reported, not "
                    f"independently verified.\n\nName: {name}\nEmail: {address}\nHow they know "
                    f"you: {relationship}\n\nReview this request and use the member invitation "
                    f"form at {public_url}/ if you recognize them. No account or device access has "
                    f"been granted."
                ),
            }
            db.add(
                Outbox(
                    id=secrets.token_hex(16),
                    account_id=request_id,
                    payload=cipher.encrypt(json.dumps(payload).encode()).decode(),
                    created=time.time(),
                )
            )
            db.commit()
        return {
            "message": (
                "Your request has been queued for the administrator. You will receive an "
                "invitation if they approve it"
            )
        }

    @app.post("/api/accounts/{account_id}/invitation", status_code=202)
    def resend_invitation(
        account_id: str, request: Request, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Sends a pending member their invitation again: the email link and the text."""
        rate(request, "invite", 20)
        account = db.get(Account, account_id)
        if not account or account.status != "pending":
            raise HTTPException(404, "No pending invitation for this member")
        sent_to = queue(db, account)
        db.commit()
        if not sent_to:
            raise HTTPException(409, "Set up email or text messages to send invitations")
        result = flush_mail(db)
        problems = result.pop("failed", {}).get(account.id, {})
        return {"channels": sent_to, **result, "problems": problems}

    @app.post("/api/accounts/{account_id}/password-reset", status_code=202)
    def admin_send_password_reset(
        account_id: str, request: Request, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Sends a member a password reset email at the admin's request."""
        rate(request, "admin-password-reset", 8)
        account = db.get(Account, account_id)
        if not account or account.role == "admin":
            raise HTTPException(404, "Household member not found")
        if not issue_password_reset(db, account):
            raise HTTPException(
                409, "Member has no active mailbox/password or email is not configured"
            )
        db.commit()
        return {"queued": True}
