"""Revoking, restoring and deleting accounts."""

from fastapi import Depends, HTTPException
from sqlalchemy import (
    select,
)
from sqlalchemy.orm import Session

from narahem.app import account_trusted, digest
from narahem.data_service import (
    audit,
    purge_account_data,
    revoke_account_data,
)
from narahem.models import (
    Account,
    AccountApproval,
    Challenge,
    DeviceBootstrapChallenge,
    EnrollmentClaim,
    LoginSession,
    NativeRefreshSession,
    Outbox,
    PasswordReset,
    RetiredNativeRefresh,
    ServiceState,
)


def install(app, *, admin, database):
    """Registers this module's routes. The keyword arguments are shared helpers from
    create_app().
    """

    @app.post("/api/accounts/{account_id}/revoke")
    def revoke(account_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Revokes an account and permanently revokes all its devices."""
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        account = db.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        if account.role == "admin":
            raise HTTPException(409, "Owner revocation is not supported")
        revoke_account_data(db, account_id, auth[0].id)
        account.status = "revoked"
        db.query(LoginSession).filter_by(account_id=account_id).delete()
        db.query(NativeRefreshSession).filter_by(account_id=account_id).delete()
        db.query(Challenge).filter_by(account_id=account_id).delete()
        db.query(Outbox).filter_by(account_id=account_id, status="pending").update(
            {Outbox.status: "expired", Outbox.payload: ""}
        )
        db.commit()
        return {"revoked": True}

    @app.post("/api/accounts/{account_id}/restore")
    def restore_revoked_account(
        account_id: str, auth=Depends(admin), db: Session = Depends(database)
    ):
        """Restores sign-in for a revoked account. Revoked devices and sessions stay invalid; new
        phones must enroll with new keys and an email code.
        """

        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        account = db.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        ).scalar_one_or_none()
        if not account or account.role == "admin":
            raise HTTPException(404, "Household member not found")
        if account.status != "revoked":
            raise HTTPException(409, "Only revoked accounts may be restored")
        if not account.password or not account_trusted(account, db):
            raise HTTPException(409, "Member account requires normal invitation or verification")
        account.status = "active"
        audit(db, "account.restored", auth[0].id, account.id)
        db.commit()
        return {"restored": True, "phones_remain_revoked": True}

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: str, auth=Depends(admin), db: Session = Depends(database)):
        """Deletes an account with its location, event and profile data. Saved places are kept."""
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        account = db.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        if account.role == "admin":
            raise HTTPException(409, "Owner deletion is not supported")
        result = purge_account_data(db, account_id, auth[0].id)
        db.query(NativeRefreshSession).filter_by(account_id=account_id).delete()
        db.query(RetiredNativeRefresh).filter_by(account_id=account_id).delete()
        db.query(LoginSession).filter_by(account_id=account_id).delete()
        db.query(Challenge).filter_by(account_id=account_id).delete()
        request_id = "req-" + digest(account.email or account.phone or "")[:32]
        db.query(Outbox).filter(Outbox.account_id.in_([account_id, request_id])).delete(
            synchronize_session=False
        )
        db.query(DeviceBootstrapChallenge).filter_by(account_id=account_id).delete()
        db.query(EnrollmentClaim).filter_by(account_id=account_id).delete(synchronize_session=False)
        db.query(PasswordReset).filter_by(account_id=account_id).delete(synchronize_session=False)
        db.query(Outbox).filter_by(account_id="r:" + account_id).delete(synchronize_session=False)
        db.query(Outbox).filter_by(account_id="p:" + account_id).delete(synchronize_session=False)
        db.query(AccountApproval).filter_by(account_id=account_id).delete(synchronize_session=False)
        db.delete(account)
        db.commit()
        return {"deleted": True, **result}
