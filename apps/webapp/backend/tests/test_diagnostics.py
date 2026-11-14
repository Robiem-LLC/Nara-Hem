import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.orm import Session

from narahem import diagnostics_cli
from narahem.data_service import diagnostic
from narahem.models import IndexedTrip
from tests import test_relay


class DiagnosticsReportTests(unittest.TestCase):
    """The redacted diagnostics report: what it counts, and what it leaves out."""

    setUp = test_relay.RelayTests.setUp
    start = test_relay.RelayTests.start
    tearDown = test_relay.RelayTests.tearDown
    setup_owner = test_relay.RelayTests.setup_owner
    login = test_relay.RelayTests.login
    configure = test_relay.RelayTests.configure
    register = test_relay.RelayTests.register
    identity = test_relay.RelayTests.identity
    call = test_relay.RelayTests.call
    roster = test_relay.RelayTests.roster
    bootstrap = test_relay.RelayTests.bootstrap
    record = test_relay.RelayTests.record
    publish = test_relay.RelayTests.publish

    def report(self, category="all", sub="all", hours=24):
        return diagnostics_cli.render_report(category, sub, hours, self.app.state)

    def add_trip(self, status, route=None):
        """Indexes a trip with the given status and, optionally, an encrypted route."""
        if not hasattr(self, "sender"):
            self.sender = self.bootstrap()
        # Each index row belongs to a stored record; a location record is the simplest to make.
        self.trips = getattr(self, "trips", 0) + 1
        captured = int(time.time() * 1000) + self.trips
        event = self.publish(self.sender, captured=captured)["body"]["id"]
        cipher = self.app.state.cipher
        encrypted = route if route is None else cipher.encrypt(route.encode()).decode()
        with Session(self.app.state.engine) as db:
            db.add(
                IndexedTrip(
                    event_id=event,
                    account_id=self.owner_id,
                    device_id=self.sender["id"],
                    started_at=captured - 60_000,
                    ended_at=captured,
                    status=status,
                    encrypted_trip=encrypted,
                )
            )
            db.commit()

    def test_unknown_categories_and_windows_are_refused(self):
        for category, sub, hours in (
            ("everything", "all", 24),
            ("trips", "x", 24),
            ("all", "all", 0),
        ):
            with self.assertRaises(ValueError):
                self.report(category, sub, hours)

    def test_trip_quality_is_counted_without_routes(self):
        self.add_trip("done", json.dumps({"matched": True, "points": [[51.5, -0.1]]}))
        self.add_trip("done", json.dumps({"matched": False}))
        self.add_trip("pending")
        self.add_trip("done", "not json")
        text = self.report("trips")
        self.assertIn('"done": 3', text)
        self.assertIn(
            '{"gps_normalized_only": 1, "no_processed_route": 1, "road_matched": 1, '
            '"unreadable": 1}',
            text,
        )
        self.assertNotIn("51.5", text)

    def test_gps_receipts_are_listed_by_device_without_coordinates(self):
        text = self.report("gps")
        self.assertIn("No retained location records received", text)
        owner = self.bootstrap()
        self.publish(owner)
        self.publish(owner, captured=int(time.time() * 1000) + 5)
        text = self.report("gps")
        self.assertIn("Persisted GPS receipts: 2", text)
        self.assertIn("gps.record.received", text)
        self.assertIn(diagnostics_cli.anon(owner["id"]), text)
        self.assertNotIn(owner["id"], text)
        self.assertNotIn("12.3456789", text)

    def test_logged_events_keep_only_safe_short_fields(self):
        with Session(self.app.state.engine) as db:
            diagnostic(
                db,
                "trip",
                "trip.road_match",
                account=self.owner_id,
                stage="roads",
                lat=51.5,
                reason="x" * 200,
                attempts=2,
            )
            diagnostic(db, "notification", "push.sent", status="delivered")
            db.commit()
        text = self.report("trips", "roads")
        self.assertIn("trip.trip.road_match", text)
        self.assertIn('"attempts": 2', text)
        self.assertNotIn("51.5", text)
        self.assertNotIn("x" * 200, text)
        self.assertNotIn("push.sent", text)
        self.assertNotIn("trip.road_match", self.report("trips", "normalization"))
        self.assertIn("Included events: 1", self.report("notifications"))
        self.assertIn("Included events: 2", self.report("all"))

    def test_no_account_or_device_shows_a_dash(self):
        self.assertEqual(diagnostics_cli.anon(None), "-")
        self.assertEqual(len(diagnostics_cli.anon("abc")), 10)
        self.assertTrue(diagnostics_cli.report_name("gps", 24).startswith("narahem-gps-24h-"))


