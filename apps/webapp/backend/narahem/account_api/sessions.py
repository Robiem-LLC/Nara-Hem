"""Password reset, sign-in, phone sessions, username and sign-out."""

import secrets
import time

from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session

from narahem.app import (
    DUMMY_HASH,
    HASHER,
    REFRESH_REUSE_GRACE_SECONDS,
    account_trusted,
    contact,
    digest,
    find_account,
    username,
)
from narahem.data_service import audit
from narahem.models import (
    Account,
    LoginSession,
    NativeRefreshSession,
    Outbox,
    PasswordReset,
    RetiredNativeRefresh,
)
from narahem.schemas import (
    ChangeUsernameInput,
    EmailInput,
    LoginInput,
    NativeRefreshInput,
    ResetPasswordInput,
)


def install(app, *, current, database, issue_password_reset, login_guard, login_outcome, rate, url):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.post("/api/password/forgot", status_code=202)
    def forgot_password(body: EmailInput, request: Request, db: Session = Depends(database)):
        """Emails a password reset link if the account exists. The response is the same either
        way.
        """
        rate(request, "password-forgot", 5)
        rate(request, "password-forgot-global", 40, shared=True)
        rate(request, "password-forgot:" + digest(body.email.strip().lower()), 3, shared=True)
        account = find_account(db, body.email)
        if issue_password_reset(db, account):
            db.commit()
        return {
            "message": (
                "If this account has recovery email available, a reset link will be sent shortly."
            )
        }

    @app.post("/api/password/reset")
    def reset_password(body: ResetPasswordInput, request: Request, db: Session = Depends(database)):
        """Sets a new password from a reset token and ends every session."""
        rate(request, "password-reset", 10)
        row = db.execute(
            select(PasswordReset).where(PasswordReset.id == digest(body.token)).with_for_update()
        ).scalar_one_or_none()
        if not row or row.expires <= time.time():
            raise HTTPException(400, "Password reset link is invalid or expired")
        account = db.execute(
            select(Account).where(Account.id == row.account_id).with_for_update()
        ).scalar_one_or_none()
        if not account or account.status != "active":
            raise HTTPException(400, "Password reset link is invalid or expired")
        account.password = HASHER.hash(body.new_password)
        db.query(PasswordReset).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(Outbox).filter_by(account_id="r:" + account.id, status="pending").update(
            {Outbox.status: "expired", Outbox.payload: ""}
        )
        db.query(LoginSession).filter_by(account_id=account.id).delete(synchronize_session=False)
        db.query(NativeRefreshSession).filter_by(account_id=account.id).delete(
            synchronize_session=False
        )
        db.commit()
        return {"changed": True, "other_sessions_signed_out": True}

    @app.post("/api/login")
    def login(
        body: LoginInput, request: Request, response: Response, db: Session = Depends(database)
    ):
        """Signs in with an email address or phone number and a password, with per-account
        backoff after failures. Phone apps also receive a refresh token.
        """
        address = contact(body.email)[1]
        login_guard(address)
        account = find_account(db, address)
        try:
            valid = HASHER.verify(
                account.password if account and account.password else DUMMY_HASH, body.password
            )
        except VerificationError:
            valid = False
        if not valid or not account or account.status != "active":
            login_outcome(address, False)
            raise HTTPException(401, "Email or password not accepted")
        login_outcome(address, True)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32) if body.native else None
        now = time.time()
        db.query(LoginSession).filter(LoginSession.expires < now).delete()
        db.query(NativeRefreshSession).filter(NativeRefreshSession.expires < now).delete()
        db.add(
            LoginSession(id=digest(token), account_id=account.id, csrf=csrf, expires=now + 43200)
        )
        if refresh_token:
            db.add(
                NativeRefreshSession(
                    id=digest(refresh_token), account_id=account.id, expires=now + 90 * 86400
                )
            )
        db.commit()
        response.set_cookie(
            "narahem_session",
            token,
            httponly=True,
            secure=url.scheme == "https",
            samesite="strict",
            max_age=43200,
            path="/",
        )
        return {
            "csrf": csrf,
            **(
                {"access_token": token, "refresh_token": refresh_token, "expires_in": 43200}
                if body.native
                else {}
            ),
        }

    @app.post("/api/native/session/refresh")
    def native_session_refresh(
        body: NativeRefreshInput, request: Request, db: Session = Depends(database)
    ):
        """Exchanges a phone's refresh token for a new access token and refresh token. Reuse of
        an old token ends every phone session for the account.
        """
        # No IP limit: tokens are 256-bit random, and behind a proxy an IP limit would let anyone
        # block every phone's refresh.
        old_hash = digest(body.refresh_token)
        grant = db.execute(
            select(NativeRefreshSession)
            .where(NativeRefreshSession.id == old_hash)
            .with_for_update()
        ).scalar_one_or_none()
        account = db.get(Account, grant.account_id) if grant else None
        now = time.time()
        if not grant:
            retired = db.get(RetiredNativeRefresh, old_hash)
            if (
                retired
                and retired.expires > now
                and now - retired.retired > REFRESH_REUSE_GRACE_SECONDS
            ):
                # A rotated token was reused, so a copy was stolen: end every phone session for the
                # account. Device keys are unaffected.
                db.query(NativeRefreshSession).filter_by(account_id=retired.account_id).delete(
                    synchronize_session=False
                )
                db.query(RetiredNativeRefresh).filter_by(account_id=retired.account_id).delete(
                    synchronize_session=False
                )

                audit(db, "session.refresh_reuse", retired.account_id, retired.account_id)
                db.commit()
            raise HTTPException(401, "Remembered sign-in is no longer valid")
        if grant.expires <= now or not account or account.status != "active":
            raise HTTPException(401, "Remembered sign-in is no longer valid")
        next_token = secrets.token_urlsafe(32)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.query(RetiredNativeRefresh).filter(RetiredNativeRefresh.expires < now).delete(
            synchronize_session=False
        )
        db.add(
            RetiredNativeRefresh(
                id=old_hash, account_id=account.id, retired=now, expires=grant.expires
            )
        )
        grant.id = digest(next_token)
        grant.expires = now + 90 * 86400
        db.add(
            LoginSession(id=digest(token), account_id=account.id, csrf=csrf, expires=now + 43200)
        )
        db.commit()
        return {"access_token": token, "refresh_token": next_token, "expires_in": 43200}

    @app.post("/api/native/session/revoke")
    def native_session_revoke(body: NativeRefreshInput, db: Session = Depends(database)):
        """Revokes a phone's refresh token, even if its access token has expired."""
        row = db.get(NativeRefreshSession, digest(body.refresh_token))
        if row:
            db.delete(row)
            db.commit()
        return {"signed_out": True}

    @app.get("/api/session")
    def session(auth=Depends(current), db: Session = Depends(database)):
        """Returns the signed-in account."""
        return {
            "id": auth[0].id,
            "email": auth[0].email,
            "phone": auth[0].phone,
            "username": auth[0].username,
            "role": auth[0].role,
            "verified": account_trusted(auth[0], db),
            "email_verified": auth[0].verified,
            "csrf": auth[1].csrf,
        }

    @app.put("/api/account/username")
    def change_username(
        body: ChangeUsernameInput, auth=Depends(current), db: Session = Depends(database)
    ):
        """Changes a member's display name. Not available to the admin, who has no display name."""
        if auth[0].role == "admin":
            raise HTTPException(403, "Server administrator has no household username")
        chosen = username(body.username.strip())
        collision = db.scalar(
            select(Account).where(
                func.lower(Account.username) == chosen.lower(), Account.id != auth[0].id
            )
        )
        if collision:
            raise HTTPException(409, "Username already taken")
        auth[0].username = chosen
        db.commit()
        return {"username": chosen}

    @app.post("/api/logout")
    def logout(response: Response, auth=Depends(current), db: Session = Depends(database)):
        """Ends this browser session."""
        db.delete(auth[1])
        db.commit()
        response.delete_cookie("narahem_session", path="/")
        return {"signed_out": True}
