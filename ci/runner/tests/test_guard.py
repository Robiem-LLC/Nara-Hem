import tempfile
import unittest
from pathlib import Path

import guard

REPO = "Example-Org/NaraHem"
PREFIX = REPO + "/.github/workflows/"


def allowed(env, event):
    return guard.allowed(env, event, REPO)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": PREFIX + "ios-mac.yaml@refs/heads/main",
            "GITHUB_EVENT_NAME": "push",
        }
        self.event = {"repository": {"full_name": REPO}, "ref": "refs/heads/main"}

    def test_trusted_main_and_manual_dispatch(self):
        self.assertTrue(allowed(self.env, self.event))
        self.env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        self.assertTrue(allowed(self.env, self.event))

    def test_android_allowed_only_on_trusted_main(self):
        self.env["GITHUB_WORKFLOW_REF"] = PREFIX + "android.yaml@refs/heads/main"
        self.assertTrue(allowed(self.env, self.event))
        self.env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        self.assertTrue(allowed(self.env, self.event))
        self.env["GITHUB_EVENT_NAME"] = "pull_request"
        self.assertFalse(allowed(self.env, self.event))
        self.env["GITHUB_EVENT_NAME"] = "push"
        self.env["GITHUB_REF"] = "refs/heads/feature"
        self.assertFalse(allowed(self.env, self.event))

    def test_dev_builds_allowed_only_from_dev_workflow_file(self):
        for name in ("android.yaml", "ios-mac.yaml", "showcase.yaml"):
            env = dict(
                self.env,
                GITHUB_REF="refs/heads/dev",
                GITHUB_WORKFLOW_REF=PREFIX + name + "@refs/heads/dev",
            )
            event = dict(self.event, ref="refs/heads/dev")
            self.assertTrue(allowed(env, event))
            self.assertTrue(allowed(dict(env, GITHUB_EVENT_NAME="workflow_dispatch"), event))
            self.assertFalse(allowed(dict(env, GITHUB_EVENT_NAME="pull_request"), event))
            # Branch and workflow file must match; a push event for another ref is refused.
            self.assertFalse(
                allowed(dict(env, GITHUB_WORKFLOW_REF=PREFIX + name + "@refs/heads/main"), event)
            )
            self.assertFalse(allowed(env, dict(event, ref="refs/heads/main")))
            self.assertFalse(
                allowed(
                    dict(
                        env,
                        GITHUB_REF="refs/heads/devil",
                        GITHUB_WORKFLOW_REF=PREFIX + name + "@refs/heads/devil",
                    ),
                    dict(event, ref="refs/heads/devil"),
                )
            )

    def test_showcase_follows_the_build_workflow_rules(self):
        self.env["GITHUB_WORKFLOW_REF"] = PREFIX + "showcase.yaml@refs/heads/main"
        self.assertTrue(allowed(self.env, self.event))
        self.assertTrue(allowed(dict(self.env, GITHUB_EVENT_NAME="workflow_dispatch"), self.event))
        self.assertFalse(allowed(dict(self.env, GITHUB_EVENT_NAME="pull_request"), self.event))
        self.assertFalse(
            allowed(
                dict(
                    self.env,
                    GITHUB_REF="refs/heads/feature/showcase",
                    GITHUB_WORKFLOW_REF=PREFIX + "showcase.yaml@refs/heads/feature/showcase",
                ),
                dict(self.event, ref="refs/heads/feature/showcase"),
            )
        )

    def test_the_retired_share_publisher_is_refused(self):
        # Builds copy to the share themselves; no workflow_run job runs on this Mac.
        self.env.update(
            GITHUB_WORKFLOW_REF=PREFIX + "publish-smb.yaml@refs/heads/main",
            GITHUB_EVENT_NAME="workflow_run",
        )
        self.event["workflow_run"] = {
            "conclusion": "success",
            "head_branch": "main",
            "head_repository": {"full_name": REPO},
            "event": "push",
            "path": ".github/workflows/android.yaml",
        }
        self.assertFalse(allowed(self.env, self.event))

    def test_pr_target_pr_other_branch_and_other_workflow_are_denied(self):
        for event in ["pull_request", "pull_request_target", "workflow_run"]:
            self.assertFalse(allowed(dict(self.env, GITHUB_EVENT_NAME=event), self.event))
        self.assertFalse(allowed(dict(self.env, GITHUB_REF="refs/heads/feature"), self.event))
        self.assertFalse(
            allowed(
                dict(self.env, GITHUB_WORKFLOW_REF=PREFIX + "evil.yaml@refs/heads/main"), self.event
            )
        )
        self.assertFalse(allowed({}, {}))

    def test_reads_owner_and_name_and_refuses_anything_else(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository"
            path.write_text(REPO + "\n")
            self.assertEqual(guard.trusted_repository(path), REPO)
            for bad in ["", "no-slash", "a/b/c", "owner/name; rm -rf /"]:
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    guard.trusted_repository(path)
            path.unlink()
            with self.assertRaises(OSError):
                guard.trusted_repository(path)

    def test_only_the_trusted_repository_is_accepted(self):
        env = {
            "GITHUB_REPOSITORY": "someone/NaraHem",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": (
                "someone/NaraHem/.github/workflows/ios-mac.yaml@refs/heads/main"
            ),
            "GITHUB_EVENT_NAME": "push",
        }
        event = {"repository": {"full_name": "someone/NaraHem"}, "ref": "refs/heads/main"}
        self.assertFalse(allowed(env, event))
        self.assertTrue(guard.allowed(env, event, "someone/NaraHem"))
        # Names compare case-insensitively, as on GitHub.
        self.assertTrue(guard.allowed(env, event, "Someone/narahem"))


if __name__ == "__main__":
    unittest.main()
