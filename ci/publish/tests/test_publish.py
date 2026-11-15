import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from publish import configured_root, publish


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.share = self.root / "share"
        self.apk = self.source / "test.apk"
        self.make_apk(b"first")

    def make_apk(self, data):
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"manifest")
            archive.writestr("classes.dex", data)

    def send(self, run=10):
        with contextlib.redirect_stdout(io.StringIO()):
            return publish(self.share, self.source, "android", run, 1, "a" * 40)

    def test_new_version_keeps_previous_and_older_run_does_not_regress_latest(self):
        first = self.send()
        original = (first / "NaraHem.apk").read_bytes()
        self.make_apk(b"newer")
        second = self.send(11)
        self.assertEqual((first / "NaraHem.apk").read_bytes(), original)
        self.assertTrue((second / "NaraHem.apk").is_file())
        self.send(9)
        latest = json.loads((self.share / "android/latest.json").read_text())
        self.assertEqual(latest["run_id"], 11)

    def test_dev_builds_publish_separately_and_never_replace_main_latest(self):
        self.send(10)
        main_package = (self.share / "android/NaraHem.apk").read_bytes()
        self.make_apk(b"dev build")
        with contextlib.redirect_stdout(io.StringIO()):
            publish(self.share, self.source, "android", 20, 1, "b" * 40, channel="dev")
        self.assertEqual(json.loads((self.share / "android/latest.json").read_text())["run_id"], 10)
        self.assertEqual((self.share / "android/NaraHem.apk").read_bytes(), main_package)
        dev_latest = json.loads((self.share / "android-dev/latest.json").read_text())
        self.assertEqual((dev_latest["run_id"], dev_latest["channel"]), (20, "dev"))
        self.assertTrue((self.share / "android-dev/NaraHem.apk").is_file())
        with self.assertRaises(ValueError):
            publish(self.share, self.source, "android", 21, 1, "b" * 40, channel="feature")

    def test_releases_publish_separately_with_their_version(self):
        self.send(10)
        self.make_apk(b"signed release")
        with contextlib.redirect_stdout(io.StringIO()):
            publish(
                self.share,
                self.source,
                "android",
                30,
                1,
                "c" * 40,
                channel="release",
                release="1.0.0",
            )
        self.assertEqual(json.loads((self.share / "android/latest.json").read_text())["run_id"], 10)
        latest = json.loads((self.share / "android-release/latest.json").read_text())
        self.assertEqual((latest["channel"], latest["release"]), ("release", "1.0.0"))
        self.assertEqual(
            (self.share / "android-release/NaraHem.apk").read_bytes(), self.apk.read_bytes()
        )
        for channel, number in [("release", None), ("release", "v1"), ("main", "1.0.0")]:
            with self.assertRaises(ValueError):
                publish(
                    self.share,
                    self.source,
                    "android",
                    31,
                    1,
                    "c" * 40,
                    channel=channel,
                    release=number,
                )

    def test_latest_package_and_two_historical_versions(self):
        import hashlib

        for run_id in (10, 11, 12, 13, 14):
            self.make_apk(str(run_id).encode())
            self.send(run_id)
        latest = self.share / "android/NaraHem.apk"
        self.assertTrue(latest.is_file())
        self.assertEqual(latest.read_bytes(), self.apk.read_bytes())
        manifest = json.loads((self.share / "android/latest.json").read_text())
        self.assertEqual(manifest["run_id"], 14)
        self.assertEqual(hashlib.sha256(latest.read_bytes()).hexdigest(), manifest["sha256"])
        versions = [p for p in (self.share / "android/builds").iterdir() if p.is_dir()]
        self.assertEqual(len(versions), 3)
        self.assertTrue(any(p.name.startswith("14-") for p in versions))
        self.assertTrue(any(p.name.startswith("13-") for p in versions))
        self.assertTrue(any(p.name.startswith("12-") for p in versions))
        self.make_apk(b"older")
        self.send(9)
        self.assertEqual(
            latest.read_bytes(),
            (self.share / "android" / "builds" / ("14-1-" + "a" * 12) / "NaraHem.apk").read_bytes(),
        )

    def test_restrictive_umask_still_produces_readable_packages(self):
        original = os.umask(0o077)
        try:
            dest = self.send(23)
        finally:
            os.umask(original)
        published = self.share / "android"
        expected = [published, published / "builds", dest]
        expected_files = [
            published / "NaraHem.apk",
            published / "latest.json",
            dest / "NaraHem.apk",
            dest / "manifest.json",
        ]
        for path in expected:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755, str(path))
        for path in expected_files:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, str(path))

    def test_failed_copy_keeps_latest_and_successful_version(self):
        first = self.send()
        pointer = (self.share / "android/latest.json").read_bytes()
        self.make_apk(b"next")
        with patch("publish.shutil.copyfile", side_effect=OSError("network disconnected")):
            with self.assertRaises(OSError):
                self.send(11)
        self.assertEqual((self.share / "android/latest.json").read_bytes(), pointer)
        self.assertTrue((first / "NaraHem.apk").is_file())
        self.assertFalse((self.share / ".publish-lock").exists())

    def test_conflicting_retry_never_overwrites(self):
        first = self.send()
        original = (first / "NaraHem.apk").read_bytes()
        self.make_apk(b"different")
        with self.assertRaises(ValueError):
            self.send()
        self.assertEqual((first / "NaraHem.apk").read_bytes(), original)

    def test_invalid_package_and_concurrent_publish_leave_latest_unchanged(self):
        self.send()
        pointer = (self.share / "android/latest.json").read_bytes()
        (self.share / ".publish-lock").mkdir()
        with self.assertRaises(FileExistsError):
            self.send(11)
        (self.share / ".publish-lock").rmdir()
        self.apk.write_bytes(b"invalid zip")
        with self.assertRaises(zipfile.BadZipFile):
            self.send(11)
        self.assertEqual((self.share / "android/latest.json").read_bytes(), pointer)

    def test_pointer_update_failure_preserves_previous_latest(self):
        first = self.send()
        pointer = (self.share / "android/latest.json").read_bytes()
        self.make_apk(b"next")
        with patch("publish.os.replace", side_effect=OSError("rename failed")):
            with self.assertRaises(OSError):
                self.send(11)
        self.assertEqual((self.share / "android/latest.json").read_bytes(), pointer)
        self.assertTrue((first / "NaraHem.apk").is_file())

    def test_idempotent_retry_and_conflicting_packages(self):
        first = self.send()
        self.assertEqual(first, self.send())
        with zipfile.ZipFile(self.source / "other.apk", "w") as archive:
            archive.writestr("AndroidManifest.xml", b"different")
            archive.writestr("classes.dex", b"different")
        pointer = (self.share / "android/latest.json").read_bytes()
        with self.assertRaises(ValueError):
            self.send(11)
        self.assertEqual((self.share / "android/latest.json").read_bytes(), pointer)

    def test_disabled_and_unmounted_configs_do_not_create_a_destination(self):
        config = self.root / "config.json"
        config.write_text(json.dumps({"enabled": False, "mountpoint": None}))
        with self.assertRaises(ValueError):
            configured_root(config)
        config.write_text(
            json.dumps({"enabled": True, "mountpoint": str(self.share), "directory": "NaraHem"})
        )
        with self.assertRaises(ValueError):
            configured_root(config)
        self.assertFalse(self.share.exists())

    def test_unsigned_ipa_cannot_be_published(self):
        self.send()
        source = self.root / "simulator"
        source.mkdir()
        with zipfile.ZipFile(source / "simulator.ipa", "w") as archive:
            archive.writestr("Payload/NaraHem.app/Info.plist", b"simulator")
        with self.assertRaises(ValueError):
            publish(self.share, source, "ios", 20, 1, "b" * 40)
        self.assertFalse((self.share / "ios").exists())

    def test_wrong_receipt_preserves_previous_build(self):
        first = self.send()
        receipt = self.root / "receipt.json"
        receipt.write_text(json.dumps({"type": "simulator"}))
        with self.assertRaises(ValueError):
            publish(self.share, self.source, "android", 11, 1, "a" * 40, receipt)
        self.assertTrue((first / "NaraHem.apk").is_file())


if __name__ == "__main__":
    unittest.main()
