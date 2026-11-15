import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def workflow(name):
    return json.loads(
        subprocess.check_output(
            [
                "/usr/bin/ruby",
                "-ryaml",
                "-rjson",
                "-e",
                "puts JSON.generate(YAML.load_file(ARGV[0]))",
                str(ROOT / ".github/workflows" / name),
            ]
        )
    )


class WorkflowTests(unittest.TestCase):
    def test_pull_requests_never_name_the_self_hosted_runners(self):
        # Every job a pull request can start picks its runner with the routing expression: local
        # only for the trusted account's own signed pushes and runs on main or dev.
        for path in sorted((ROOT / ".github/workflows").glob("*.yaml")):
            config = workflow(path.name)
            events = config.get("on", config.get("true"))
            if not {"pull_request", "pull_request_target"} & set(events):
                continue
            self.assertNotIn("pull_request_target", events, path.name)
            for name, job in config["jobs"].items():
                runs_on = job["runs-on"]
                self.assertIsInstance(runs_on, str, f"{path.name} {name}")
                for part in (
                    "github.actor == vars.NARAHEM_TRUSTED_ACTOR",
                    "github.triggering_actor == vars.NARAHEM_TRUSTED_ACTOR",
                    "github.ref == 'refs/heads/main' || github.ref == 'refs/heads/dev'",
                    "github.event_name == 'push' || github.event_name == 'workflow_dispatch'",
                    "noreply@github.com",
                    "ubuntu-24.04",
                ):
                    self.assertIn(part, runs_on, f"{path.name} {name}")

    def test_local_only_jobs_skip_commits_made_on_the_website(self):
        for name in ["android.yaml", "ios-mac.yaml", "showcase.yaml", "linux-runner-smoke.yaml"]:
            for job_name, job in workflow(name)["jobs"].items():
                if job_name == "release":
                    continue  # manual runs only; the guard checks the commit
                self.assertIn("noreply@github.com", job["if"], f"{name} {job_name}")

    def test_no_self_hosted_pull_request_events(self):
        for name in ["ios-mac.yaml", "android.yaml"]:
            config = workflow(name)
            events = config.get("on", config.get("true"))
            self.assertFalse({"pull_request", "pull_request_target"} & set(events))
            for job in config["jobs"].values():
                self.assertIn("narahem-ios", job["runs-on"])
                self.assertIn("vars.NARAHEM_TRUSTED_REPOSITORY", job["if"])
        config = workflow("ios-mac.yaml")
        events = config.get("on", config.get("true"))
        self.assertEqual(events["push"]["branches"], ["main", "dev"])
        self.assertIn("apps/ios/**", events["push"]["paths"])
        self.assertEqual(events["workflow_dispatch"]["inputs"]["signing"]["default"], "ad-hoc")

    def test_delivery_requires_verified_adhoc_output_and_retains_github_artifact(self):
        steps = workflow("ios-mac.yaml")["jobs"]["simulator"]["steps"]
        upload = next(
            s for s in steps if s.get("name", "").startswith("Upload verified signed IPA")
        )
        delivery = next(s for s in steps if s.get("id") == "deliver")
        self.assertIn("steps.sign.outputs.ipa", upload["if"])
        self.assertNotIn("*.ipa", upload["with"]["path"])
        self.assertIn("github.event_name == 'push'", delivery["if"])
        self.assertIn("inputs.signing == 'ad-hoc'", delivery["if"])
        self.assertIn("inputs.publish_to_share", delivery["if"])
        self.assertIn("--receipt", delivery["run"])
        self.assertIn('--channel "$GITHUB_REF_NAME"', delivery["run"])
        self.assertLess(steps.index(upload), steps.index(delivery))

    def test_every_platform_push_produces_installable_and_full_validation_is_opt_in(self):
        ios = workflow("ios-mac.yaml")
        steps = ios["jobs"]["simulator"]["steps"]
        sign = next(s for s in steps if s.get("id") == "sign")
        self.assertIn("github.event_name == 'push'", sign["if"])
        self.assertIn("'ad-hoc'", sign["env"]["SIGNING_METHOD"])
        sim_test = next(s for s in steps if s.get("name", "").startswith("Run simulator tests"))
        self.assertIn("inputs.mode == 'validate'", sim_test["if"])
        android = workflow("android.yaml")
        android_events = android.get("on", android.get("true"))
        self.assertEqual(android_events["push"]["branches"], ["main", "dev"])
        self.assertIn("apps/android/**", android_events["push"]["paths"])
        self.assertIn("github.event_name == 'push'", android["jobs"]["build"]["if"])
        gradle = next(
            s
            for s in android["jobs"]["build"]["steps"]
            if s.get("name", "").startswith("Compile Google Maps APK")
        )
        self.assertNotIn("test", gradle["run"])
        linux = workflow("android-tests.yaml")["jobs"]["unit-tests"]["steps"]
        checks = next(s for s in linux if s.get("name", "").startswith("Kotlin style"))
        for task in ("testOsmDebugUnitTest", "testGoogleDebugUnitTest", "lintGoogleDebug"):
            self.assertIn(task, checks["run"])
