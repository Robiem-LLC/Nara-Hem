import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from narahem import push_service

PUSH = "https://push.example.invalid/v1/push"
FCM = "https://fcm.example.invalid/v1/push"
ISSUED = "A" * 43


def relay_reply(status, body):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    return response


class RelayRegistrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        push_service.enable_relay_registration(self.folder)
        self.addCleanup(push_service.enable_relay_registration, None)
        self.env = {
            "NARAHEM_RELAY_DEFAULTS_FILE": str(self.folder / "none.json"),
            "NARAHEM_PUSH_RELAY_URL": PUSH,
            "NARAHEM_PUSH_RELAY_TOKEN": "",
            "NARAHEM_FCM_RELAY_URL": FCM,
            "NARAHEM_FCM_RELAY_TOKEN": "",
        }
        client = patch("narahem.push_service.httpx.Client")
        self.client = client.start()
        self.addCleanup(client.stop)
        self.post = self.client.return_value.__enter__.return_value.post

    def test_registers_once_per_relay_and_keeps_the_token_private(self):
        self.post.return_value = relay_reply(201, {"ok": True, "token": ISSUED})
        with patch.dict(os.environ, self.env):
            self.assertEqual(
                push_service.relay_settings(), {"url": PUSH, "token": ISSUED, "registered": True}
            )
            self.assertEqual(push_service.relay_settings()["token"], ISSUED)
            self.assertEqual(push_service.fcm_relay_settings()["token"], ISSUED)
        # One registration per relay, sent to /v1/register with no credentials.
        self.assertEqual(
            [call.args[0] for call in self.post.call_args_list],
            ["https://push.example.invalid/v1/register", "https://fcm.example.invalid/v1/register"],
        )
        for call in self.post.call_args_list:
            self.assertNotIn("headers", call.kwargs)
        stored = self.folder / push_service.REGISTRATIONS_FILE
        self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
        self.assertEqual(set(json.loads(stored.read_text())), {PUSH, FCM})

    def test_configured_tokens_win_and_never_register(self):
        with patch.dict(os.environ, dict(self.env, NARAHEM_PUSH_RELAY_TOKEN="manual-token")):
            self.assertEqual(push_service.relay_settings(), {"url": PUSH, "token": "manual-token"})
        self.post.assert_not_called()

    def test_refused_or_malformed_registration_waits_before_retrying(self):
        with patch.dict(os.environ, self.env):
            for reply in (
                relay_reply(429, {"error": "Too many registrations today"}),
                relay_reply(201, {"token": "short"}),
            ):
                push_service.enable_relay_registration(self.folder)
                self.post.reset_mock()
                self.post.return_value = reply
                self.assertIsNone(push_service.relay_settings())
                self.assertIsNone(push_service.relay_settings())
                self.assertEqual(self.post.call_count, 1, "No retry inside the waiting period")
            self.post.return_value = relay_reply(201, {"token": ISSUED})
            later = push_service.time.time() + push_service.REGISTRATION_RETRY_SECONDS + 1
            with patch("narahem.push_service.time.time", return_value=later):
                self.assertEqual(push_service.relay_settings()["token"], ISSUED)

    def test_without_a_data_folder_nothing_registers(self):
        push_service.enable_relay_registration(None)
        with patch.dict(os.environ, self.env):
            self.assertIsNone(push_service.relay_settings())
        self.post.assert_not_called()

    def test_rejected_registered_token_is_forgotten_after_the_grace_period(self):
        self.post.return_value = relay_reply(201, {"token": ISSUED})
        with patch.dict(os.environ, self.env):
            relay = push_service.relay_settings()
        rejected = relay_reply(401, {"error": "Unauthorized"})
        self.post.return_value = rejected
        # A brand-new token may not have reached every relay location yet: keep it.
        with self.assertRaises(push_service.PushRelayFailure):
            push_service.relay_deliver("d" * 64, "production", "0" * 32, None, relay)
        self.assertIn(PUSH, json.loads((self.folder / push_service.REGISTRATIONS_FILE).read_text()))
        later = push_service.time.time() + push_service.REGISTRATION_GRACE_SECONDS + 1
        with (
            patch("narahem.push_service.time.time", return_value=later),
            self.assertRaises(push_service.PushRelayFailure),
        ):
            push_service.relay_deliver("d" * 64, "production", "0" * 32, None, relay)
        self.assertNotIn(
            PUSH, json.loads((self.folder / push_service.REGISTRATIONS_FILE).read_text())
        )
        # The next use registers again.
        self.post.return_value = relay_reply(201, {"token": "B" * 43})
        with patch.dict(os.environ, self.env):
            self.assertEqual(push_service.relay_settings()["token"], "B" * 43)

    def test_manual_tokens_are_never_forgotten(self):
        self.post.return_value = relay_reply(401, {"error": "Unauthorized"})
        with self.assertRaises(OSError) as raised:
            push_service.fcm_relay_deliver("token", None, {"url": FCM, "token": "manual-token"})
        self.assertEqual(raised.exception.relay_status, 401)
        self.assertFalse((self.folder / push_service.REGISTRATIONS_FILE).exists())

    def test_status_explains_a_refused_registration_and_never_shows_tokens(self):
        self.post.side_effect = [
            relay_reply(404, {"error": "Registration is not enabled"}),
            relay_reply(201, {"token": ISSUED}),
        ]
        with patch.dict(os.environ, self.env):
            push_service.relay_settings()
            push_service.fcm_relay_settings()
            push, fcm = push_service.relay_status()
        self.assertEqual((push["address"], push["registered"]), (PUSH, False))
        self.assertEqual(
            push["last_error"], "The relay answered HTTP 404: Registration is not enabled"
        )
        self.assertGreater(push["retry_in"], 0)
        self.assertEqual((fcm["registered"], fcm["last_error"]), (True, None))
        self.assertNotIn(ISSUED, json.dumps([push, fcm]))

    def test_register_now_skips_the_wait_after_a_failure(self):
        self.post.return_value = relay_reply(404, {"error": "Registration is not enabled"})
        with patch.dict(os.environ, self.env):
            self.assertIsNone(push_service.relay_settings())
            self.post.return_value = relay_reply(201, {"token": ISSUED})
            self.assertIsNone(push_service.relay_settings(), "Still inside the waiting period")
            push, fcm = push_service.register_relays_now()
        self.assertTrue(push["registered"] and fcm["registered"])
        self.assertIsNone(push["last_error"])


if __name__ == "__main__":
    unittest.main()
