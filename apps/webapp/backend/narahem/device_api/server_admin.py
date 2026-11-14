"""Storage, retention, diagnostics, logs and the audit trail."""

import json
import time
from typing import Literal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import Field
from sqlalchemy import (
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from narahem.data_service import DAY, audit, prune
from narahem.diagnostics_cli import export_dir, render_report, report_name, save_export
from narahem.models import (
    Account,
    AuditEntry,
    ClientDevice,
    DiagnosticEntry,
    EncryptedRecord,
    PushDelivery,
    ServiceState,
)
from narahem.schemas import (
    Input,
    RetentionInput,
)


def install(app, *, admin, database, quota, visible_query):
    """Registers this module's routes. The keyword arguments are shared helpers from
    device_api.install().
    """

    @app.get("/api/storage")
    def storage(auth=Depends(admin), db: Session = Depends(database)):
        """Returns encrypted storage use and the quota."""
        state = db.get(ServiceState, 1)
        count, size = db.execute(
            select(
                func.count(EncryptedRecord.id), func.coalesce(func.sum(EncryptedRecord.bytes), 0)
            )
        ).one()

        return {
            "retention_days": state.retention_days,
            "records": count,
            "bytes": size,
            "quota_bytes": quota,
            "last_cleanup": state.last_cleanup,
            "pending_push": db.query(PushDelivery).count(),
            "persistent_kinds": ["place", "profile"],
            "exports_available": export_dir() is not None,
        }

    @app.put("/api/storage/retention")
    def retention(body: RetentionInput, auth=Depends(admin), db: Session = Depends(database)):
        """Sets the retention period and prunes immediately."""
        state = db.execute(
            select(ServiceState).where(ServiceState.id == 1).with_for_update()
        ).scalar_one()
        before = state.retention_days
        state.retention_days = body.days
        db.query(EncryptedRecord).filter(EncryptedRecord.kind.in_(["location", "event"])).update(
            {EncryptedRecord.expires_at: EncryptedRecord.captured_at / 1000 + body.days * DAY},
            synchronize_session=False,
        )
        db.query(PushDelivery).filter(PushDelivery.created <= time.time() - body.days * DAY).delete(
            synchronize_session=False
        )
        audit(db, "retention.changed", auth[0].id, before_days=before, after_days=body.days)
        db.commit()
        prune(db)
        return {"days": body.days}

    @app.post("/api/storage/cleanup")
    def cleanup(auth=Depends(admin), db: Session = Depends(database)):
        """Runs retention cleanup."""
        prune(db)
        return {"cleaned": True}

    @app.get("/api/admin/diagnostics")
    def download_diagnostics(
        category: str = Query("gps", pattern="^(all|gps|trips|notifications|accounts|server)$"),
        hours: int = Query(3, ge=1, le=336),
        sub: str = Query("all", pattern="^(all|roads|normalization|finalization)$"),
        auth=Depends(admin),
    ):
        """Returns a redacted diagnostics report as a download. Never includes keys, database
        files, queued records or arbitrary paths.
        """

        report = render_report(category, sub, hours, app.state)
        filename = f"narahem-{category}-{hours}h.txt"
        return PlainTextResponse(
            report,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    class DiagnosticExportInput(Input):
        """Category and time range for a diagnostics export."""

        category: Literal["all", "gps", "trips", "notifications", "accounts", "server"] = "gps"
        hours: int = Field(default=3, ge=1, le=336)

    @app.post("/api/admin/diagnostics/export", status_code=201)
    def export_diagnostics(body: DiagnosticExportInput, auth=Depends(admin)):
        """Saves the redacted diagnostics report to the exports folder."""

        try:
            output = save_export(
                render_report(body.category, "all", body.hours, app.state),
                report_name(body.category, body.hours),
            )
        except FileNotFoundError as error:
            raise HTTPException(409, "No exports folder is mounted at /exports") from error
        except FileExistsError as error:
            raise HTTPException(409, "A report with this name was just saved; try again") from error
        return {"saved": output.name}

    @app.get("/api/logs")
    def logs(
        start: float | None = None,
        end: float | None = None,
        category: str = "all",
        actor: str | None = None,
        user: str | None = None,
        device: str | None = None,
        outcome: str = "all",
        offset: int = 0,
        limit: int = 100,
        auth=Depends(admin),
        db: Session = Depends(database),
    ):
        """Returns the admin log view: diagnostics and record metadata, never decrypted contents."""
        now = time.time()
        start = max(start if start is not None else now - 14 * DAY, now - 14 * DAY)
        end = min(end if end is not None else now, now)
        if start > end or not 0 <= offset <= 20000 or not 1 <= limit <= 100:
            raise HTTPException(422, "Invalid time range or page")
        accounts = {a.id: a.username or a.email or a.phone for a in db.scalars(select(Account))}
        admin_ids = {a.id for a in db.scalars(select(Account).where(Account.role == "admin"))}
        devices = {d.id: d for d in db.scalars(select(ClientDevice))}

        def device_name(device):
            """Returns a display name for a device in the logs."""
            return (
                "Admin"
                if device.account_id in admin_ids and device.name == "My browser"
                else device.name
            )

        def name(ident):
            """Returns a display name for an account or device ID in the logs."""
            return (
                accounts.get(
                    ident,
                    device_name(devices[ident]) if ident in devices else "Former/unknown identity",
                )
                if ident
                else None
            )

        audit_details = {
            json.loads(e.details).get("audit_id"): json.loads(e.details)
            for e in db.scalars(
                select(DiagnosticEntry).where(
                    DiagnosticEntry.category == "administration",
                    DiagnosticEntry.created >= start,
                    DiagnosticEntry.created <= end,
                )
            )
        }
        entries = []
        if category in ("all", "administration") and outcome in ("all", "ok"):
            q = select(AuditEntry).where(AuditEntry.created >= start, AuditEntry.created <= end)
            if actor:
                q = q.where(AuditEntry.actor_id == actor)
            if user:
                owned = [d.id for d in devices.values() if d.account_id == user]
                q = q.where(
                    or_(AuditEntry.actor_id == user, AuditEntry.target_id.in_([user, *owned]))
                )
            if device:
                q = q.where(AuditEntry.target_id == device)
            q = q.order_by(AuditEntry.created.desc(), AuditEntry.id.desc()).limit(
                offset + limit + 1
            )
            for e in db.scalars(q):
                entries.append(
                    dict(
                        id=e.id,
                        category="administration",
                        action=e.action,
                        created=e.created,
                        actor_id=e.actor_id,
                        actor=name(e.actor_id),
                        target_id=e.target_id,
                        target=name(e.target_id),
                        outcome="ok",
                        details=audit_details.get(
                            e.id, {"source": "server audit", "target_id": e.target_id}
                        ),
                    )
                )
        # Record metadata is listed even when diagnostics are off. Never return decrypted contents.
        for record_kind, record_category in (("location", "gps"), ("event", "events")):
            if category not in ("all", record_category) or outcome not in ("all", "ok"):
                continue
            q = visible_query(db).where(
                EncryptedRecord.kind == record_kind,
                EncryptedRecord.received_at >= start,
                EncryptedRecord.received_at <= end,
            )
            if actor:
                q = q.where(EncryptedRecord.account_id == actor)
            if user:
                q = q.where(EncryptedRecord.account_id == user)
            if device:
                q = q.where(EncryptedRecord.device_id == device)
            q = q.order_by(EncryptedRecord.received_at.desc(), EncryptedRecord.id.desc()).limit(
                offset + limit + 1
            )
            for record in db.scalars(q):
                entries.append(
                    dict(
                        id=record.id,
                        category=record_category,
                        action="record.received",
                        created=record.received_at,
                        actor_id=record.account_id,
                        actor=name(record.account_id),
                        target_id=record.device_id,
                        target=name(record.device_id),
                        outcome="ok",
                        details=dict(
                            source="server retained encrypted history",
                            kind=record_kind,
                            record_id=record.id,
                            captured_at=record.captured_at,
                            received_at=record.received_at,
                            upload_delay_ms=max(
                                0, int(record.received_at * 1000) - record.captured_at
                            ),
                            recovery="unknown",
                        ),
                    )
                )
        if not actor:
            q = select(DiagnosticEntry).where(
                DiagnosticEntry.created >= start,
                DiagnosticEntry.created <= end,
                DiagnosticEntry.category != "administration",
                ~and_(
                    DiagnosticEntry.category == "gps", DiagnosticEntry.action == "record.received"
                ),
            )
            if category != "all":
                q = q.where(DiagnosticEntry.category == category)
            if user:
                q = q.where(DiagnosticEntry.account_id == user)
            if device:
                q = q.where(DiagnosticEntry.device_id == device)
            if outcome != "all":
                q = q.where(DiagnosticEntry.outcome == outcome)
            q = q.order_by(DiagnosticEntry.created.desc(), DiagnosticEntry.id.desc()).limit(
                offset + limit + 1
            )
            for e in db.scalars(q):
                entries.append(
                    dict(
                        id=e.id,
                        category=e.category,
                        action=e.action,
                        created=e.created,
                        actor_id=e.account_id,
                        actor=name(e.account_id),
                        target_id=e.device_id,
                        target=name(e.device_id),
                        outcome=e.outcome,
                        details=json.loads(e.details),
                    )
                )
        entries.sort(key=lambda e: (e["created"], e["id"]), reverse=True)
        return {
            "entries": entries[offset : offset + limit],
            "next_offset": offset + limit if len(entries) > offset + limit else None,
            "retention_days": 14,
            "diagnostic_row_limit": 20000,
            "users": [{"id": k, "name": v} for k, v in accounts.items()],
            "devices": [
                {"id": d.id, "name": device_name(d), "account_id": d.account_id}
                for d in devices.values()
                if d.status != "revoked"
            ],
            "notification_note": (
                "The server decides arrival/departure alerts. Provider acceptance is not confirmed "
                "delivery."
            ),
        }

    @app.get("/api/audit")
    def audit_log(auth=Depends(admin), db: Session = Depends(database)):
        """Returns the latest audit entries."""
        return [
            {
                "action": e.action,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "created": e.created,
            }
            for e in db.scalars(
                select(AuditEntry)
                .where(AuditEntry.created > time.time() - 14 * DAY)
                .order_by(AuditEntry.created.desc())
                .limit(100)
            )
        ]
