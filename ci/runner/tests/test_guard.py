import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import guard

REPO = "Example-Org/NaraHem"
PREFIX = REPO + "/.github/workflows/"
ACTORS = ["Owner-Account"]
WORKFLOWS = ["ios-mac.yaml", "android.yaml", "showcase.yaml"]


def allowed(env, event):
    return guard.allowed(env, event, REPO, ACTORS, WORKFLOWS)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": PREFIX + "ios-mac.yaml@refs/heads/main",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_ACTOR": "Owner-Account",
            "GITHUB_TRIGGERING_ACTOR": "Owner-Account",
        }
        self.event = {
            "repository": {"full_name": REPO},
            "ref": "refs/heads/main",
            "sender": {"login": "Owner-Account"},
        }

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

    def test_only_allowed_accounts_may_start_jobs(self):
        # Account names compare case-insensitively, as on GitHub.
        self.assertTrue(allowed(dict(self.env, GITHUB_ACTOR="owner-account"), self.event))
        for name in ("GITHUB_ACTOR", "GITHUB_TRIGGERING_ACTOR"):
            self.assertFalse(allowed(dict(self.env, **{name: "stranger"}), self.event))
            self.assertFalse(allowed({k: v for k, v in self.env.items() if k != name}, self.event))
        self.assertFalse(allowed(self.env, dict(self.event, sender={"login": "stranger"})))
        self.assertFalse(allowed(self.env, {k: v for k, v in self.event.items() if k != "sender"}))
        self.assertFalse(guard.allowed(self.env, self.event, REPO, [], WORKFLOWS))

    def test_only_listed_workflows_run(self):
        self.assertFalse(guard.allowed(self.env, self.event, REPO, ACTORS, ["android.yaml"]))
        self.assertTrue(guard.allowed(self.env, self.event, REPO, ACTORS, ["ios-mac.yaml"]))

    def test_policy_lists_refuse_anything_odd_or_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "list"
            path.write_text("# who may start jobs\nOwner-Account\n\n")
            self.assertEqual(guard.trusted_actors(path), ["Owner-Account"])
            path.write_text("ios-mac.yaml\nandroid.yml\n")
            self.assertEqual(guard.trusted_workflows(path), ["ios-mac.yaml", "android.yml"])
            for bad in ["", "# only a comment", "owner account", "a" * 40]:
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    guard.trusted_actors(path)
            for bad in ["", "../evil.yaml", "script.sh"]:
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    guard.trusted_workflows(path)

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
            "GITHUB_ACTOR": "Owner-Account",
            "GITHUB_TRIGGERING_ACTOR": "Owner-Account",
        }
        event = {
            "repository": {"full_name": "someone/NaraHem"},
            "ref": "refs/heads/main",
            "sender": {"login": "Owner-Account"},
        }
        self.assertFalse(allowed(env, event))
        self.assertTrue(guard.allowed(env, event, "someone/NaraHem", ACTORS, WORKFLOWS))
        # Names compare case-insensitively, as on GitHub.
        self.assertTrue(guard.allowed(env, event, "Someone/narahem", ACTORS, WORKFLOWS))


class SignatureTests(unittest.TestCase):
    """Real commits in a local repository, signed with throwaway SSH keys."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.repo = self.root / "repo"
        self.env = dict(
            os.environ,
            HOME=str(self.root),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        self.owner = self.key("owner")
        self.stranger = self.key("stranger")
        self.signers = self.root / "allowed_signers"
        public = (self.owner.parent / "owner.pub").read_text().strip()
        self.signers.write_text("owner@example.invalid " + public + "\n")
        self.git("init", "--quiet", str(self.repo), cwd=self.root)

    def tearDown(self):
        self.folder.cleanup()

    def key(self, name):
        path = self.root / name
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)],
            check=True,
        )
        return path

    def git(self, *args, cwd=None):
        command = ["git", "-c", "user.name=Owner", "-c", "user.email=owner@example.invalid", *args]
        result = subprocess.run(
            command, cwd=cwd or self.repo, env=self.env, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def commit(self, key=None):
        signing = ["-c", "gpg.format=ssh", "-c", f"user.signingkey={key}"] if key else []
        self.git(
            *signing, "commit", "--quiet", "--allow-empty", "-m", "change", *(["-S"] if key else [])
        )
        return self.git("rev-parse", "HEAD")

    def signed(self, sha):
        return guard.signed(REPO, sha, self.signers, url="file://" + str(self.repo))

    def test_only_commits_signed_with_an_allowed_key_pass(self):
        self.assertTrue(self.signed(self.commit(self.owner)))
        self.assertFalse(self.signed(self.commit(self.stranger)))
        self.assertFalse(self.signed(self.commit()))

    def test_a_relative_path_to_the_keys_still_works(self):
        sha = self.commit(self.owner)
        relative = os.path.relpath(self.signers)
        self.assertTrue(guard.signed(REPO, sha, relative, url="file://" + str(self.repo)))

    def test_missing_or_malformed_commits_are_refused(self):
        self.commit(self.owner)
        self.assertFalse(self.signed("0" * 40))
        for bad in ["", None, "HEAD", "main", "abc123"]:
            self.assertFalse(self.signed(bad))


if __name__ == "__main__":
    unittest.main()
