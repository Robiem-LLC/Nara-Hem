import json
import os
import tempfile
import unittest

from relay_defaults import DEFAULTS, build, main

URL = "https://relay.example.invalid/v1/push"


class RelayDefaultsTests(unittest.TestCase):
    def test_only_valid_addresses_are_written_never_tokens_or_printed_values(self):
        defaults, summary = build(
            {
                "NARAHEM_PUSH_RELAY_URL": URL,
                "NARAHEM_PUSH_RELAY_TOKEN": "secret-ios",
                "NARAHEM_FCM_RELAY_URL": "http://insecure.invalid/v1/push",
                "NARAHEM_FCM_RELAY_TOKEN": "secret-android",
            }
        )
        self.assertEqual(defaults, {"NARAHEM_PUSH_RELAY_URL": URL})
        for value in ("secret-ios", "secret-android", URL):
            self.assertNotIn(value, "\n".join(summary))
            self.assertNotIn(value, json.dumps(defaults) if value != URL else "")
        self.assertIn("not built in", summary[1])

    def test_alexa_and_app_links_are_built_in_when_valid(self):
        defaults, summary = build(
            {
                "NARAHEM_ALEXA_RELAY_URL": "https://alexa.example.invalid",
                "NARAHEM_ALEXA_STORE_SKILL_ID": "amzn1.ask.skill."
                + "a" * 8
                + "-bbbb-cccc-dddd-"
                + "e" * 12,
                "NARAHEM_IOS_APP_URL": "https://apps.example.invalid/join/abc",
                "NARAHEM_ANDROID_APP_URL": "http://apps.example.invalid/app.apk",
            }
        )
        self.assertEqual(
            sorted(defaults),
            ["NARAHEM_ALEXA_RELAY_URL", "NARAHEM_ALEXA_STORE_SKILL_ID", "NARAHEM_IOS_APP_URL"],
        )
        self.assertIn("Android app link: **not built in**", "\n".join(summary))
        rejected, _ = build(
            {
                "NARAHEM_ALEXA_RELAY_URL": "https://alexa.example.invalid/link",
                "NARAHEM_ALEXA_STORE_SKILL_ID": "amzn1.ask.skill.not-a-skill",
                "NARAHEM_IOS_APP_URL": "https://user:pass@apps.example.invalid/",
            }
        )
        self.assertEqual(rejected, {})

    def test_no_secrets_writes_an_empty_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "relay.json")
            for name in (*DEFAULTS, "NARAHEM_PUSH_RELAY_TOKEN", "NARAHEM_FCM_RELAY_TOKEN"):
                os.environ.pop(name, None)
            main(path)
            self.assertEqual(os.path.getsize(path), 0)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
