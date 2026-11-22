import base64
import datetime as dt
import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps/ios/ci/remote"))
from build import (
    bundle_version,
    decode_profile,
    marketing_version,
    validate_extension_profile,
    validate_profile,
)

spec = importlib.util.spec_from_file_location(
    "wrapper", Path(__file__).resolve().parents[1] / "with-signing.py"
)
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def profile():
    return {
        "UUID": "12345678-1234-1234-1234-123456789ABC",
        "TeamIdentifier": ["ABCDEFGHIJ"],
        "ExpirationDate": dt.datetime.now() + dt.timedelta(days=30),
        "ProvisionedDevices": ["device"],
        "Entitlements": {
            "application-identifier": "ABCDEFGHIJ.com.robiem.narahem",
            "aps-environment": "production",
            "get-task-allow": False,
            "com.apple.developer.usernotifications.time-sensitive": True,
            "com.apple.security.application-groups": ["group.com.robiem.narahem.notifications"],
        },
    }


def extension_profile():
    value = profile()
    value["UUID"] = "87654321-4321-4321-4321-CBA987654321"
    value["Entitlements"] = {
        "application-identifier": "ABCDEFGHIJ.com.robiem.narahem.notifications",
        "get-task-allow": False,
        "com.apple.security.application-groups": ["group.com.robiem.narahem.notifications"],
    }
    return value


