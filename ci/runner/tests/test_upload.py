import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "upload", Path(__file__).resolve().parents[1] / "upload-testflight.py"
)
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)

KEY = "-----BEGIN PRIVATE KEY-----\nc3ludGhldGljLW5vdC1hLWtleQ==\n-----END PRIVATE KEY-----"
ISSUER = "12345678-1234-1234-1234-123456789abc"


def environ(**changes):
    value = {
        "APP_STORE_CONNECT_API_KEY_ID": "ABCDE12345",
        "APP_STORE_CONNECT_ISSUER_ID": ISSUER,
        "APP_STORE_CONNECT_API_KEY_P8": KEY + "\n",
    }
    value.update(changes)
    return value


class UploadTests(unittest.TestCase):
    def test_credentials_are_validated_and_removed_from_the_environment(self):
        env = environ()
        self.assertEqual(upload.credentials(env), ("ABCDE12345", ISSUER, KEY))
        self.assertFalse(any(k.startswith("APP_STORE_CONNECT") for k in env))
        for bad in [
            {"APP_STORE_CONNECT_API_KEY_ID": "short"},
            {"APP_STORE_CONNECT_ISSUER_ID": "not-a-uuid"},
            {"APP_STORE_CONNECT_API_KEY_P8": "AuthKey_ABCDE12345.p8"},
            {"APP_STORE_CONNECT_API_KEY_P8": ""},
        ]:
            with self.assertRaises(ValueError):
                upload.credentials(environ(**bad))

    def test_key_exists_only_during_upload_and_altool_gets_ids_not_the_key(self):
        seen = {}

        def fake_run(args, cwd, env):
            key_file = Path(env["API_PRIVATE_KEYS_DIR"]) / "AuthKey_ABCDE12345.p8"
            seen.update(
                args=args,
                key=key_file,
                text=key_file.read_text(),
                mode=key_file.stat().st_mode & 0o777,
            )
            return subprocess.CompletedProcess(args, 0)

        with tempfile.NamedTemporaryFile(suffix=".ipa") as ipa:
            self.assertEqual(
                upload.upload(Path(ipa.name), "ABCDE12345", ISSUER, KEY, run=fake_run), 0
            )
            self.assertEqual(
                seen["args"],
                [
                    "xcrun",
                    "altool",
                    "--upload-app",
                    "--type",
                    "ios",
                    "--file",
                    ipa.name,
                    "--apiKey",
                    "ABCDE12345",
                    "--apiIssuer",
                    ISSUER,
                ],
            )
        self.assertNotIn(KEY, " ".join(seen["args"]))
        self.assertEqual(seen["text"], KEY + "\n")
        self.assertEqual(seen["mode"], 0o600)
        self.assertFalse(seen["key"].exists())


if __name__ == "__main__":
    unittest.main()
