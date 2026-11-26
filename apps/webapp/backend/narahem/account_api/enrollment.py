"""Invitation enrollment: claims, requests and email verification."""

import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session

from narahem import review_mode
from narahem.app import HASHER, account_trusted, contact, digest, find_account, username
from narahem.data_service import audit
from narahem.models import (
    Account,
    AccountApproval,
    Challenge,
    ClientDevice,
    EnrollmentClaim,
    LoginSession,
    NativeRefreshSession,
    Outbox,
    PhoneChallenge,
    ServiceState,
)
from narahem.schemas import (
    AccountRegistrationInput,
    ClaimInput,
    EmailInput,
    VerifyInput,
)


def install(app, *, admin, database, queue, rate):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.post("/api/enrollment/claim", status_code=202)
    def claim_invitation(body: ClaimInput, request: Request, db: Session = Depends(database)):
        """Legacy endpoint. Always returns 410, directing older apps to the email link."""
        raise HTTPException(
            410, "Use the invitation email link; no second administrator approval is required."
        )

    @app.get("/api/enrollment/claims")
    def enrollment_claims(auth=Depends(admin), db: Session = Depends(database)):
        """Returns pending join requests."""
        rows = db.scalars(
            select(EnrollmentClaim)
            .where(EnrollmentClaim.expires > time.time())
            .order_by(EnrollmentClaim.created)
        )
        return {
            "claims": [
                {
                    "id": row.id,
                    "account_id": row.account_id,
                    "username": row.username,
                    "email": db.get(Account, row.account_id).email,
                    "created": row.created,
                }
                for row in rows
                if db.get(Account, row.account_id)
            ]
        }

    @app.post("/api/enrollment/claims/{claim_id}/approve")
    def approve_claim(claim_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Approves a join request and emails the person their enrollment link."""
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        claim = db.get(EnrollmentClaim, claim_id)
        if not claim or claim.expires <= time.time():
            raise HTTPException(404, "Setup request expired or was removed")
        account = db.execute(
            select(Account).where(Account.id == claim.account_id).with_for_update()
        ).scalar_one_or_none()
        if (
            not account
            or account.status != "pending"
            or account.password
            or account.role == "admin"
        ):
            raise HTTPException(409, "Account is no longer awaiting setup")
        if db.scalar(select(Account).where(Account.username == claim.username)):
            raise HTTPException(
                409, "Username unavailable; reject this request and have the member choose another"
            )
        account.username, account.password, account.status = (
            claim.username,
            claim.password_hash,
            "active",
        )
        db.add(AccountApproval(account_id=account.id, approved_by=auth[0].id, created=time.time()))
        db.query(EnrollmentClaim).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(Challenge).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(Outbox).filter_by(account_id=account.id, status="pending").update(
            {Outbox.status: "expired", Outbox.payload: ""}
        )

        audit(db, "account.approved", auth[0].id, account.id, verification="administrator")
        db.commit()
        return {"approved": True, "device_approval_required": True}

    @app.delete("/api/enrollment/claims/{claim_id}")
    def reject_claim(claim_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Deletes a join request."""
        row = db.get(EnrollmentClaim, claim_id)
        if row:
            db.delete(row)
        db.commit()
        return {"removed": True}

    @app.post("/api/enrollment/request", status_code=202)
    def request_enrollment(body: EmailInput, request: Request, db: Session = Depends(database)):
        """Sends the invitation again to an invited email address or phone number. Returns the
        same response whether or not it exists.
        """
        rate(request, "enrollment", 5)
        account = find_account(db, body.email)
        if (
            account
            and account.status != "revoked"
            and (account.status == "pending" or not account.verified)
        ):
            queue(db, account)
            db.commit()
        return {"message": "If eligible, a confirmation link will be sent."}

    @app.post("/api/enrollment/register", status_code=201)
    def register(body: AccountRegistrationInput, request: Request, db: Session = Depends(database)):
        """Creates the account for an open invitation from the app: the invited email address
        or phone number, a username and a password. The account can sign in but stays
        unconfirmed, seeing nothing of the household, until the code sent to that address or
        number approves its phone. Until then, registering again replaces it, so knowing someone's
        number isn't enough to lock them out.
        """
        rate(request, "register-account", 5)
        account = find_account(db, body.email)
        if not account and review_mode.open_signup():
            # An open demo server lets anyone in without an invitation, except under an address
            # on the review list, which only the administrator can invite.
            kind, value = contact(body.email)
            account = Account(
                id=secrets.token_hex(16),
                email=value if kind == "email" else None,
                phone=value if kind == "phone" else None,
            )
            if review_mode.listed(account):
                account = None
            else:
                db.add(account)
                db.flush()
        if not account or not replaceable(db, account):
            raise HTTPException(
                404,
                "There's no open invitation for that email or phone number. Ask your household "
                "administrator to invite you.",
            )
        chosen = username(body.username)
        if db.scalar(
            select(Account).where(
                func.lower(Account.username) == chosen.lower(), Account.id != account.id
            )
        ):
            raise HTTPException(409, "Username already taken")
        # Whoever registered before loses their sign-in and unfinished phones.
        db.query(LoginSession).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(NativeRefreshSession).filter_by(account_id=account.id).delete(
            synchronize_session=False
        )
        for device in db.scalars(
            select(ClientDevice).where(
                ClientDevice.account_id == account.id, ClientDevice.status == "pending"
            )
        ):
            db.query(PhoneChallenge).filter_by(device_id=device.id).delete()
            db.delete(device)
        account.username, account.password = chosen, HASHER.hash(body.password)
        account.status, account.verified = "active", False
        db.query(Challenge).filter_by(account_id=account.id).delete(synchronize_session=False)
        audit(db, "account.registered", account.id)
        db.commit()
        return {"registered": True, "confirmation": "phone_code"}

    def replaceable(db, account):
        """Returns True if the account is an open invitation: never set up, or registered from
        the app but not yet confirmed with a code and without any approved device.
        """
        if account.role == "admin" or account.status == "revoked":
            return False
        if account.status == "pending":
            return True
        return (
            account.status == "active"
            and not account_trusted(account, db)
            and not db.scalar(
                select(ClientDevice.id).where(
                    ClientDevice.account_id == account.id, ClientDevice.status != "pending"
                )
            )
        )

    @app.post("/api/enrollment/verify")
    def verify(body: VerifyInput, request: Request, db: Session = Depends(database)):
        """Handles an email verification link: confirms the address and, for new members, sets
        the username and password.
        """
        rate(request, "verify", 10)
        challenge = db.execute(
            select(Challenge).where(Challenge.id == digest(body.token)).with_for_update()
        ).scalar_one_or_none()
        if not challenge or challenge.used or challenge.expires <= time.time():
            raise HTTPException(400, "Confirmation link is invalid or expired")
        account = db.execute(
            select(Account).where(Account.id == challenge.account_id).with_for_update()
        ).scalar_one()
        if account.status == "revoked":
            raise HTTPException(400, "Confirmation link is invalid or expired")
        if account.status == "pending":
            if not body.password:
                raise HTTPException(422, "Choose and confirm a password")
            if not body.username:
                raise HTTPException(422, "Choose a username")
            chosen = username(body.username)
            collision = db.scalar(
                select(Account).where(
                    func.lower(Account.username) == chosen.lower(), Account.id != account.id
                )
            )
            if collision:
                raise HTTPException(409, "Username already taken")
            account.username, account.password, account.status = (
                chosen,
                HASHER.hash(body.password),
                "active",
            )
        # Existing accounts only confirm their email here; this never sets a password.
        account.verified, challenge.used = True, True
        db.commit()
        return {
            "verified": True,
            "device_approval_required": False,
            "phone_email_verification_required": True,
        }
