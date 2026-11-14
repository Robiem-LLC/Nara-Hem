import unittest
from unittest.mock import patch

import httpx

from narahem import texting

BASE = "https://textbelt.example.invalid"


def answer(data):
    """Returns a Textbelt-style JSON response."""
    return httpx.Response(200, json=data, request=httpx.Request("GET", BASE))


class TextbeltClientTests(unittest.TestCase):
    def setUp(self):
        self.client = texting.Textbelt(BASE + "/", timeout=3)

    def test_quota_reads_the_credit_left(self):
        with patch.object(
            httpx, "get", return_value=answer({"success": True, "quotaRemaining": 7})
        ) as get:
            self.assertEqual(self.client.quota("k"), 7)
        self.assertEqual(get.call_args.args[0], BASE + "/quota/k")
        self.assertEqual(get.call_args.kwargs["timeout"], 3)

    def test_send_posts_the_text_and_returns_the_credit_left(self):
        reply = answer({"success": True, "quotaRemaining": 4})
        with patch.object(httpx, "post", return_value=reply) as post:
            self.assertEqual(self.client.send("k", "+14155550123", "Hello"), 4)
        self.assertEqual(post.call_args.args[0], BASE + "/text")
        self.assertEqual(
            post.call_args.kwargs["data"], {"phone": "+14155550123", "message": "Hello", "key": "k"}
        )

    def test_refusals_explain_themselves_and_links_get_advice(self):
        refused = answer({"success": False, "error": "Sorry, links are not allowed."})
        with (
            patch.object(httpx, "post", return_value=refused),
            self.assertRaises(texting.TextingError) as error,
        ):
            self.client.send("k", "+14155550123", "https://x.example.invalid")
        self.assertIn("allow links from your server", str(error.exception))
        with (
            patch.object(httpx, "get", return_value=answer({"success": False})),
            self.assertRaises(texting.TextingError) as error,
        ):
            self.client.quota("k")
        self.assertEqual(str(error.exception), "Textbelt did not say why")

    def test_unreachable_or_garbled_answers_are_a_texting_error(self):
        garbled = httpx.Response(200, text="<html>", request=httpx.Request("GET", BASE))
        with (
            patch.object(httpx, "get", side_effect=httpx.ConnectError("down")),
            self.assertRaises(texting.TextingError),
        ):
            self.client.quota("k")
        with (
            patch.object(httpx, "post", return_value=garbled),
            self.assertRaises(texting.TextingError) as error,
        ):
            self.client.send("k", "+14155550123", "Hi")
        self.assertEqual(str(error.exception), "Textbelt could not be reached")

    def test_masked_keys_show_only_the_last_four(self):
        self.assertEqual(texting.hint("abcdefghijkl"), "••••••••ijkl")
        self.assertEqual(texting.hint("short"), "••••••••")


if __name__ == "__main__":
    unittest.main()
