"""Local-only diagnostic export. Never include GPS coordinates, bearer tokens,
email addresses, provider credentials, or raw encrypted record envelopes."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from narahem.app import create_app
from narahem.models import ClientDevice, DiagnosticEntry, EncryptedRecord, IndexedTrip

CATEGORY = {
    "1": "all",
    "2": "trips",
    "3": "gps",
    "4": "notifications",
    "5": "accounts",
    "6": "server",
}
SUB = {"1": "all", "2": "roads", "3": "normalization", "4": "finalization"}
DIAGNOSTIC_CATEGORY = {
    "trips": {"trip"},
    "gps": {"gps", "communication", "incoming"},
    "notifications": {"notification"},
    "accounts": {"administration"},
    "server": {"server"},
}
SAFE_FIELDS = {
    "reason",
    "stage",
    "provider",
    "attempt",
    "attempts",
    "http_status",
    "accepted_points",
    "received_points",
    "rejected_points",
    "distance_m",
    "duration_ms",
    "matched",
    "partial",
    "processing",
    "status",
    "region",
    "retry_after_seconds",
    "confidence",
    "limit",
    "upload_delay_ms",
    "contact_gap_seconds",
    "pending_before",
    "pending_after",
    "acknowledged",
    "dropped",
    "gap_ms",
    "source",
    "error_type",
    "original_points",
    "usable_points",
    "outcome",
}
STAGE = {
    "roads": {"trip.roads", "trip.road_match"},
    "normalization": {"trip.normalization"},
    "finalization": {"trip.summary", "trip.finalization"},
}

EXPORT_KEEP_FILES = 100
EXPORT_MAX_AGE = 30 * 86400


def export_dir():
    """Returns the readable folder for exported reports, separate from the private /data volume."""
    path = Path(os.environ.get("NARAHEM_EXPORT_DIR", "/exports"))
    if path.is_dir() and not path.is_symlink() and os.access(path, os.W_OK | os.X_OK):
        return path
    return None


def save_export(report, name):
    """Writes a report as a world-readable file and deletes old reports."""
    target = export_dir()
    if target is None:
        raise FileNotFoundError("No writable exports folder is mounted")
    if Path(name).name != name or not name.startswith("narahem-") or not name.endswith(".txt"):
        raise ValueError("Unexpected report name")
    output = target / name
    with output.open("x", encoding="utf-8") as f:
        f.write(report)
    output.chmod(0o644)
    reports = sorted(
        (p for p in target.glob("narahem-*.txt") if p.is_file() and not p.is_symlink()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - EXPORT_MAX_AGE
    for index, old in enumerate(reports):
        if index >= EXPORT_KEEP_FILES or old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return output


def report_name(category, hours):
    """Returns the file name for a report."""
    return (
        "narahem-"
        + category
        + "-"
        + str(hours)
        + "h-"
        + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        + ".txt"
    )


def utc(timestamp):
    """Formats a Unix timestamp as an ISO 8601 UTC string."""
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat()


def anon(identifier):
    """Returns a short, stable pseudonym for an ID."""
    if not identifier:
        return "-"
    return hashlib.sha256(str(identifier).encode()).hexdigest()[:10]


def render_report(category, sub, hours, state):
    """Builds a redacted diagnostics report. Used by both the CLI and the admin download; never
    includes coordinates, device secrets or record contents.
    """
    if category not in set(DIAGNOSTIC_CATEGORY) | {"all"}:
        raise ValueError("Unsupported diagnostic category")
    if sub not in set(STAGE) | {"all"} or not 1 <= hours <= 336:
        raise ValueError("Unsupported diagnostic window")

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    lines = [
        "NARAHEM SUPPORT DIAGNOSTICS (redacted, local export)",
        "Generated UTC: " + utc(now),
        "Category: " + category + (", stage: " + sub if category == "trips" else ""),
        "Window: " + str(hours) + " hours",
        "Trusted trip processing enabled: " + str(state.trip_processor is not None),
        "Road matching enabled: " + str(bool(state.trip_processor and state.trip_processor.roads)),
        "Notes: Only events that were previously recorded are present.",
        "Coordinates, access tokens, passwords, phone numbers and raw payloads are omitted.",
        "",
    ]
    with Session(state.engine) as db:
        if category in ("all", "trips"):
            counts = db.execute(
                select(IndexedTrip.status, func.count()).group_by(IndexedTrip.status)
            ).all()
            lines.append(
                "Trip processing status totals: " + json.dumps(dict(counts), sort_keys=True)
            )
            # Aggregate counts only; never export route locations.
            quality = {
                "road_matched": 0,
                "gps_normalized_only": 0,
                "no_processed_route": 0,
                "unreadable": 0,
            }
            cutoff_ms = int((now - hours * 3600) * 1000)
            for indexed in db.scalars(
                select(IndexedTrip).where(IndexedTrip.ended_at >= cutoff_ms).limit(20000)
            ):
                if not indexed.encrypted_trip:
                    quality["no_processed_route"] += 1
                    continue
                try:
                    route = json.loads(
                        state.cipher.decrypt(indexed.encrypted_trip.encode()).decode()
                    )
                    if route.get("matched") is True:
                        quality["road_matched"] += 1
                    else:
                        quality["gps_normalized_only"] += 1
                except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                    quality["unreadable"] += 1
            lines.append("Verified trip quality in window: " + json.dumps(quality, sort_keys=True))
            if state.trip_processor and state.trip_processor.roads:
                cache = state.trip_processor.roads
                lines.append(
                    "Road cache: pinned="
                    + str(len(cache.pinned))
                    + ", prepared="
                    + str(sum(1 for x in cache.pinned if (cache.root / x / "region.osrm").exists()))
                    + ", max_bytes="
                    + str(cache.max_bytes)
                    + ", download_max="
                    + str(cache.download_max)
                    + ", memory_limit="
                    + str(cache.prep_mem)
                    + ", threads="
                    + str(cache.threads)
                )
                lines.append(
                    "Road graph preparation last error: "
                    + str(getattr(cache, "last_error", "not recorded"))
                )
        if category in ("all", "gps"):
            # Metadata only; never decrypt records or expose coordinates.
            devices = {
                device.id: (json.loads(device.registration).get("platform") or "unknown")
                for device in db.scalars(select(ClientDevice))
            }
            window = now - hours * 3600
            gps_rows = db.execute(
                select(
                    EncryptedRecord.device_id,
                    EncryptedRecord.captured_at,
                    EncryptedRecord.received_at,
                )
                .where(
                    EncryptedRecord.kind == "location",
                    EncryptedRecord.received_at >= window,
                    EncryptedRecord.received_at <= now,
                )
                .order_by(EncryptedRecord.device_id, EncryptedRecord.received_at)
                .limit(20000)
            ).all()
            lines.append(
                "Persisted GPS receipts: "
                + str(len(gps_rows))
                + (" (limited to 20000)" if len(gps_rows) == 20000 else "")
            )
            grouped = {}
            for device_id, captured, received in gps_rows:
                grouped.setdefault(device_id, []).append((captured, received))
            for device_id, samples in sorted(grouped.items()):
                platform = devices.get(device_id, "unknown")
                lines.append(
                    "GPS device "
                    + anon(device_id)
                    + " platform="
                    + platform
                    + " receipts="
                    + str(len(samples))
                )
                previous_capture = None
                previous_receive = None
                for captured, received in samples:
                    delay = max(0, int(received * 1000) - captured)
                    capture_gap = (
                        (captured - previous_capture) / 1000
                        if previous_capture is not None
                        else None
                    )
                    receive_gap = (
                        received - previous_receive if previous_receive is not None else None
                    )
                    details = {
                        "capture": utc(captured / 1000),
                        "received": utc(received),
                        "upload_delay_ms": delay,
                        "capture_gap_seconds": round(capture_gap, 2)
                        if capture_gap is not None
                        else None,
                        "receive_gap_seconds": round(receive_gap, 2)
                        if receive_gap is not None
                        else None,
                    }
                    lines.append(
                        utc(received)
                        + " | gps.record.received | ok | device="
                        + anon(device_id)
                        + " "
                        + json.dumps(details, sort_keys=True)
                    )
                    previous_capture, previous_receive = captured, received
            if not gps_rows:
                lines.append(
                    "No retained location records received in this window; "
                    "check device sharing and upload status."
                )
        query = (
            select(DiagnosticEntry)
            .where(DiagnosticEntry.created >= now - hours * 3600)
            .order_by(DiagnosticEntry.created.asc())
            .limit(20000)
        )
        count = 0
        for row in db.scalars(query):
            if category != "all" and row.category not in DIAGNOSTIC_CATEGORY[category]:
                continue
            if category == "trips" and sub != "all" and row.action not in STAGE[sub]:
                continue
            try:
                details = json.loads(row.details)
            except (ValueError, TypeError):
                details = {}
            filtered = {
                k: v
                for k, v in details.items()
                if k in SAFE_FIELDS
                and isinstance(v, (str, int, float, bool, type(None)))
                and (not isinstance(v, str) or len(v) <= 160)
            }
            lines.append(
                f"{utc(row.created)} | {row.category}.{row.action} | {row.outcome} | "
                + "account="
                + anon(row.account_id)
                + " device="
                + anon(row.device_id)
                + " "
                + json.dumps(filtered, sort_keys=True)
            )
            count += 1
    lines.append("")
    lines.append("Included events: " + str(count))
    return "\n".join(lines) + "\n"


def main(argv=None):
    """Command line entry point: builds a report and saves it."""
    parser = argparse.ArgumentParser(description="Export redacted Nära Hem diagnostics")
    parser.add_argument("--category", choices=list(DIAGNOSTIC_CATEGORY) + ["all"])
    parser.add_argument("--sub-category", choices=list(STAGE) + ["all"], default="all")
    parser.add_argument("--hours", type=int)
    parser.add_argument("--output", help="File name under /data/diagnostics (not an absolute path)")
    parser.add_argument("--yes", action="store_true", help="Skip interactive wizard")
    options = parser.parse_args(argv)
    category = options.category
    sub = options.sub_category
    hours = options.hours
    if not options.yes and os.isatty(0):
        if category is None:
            print(
                "Nära Hem diagnostics\n1. All\n2. Trips and maps\n3. GPS and uploads\n4. "
                "Notifications\n5. Accounts and devices\n6. Server"
            )
            category = CATEGORY.get(input("Category [2]: ").strip() or "2", "trips")
        if category == "trips" and options.sub_category == "all":
            print(
                "1. All trip processing\n2. Road matching\n3. GPS normalization\n4. Trip completion"
            )
            sub = SUB.get(input("Stage [1]: ").strip() or "1", "all")
        if hours is None:
            print("Time window: 1. Last hour  2. Last day  3. Last week")
            hours = {"1": 1, "2": 24, "3": 168}.get(input("Range [2]: ").strip() or "2", 24)
    category = category or "trips"
    hours = 24 if hours is None else hours
    if not 1 <= hours <= 336:
        parser.error("Hours must be between 1 and 336")
    if options.output:
        if Path(options.output).name != options.output or not options.output.endswith(".txt"):
            parser.error("Output must be a simple .txt filename")
        name = options.output
    else:
        name = (
            "narahem-"
            + category
            + "-"
            + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
            + ".txt"
        )

    app = create_app(mail_worker=False)
    app.state.initialize()
    report = render_report(category, sub, hours, app.state)
    if export_dir() is not None:
        output = save_export(report, name if name.startswith("narahem-") else "narahem-" + name)
        print("Report saved: " + str(output))
        print("Open it from the host folder mounted at /exports.")
        return
    target = Path(os.environ.get("NARAHEM_DATA_DIR", "/data")) / "diagnostics"
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.chmod(0o700)
    output = target / name
    with output.open("x", encoding="utf-8") as f:
        f.write(report)
    output.chmod(0o600)
    print("Report saved: " + str(output))
    print("On the Docker host: <mounted-server-data>/diagnostics/" + name)


if __name__ == "__main__":
    main()