class DiagnosticsExportTests(unittest.TestCase):
    """Saving reports to the exports folder or the private data folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.exports = Path(self.temp.name) / "exports"
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        fake_state = SimpleNamespace(initialize=lambda: None)
        self.patches = [
            patch.object(
                diagnostics_cli, "create_app", lambda **_: SimpleNamespace(state=fake_state)
            ),
            patch.object(diagnostics_cli, "render_report", lambda *args: f"report {args[:3]}\n"),
            patch.dict(
                os.environ,
                {"NARAHEM_EXPORT_DIR": str(self.exports), "NARAHEM_DATA_DIR": str(self.data)},
            ),
        ]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def run_cli(self, *args):
        with patch("builtins.print") as printed:
            diagnostics_cli.main(list(args))
        return [call.args[0] for call in printed.call_args_list]

    def test_without_an_exports_folder_reports_go_to_the_data_folder(self):
        self.assertIsNone(diagnostics_cli.export_dir())
        lines = self.run_cli("--yes", "--category", "gps", "--hours", "2", "--output", "gps.txt")
        saved = self.data / "diagnostics" / "gps.txt"
        self.assertEqual(saved.read_text(), "report ('gps', 'all', 2)\n")
        self.assertEqual(oct(saved.stat().st_mode & 0o777), "0o600")
        self.assertIn("diagnostics/gps.txt", lines[-1])
        with self.assertRaises(FileNotFoundError):
            diagnostics_cli.save_export("text", "narahem-x.txt")

    def test_reports_in_the_exports_folder_are_readable_and_pruned(self):
        self.exports.mkdir()
        old = self.exports / "narahem-old.txt"
        old.write_text("old")
        os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
        self.run_cli("--yes", "--output", "today.txt")
        saved = self.exports / "narahem-today.txt"
        self.assertEqual(oct(saved.stat().st_mode & 0o777), "0o644")
        self.assertFalse(old.exists())
        self.run_cli("--yes")
        self.assertEqual(len(list(self.exports.glob("narahem-trips-*.txt"))), 1)
        with self.assertRaises(ValueError):
            diagnostics_cli.save_export("text", "../escape.txt")
        with patch.object(diagnostics_cli, "EXPORT_KEEP_FILES", 1):
            diagnostics_cli.save_export("text", "narahem-newest.txt")
        self.assertEqual([p.name for p in self.exports.iterdir()], ["narahem-newest.txt"])

    def test_bad_options_are_refused(self):
        with patch("sys.stderr"):
            for args in (("--yes", "--hours", "400"), ("--yes", "--output", "../x.txt")):
                with self.assertRaises(SystemExit):
                    diagnostics_cli.main(list(args))

    def test_the_wizard_asks_for_category_stage_and_window(self):
        answers = iter(["2", "3", "1"])
        with (
            patch("os.isatty", return_value=True),
            patch("builtins.input", lambda _: next(answers)),
        ):
            self.run_cli("--output", "wizard.txt")
        saved = self.data / "diagnostics" / "wizard.txt"
        self.assertEqual(saved.read_text(), "report ('trips', 'normalization', 1)\n")


if __name__ == "__main__":
    unittest.main()
