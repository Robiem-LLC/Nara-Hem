import tempfile
import unittest
import urllib.error
from pathlib import Path

from github_release import publish, release_details

REPO = "example/app"
UPLOAD = "https://uploads.example.invalid/releases/1/assets{?name,label}"


class FakeGitHub:
    """Records requests and answers like GitHub, with or without an existing release."""

    def __init__(self, release=None):
        self.release = release
        self.calls = []

    def __call__(self, method, url, token, body=None, content_type="application/json"):
        self.calls.append((method, url, body, content_type))
        if method == "GET":
            if self.release is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return self.release
        if url.endswith("/releases"):
            return {
                "upload_url": UPLOAD,
                "html_url": "https://example.invalid/v1.0.0",
                "assets": [],
            }
        return None


class GitHubReleaseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.apk = Path(folder.name, "NaraHem-Android-1.0.0.apk")
        self.apk.write_bytes(b"apk")
        self.sums = Path(folder.name, "SHA256SUMS")
        self.sums.write_text("abc  NaraHem-Android-1.0.0.apk\n")

    def test_versions_are_plain_or_beta_and_betas_are_prereleases(self):
        self.assertEqual(release_details("1.0.0")["tag_name"], "v1.0.0")
        self.assertFalse(release_details("1.0.0")["prerelease"])
        self.assertTrue(release_details("1.2.0-beta.3")["prerelease"])
        for bad in ("v1.0.0", "1.0", "1.0.0; rm -rf /", "1.0.0-preview"):
            with self.assertRaises(ValueError):
                release_details(bad)

    def test_a_new_release_is_created_with_generated_notes_and_files_uploaded(self):
        github = FakeGitHub()
        page = publish(REPO, "1.0.0", [self.apk, self.sums], "token", github)
        self.assertEqual(page, "https://example.invalid/v1.0.0")
        created = github.calls[1]
        self.assertEqual(created[:2], ("POST", "https://api.github.com/repos/example/app/releases"))
        self.assertTrue(created[2]["generate_release_notes"])
        self.assertEqual(created[2]["name"], "Nära Hem 1.0.0")
        uploads = github.calls[2:]
        self.assertEqual(uploads[0][1], UPLOAD.split("{")[0] + "?name=NaraHem-Android-1.0.0.apk")
        self.assertEqual(uploads[0][2:], (b"apk", "application/vnd.android.package-archive"))
        self.assertEqual(uploads[1][3], "text/plain")
        self.assertNotIn("target_commitish", created[2])

    def test_a_new_release_tags_the_commit_it_was_built_from(self):
        github = FakeGitHub()
        publish(REPO, "1.0.1", [self.apk], "token", github, target="a" * 40)
        self.assertEqual(github.calls[1][2]["target_commitish"], "a" * 40)
        self.assertEqual(github.calls[1][2]["tag_name"], "v1.0.1")

    def test_running_again_replaces_files_of_the_same_name(self):
        release = {
            "upload_url": UPLOAD,
            "html_url": "https://example.invalid/v1.0.0",
            "assets": [{"name": "NaraHem-Android-1.0.0.apk", "id": 7}],
        }
        github = FakeGitHub(release)
        publish(REPO, "1.0.0", [self.apk], "token", github)
        methods = [(method, url.rsplit("/", 1)[-1]) for method, url, *_ in github.calls]
        self.assertEqual(methods[1], ("DELETE", "7"))
        self.assertEqual(methods[2][0], "POST")
        self.assertEqual(len(github.calls), 3)


if __name__ == "__main__":
    unittest.main()