class SigningTests(unittest.TestCase):
    def test_headless_profile_decoder_verifies_cms_without_keychain(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.mobileprovision"
            source.write_bytes(b"cms-fixture")
            data = plistlib.dumps(profile())
            with patch("build.run", return_value=data) as mocked:
                parsed = decode_profile(source)
            self.assertEqual(parsed["UUID"], profile()["UUID"])
            argv = mocked.call_args.args
            self.assertEqual(str(argv[0]), "/opt/homebrew/opt/openssl@3/bin/openssl")
            self.assertEqual(argv[1:6], ("cms", "-verify", "-noverify", "-binary", "-inform"))
            self.assertNotIn("security", argv)
            self.assertTrue(mocked.call_args.kwargs["capture"])

    def test_the_version_comes_from_the_version_file(self):
        self.assertRegex(marketing_version(), r"^[0-9]+\.[0-9]+\.[0-9]+$")
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "VERSION"
            bad.write_text("1.0\n")
            with self.assertRaises(ValueError):
                marketing_version(bad)

    def test_bundle_versions_fit_apple_limits(self):
        for n in [0, 1, 10000, 34567890, 99989999]:
            parts = bundle_version(n).split(".")
            self.assertTrue(all(len(p) <= limit for p, limit in zip(parts, [4, 2, 2])))
        with self.assertRaises(ValueError):
            bundle_version(99990000)

    def test_wrong_profile_type_expiry_wildcard_and_devices_rejected(self):
        self.assertEqual(validate_profile(profile(), "ad-hoc"), "ABCDEFGHIJ")
        with self.assertRaises(ValueError):
            validate_profile(profile(), "development")
        for change in [
            {"ProvisionedDevices": []},
            {"ProvisionsAllDevices": True},
            {"ExpirationDate": dt.datetime(2020, 1, 1)},
            {"Entitlements": {"application-identifier": "ABCDEFGHIJ.*"}},
        ]:
            with self.assertRaises(ValueError):
                validate_profile(dict(profile(), **change), "ad-hoc")
        # A profile regenerated before App Groups was enabled cannot share keys with the extension.
        missing_group = profile()
        del missing_group["Entitlements"]["com.apple.security.application-groups"]
        with self.assertRaisesRegex(ValueError, "App Group"):
            validate_profile(missing_group, "ad-hoc")
        # Likewise a profile regenerated before Time Sensitive Notifications was enabled.
        not_time_sensitive = profile()
        del not_time_sensitive["Entitlements"][
            "com.apple.developer.usernotifications.time-sensitive"
        ]
        with self.assertRaisesRegex(ValueError, "Time Sensitive"):
            validate_profile(not_time_sensitive, "ad-hoc")

    def test_app_store_profiles_have_no_devices(self):
        store, store_extension = profile(), extension_profile()
        for value in (store, store_extension):
            del value["ProvisionedDevices"]
        self.assertEqual(validate_profile(store, "app-store"), "ABCDEFGHIJ")
        self.assertEqual(validate_extension_profile(store_extension, "app-store"), "ABCDEFGHIJ")
        # An Ad Hoc profile is refused for TestFlight, and an App Store profile for Ad Hoc.
        with self.assertRaisesRegex(ValueError, "App Store"):
            validate_profile(profile(), "app-store")
        with self.assertRaisesRegex(ValueError, "App Store"):
            validate_extension_profile(extension_profile(), "app-store")
        with self.assertRaises(ValueError):
            validate_profile(store, "ad-hoc")
        with self.assertRaises(ValueError):
            validate_profile(dict(store, ProvisionsAllDevices=True), "app-store")

    def test_alert_extension_profile_must_match_its_bundle_and_group(self):
        self.assertEqual(validate_extension_profile(extension_profile(), "ad-hoc"), "ABCDEFGHIJ")
        with self.assertRaises(ValueError):
            validate_extension_profile(profile(), "ad-hoc")
        with self.assertRaises(ValueError):
            validate_extension_profile(extension_profile(), "development")
        no_group = extension_profile()
        no_group["Entitlements"]["com.apple.security.application-groups"] = []
        for change in [
            no_group,
            dict(extension_profile(), ProvisionedDevices=[]),
            dict(extension_profile(), ExpirationDate=dt.datetime(2020, 1, 1)),
        ]:
            with self.assertRaises(ValueError):
                validate_extension_profile(change, "ad-hoc")

    def test_command_error_does_not_print_secret_arguments(self):
        with patch.object(
            wrapper.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, ["security", "-P", "dummy-secret"]),
        ):
            with self.assertRaises(RuntimeError) as error:
                wrapper.run("security", "import", "-P", "dummy-secret")
        self.assertNotIn("dummy-secret", str(error.exception))

    def test_failed_build_restores_search_list_and_preserves_existing_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            home, data = Path(temporary), plistlib.dumps(profile())
            extension_data = plistlib.dumps(extension_profile())
            existing = (
                home
                / "Library/MobileDevice/Provisioning Profiles"
                / (profile()["UUID"] + ".mobileprovision")
            )
            existing.parent.mkdir(parents=True)
            existing.write_bytes(data)
            calls = []

            def fake(*args, **kwargs):
                args = [str(a) for a in args]
                calls.append(args)
                if args == ["security", "list-keychains", "-d", "user"]:
                    return b'"/original/login.keychain-db"\n'
                if "pkcs12" in args and "-out" in args:
                    Path(args[args.index("-out") + 1]).write_bytes(b"encrypted-fixture")
                if args[0] == "/bin/bash":
                    self.assertNotIn("IOS_P12_PASSWORD", os.environ)
                    self.assertIn("--extension-profile", args)
                    installed = (
                        home
                        / "Library/MobileDevice/Provisioning Profiles"
                        / (extension_profile()["UUID"] + ".mobileprovision")
                    )
                    self.assertEqual(installed.read_bytes(), extension_data)
                    self.assertTrue(
                        os.environ.get("NARAHEM_SIGNING_KEYCHAIN", "").endswith(
                            "/build.keychain-db"
                        )
                    )
                    raise RuntimeError("simulated build failure")
                return b""

            env = {
                "IOS_P12_BASE64": base64.b64encode(b"fixture").decode(),
                "IOS_P12_PASSWORD": "dummy",
                "IOS_PROFILE_BASE64": base64.b64encode(data).decode(),
                "IOS_EXTENSION_PROFILE_BASE64": base64.b64encode(extension_data).decode(),
                "RUNNER_TEMP": temporary,
            }
            with (
                patch.dict(os.environ, env),
                patch.object(wrapper, "run", side_effect=fake),
                patch.object(
                    wrapper, "decode_profile", side_effect=[profile(), extension_profile()]
                ),
                patch.object(wrapper.Path, "home", return_value=home),
                patch.object(wrapper.Path, "is_file", return_value=True),
                patch.object(wrapper.signal, "signal"),
                patch.object(wrapper.os, "umask"),
                patch.object(sys, "argv", ["with-signing.py", "--method", "ad-hoc"]),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated build failure"):
                    wrapper.main()
            self.assertNotIn("NARAHEM_SIGNING_KEYCHAIN", os.environ)
            self.assertEqual(existing.read_bytes(), data)
            self.assertFalse(
                (
                    home / "Library/Developer/Xcode/UserData/Provisioning Profiles" / existing.name
                ).exists()
            )
            # The temporarily installed extension profile is removed again.
            self.assertFalse(
                (
                    home
                    / "Library/MobileDevice/Provisioning Profiles"
                    / (extension_profile()["UUID"] + ".mobileprovision")
                ).exists()
            )
            restore = [
                "security",
                "list-keychains",
                "-d",
                "user",
                "-s",
                "/original/login.keychain-db",
            ]
            self.assertIn(restore, calls)
            self.assertTrue(
                any(
                    c[:2] == ["security", "delete-keychain"]
                    for c in calls[calls.index(restore) + 1 :]
                )
            )
