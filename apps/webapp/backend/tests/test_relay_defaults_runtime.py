import json
import os
import tempfile
import unittest
from unittest.mock import patch

from narahem import app, image_defaults, push_service

NAMES = (*image_defaults.NAMES, "NARAHEM_PUSH_RELAY_TOKEN", "NARAHEM_FCM_RELAY_TOKEN")


class BuiltInRelayDefaultsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "relay-defaults.json")
        self.env = {name: "" for name in NAMES}
        self.env["NARAHEM_RELAY_DEFAULTS_FILE"] = self.path
        # Address and token resolution only; never register with a relay.
        push_service.enable_relay_registration(None)

    def write(self, value):
        with open(self.path, "w") as f:
            f.write(value if isinstance(value, str) else json.dumps(value))

    def test_image_supplies_addresses_and_the_operator_supplies_tokens(self):
        self.write(
            {
                "NARAHEM_PUSH_RELAY_URL": "https://ios.example.invalid/v1/push",
                "NARAHEM_FCM_RELAY_URL": "https://fcm.example.invalid/v1/push",
            }
        )
        with patch.dict(
            os.environ,
            dict(
                self.env,
                NARAHEM_PUSH_RELAY_TOKEN="mine-ios",
                NARAHEM_FCM_RELAY_TOKEN="mine-fcm",
            ),
        ):
            self.assertEqual(
                push_service.relay_settings(),
                {"url": "https://ios.example.invalid/v1/push", "token": "mine-ios"},
            )
            self.assertEqual(
                push_service.fcm_relay_settings(),
                {"url": "https://fcm.example.invalid/v1/push", "token": "mine-fcm"},
            )
        # Without the server's own token there is no relay.
        with patch.dict(os.environ, self.env):
            self.assertIsNone(push_service.relay_settings())
            self.assertIsNone(push_service.fcm_relay_settings())

    def test_tokens_in_an_image_file_are_ignored(self):
        self.write(
            {
                "NARAHEM_PUSH_RELAY_URL": "https://ios.example.invalid/v1/push",
                "NARAHEM_PUSH_RELAY_TOKEN": "built-in-ios",
                "NARAHEM_FCM_RELAY_URL": "https://fcm.example.invalid/v1/push",
                "NARAHEM_FCM_RELAY_TOKEN": "built-in-fcm",
            }
        )
        with patch.dict(os.environ, self.env):
            self.assertIsNone(push_service.relay_settings())
            self.assertIsNone(push_service.fcm_relay_settings())

    def test_environment_overrides_image_defaults(self):
        self.write(
            {
                "NARAHEM_PUSH_RELAY_URL": "https://ios.example.invalid/v1/push",
                "NARAHEM_PUSH_RELAY_TOKEN": "built-in-ios",
            }
        )
        with patch.dict(
            os.environ,
            dict(
                self.env,
                NARAHEM_PUSH_RELAY_URL="https://mine.example.invalid/v1/push",
                NARAHEM_PUSH_RELAY_TOKEN="operator",
            ),
        ):
            self.assertEqual(
                push_service.relay_settings(),
                {"url": "https://mine.example.invalid/v1/push", "token": "operator"},
            )

    def test_missing_or_malformed_defaults_disable_push(self):
        with patch.dict(os.environ, self.env):
            self.assertIsNone(push_service.relay_settings())
            self.write("not json")
            self.assertIsNone(push_service.fcm_relay_settings())
            self.write(["unexpected"])
            self.assertIsNone(push_service.relay_settings())

    def test_invalid_built_in_url_is_still_rejected(self):
        self.write({"NARAHEM_PUSH_RELAY_URL": "http://insecure.example.invalid/v1/push"})
        with (
            patch.dict(os.environ, dict(self.env, NARAHEM_PUSH_RELAY_TOKEN="x")),
            self.assertRaises(ValueError),
        ):
            push_service.relay_settings()

    def test_app_links_come_from_the_image_unless_overridden(self):
        with patch.dict(os.environ, self.env):
            self.assertEqual(app.app_links(), (None, None))
            self.write({"NARAHEM_IOS_APP_URL": "https://apps.example.invalid/ios"})
            self.assertEqual(app.app_links(), ("https://apps.example.invalid/ios", None))
        with patch.dict(os.environ, dict(self.env, NARAHEM_IOS_APP_URL="none")):
            self.assertEqual(app.app_links(), (None, None))

    def test_unknown_names_in_the_image_file_are_ignored(self):
        self.write({"NARAHEM_ALEXA_RELAY_URL": "https://alexa.example.invalid", "OTHER": "x"})
        with patch.dict(os.environ, self.env):
            self.assertEqual(
                image_defaults.built_in(),
                {"NARAHEM_ALEXA_RELAY_URL": "https://alexa.example.invalid"},
            )


if __name__ == "__main__":
    unittest.main()
