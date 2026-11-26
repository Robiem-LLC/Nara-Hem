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
        self.assertEqual(events["push"]["branches"], ["dev"])
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
        self.assertIn("env.METHOD == 'ad-hoc'", delivery["if"])
        self.assertIn("inputs.publish_to_share", delivery["if"])
        self.assertIn("--receipt", delivery["run"])
        self.assertIn('--channel "$GITHUB_REF_NAME"', delivery["run"])
        self.assertLess(steps.index(upload), steps.index(delivery))

    def test_dev_pushes_are_checked_and_releases_are_only_manual(self):
        ios = workflow("ios-mac.yaml")
        job = ios["jobs"]["simulator"]
        steps = job["steps"]
        # dev pushes are Ad Hoc copies for the share, with the simulator tests. A push never goes
        # to TestFlight: only a manual run that chooses app-store does.
        self.assertEqual(
            job["env"]["METHOD"], "${{ github.event_name == 'push' && 'ad-hoc' || inputs.signing }}"
        )
        self.assertNotIn("app-store", job["env"]["METHOD"])
        inputs = ios.get("on", ios.get("true"))["workflow_dispatch"]["inputs"]
        self.assertIn("app-store", inputs["signing"]["options"])
        self.assertIn("github.event_name == 'push'", job["env"]["VALIDATE"])
        self.assertIn("inputs.mode == 'validate'", job["env"]["VALIDATE"])
        sign = next(s for s in steps if s.get("id") == "sign")
        self.assertEqual(sign["if"], "env.METHOD != 'none'")
        self.assertEqual(sign["env"]["SIGNING_METHOD"], "${{ env.METHOD }}")
        sim_test = next(s for s in steps if s.get("name", "").startswith("Run simulator tests"))
        self.assertEqual(sim_test["if"], "env.VALIDATE == 'true'")
        testflight = next(s for s in steps if s.get("id") == "testflight")
        self.assertIn("env.METHOD == 'app-store'", testflight["if"])
        android = workflow("android.yaml")
        android_events = android.get("on", android.get("true"))
        self.assertEqual(android_events["push"]["branches"], ["dev"])
        self.assertFalse(android_events["workflow_dispatch"]["inputs"]["release"]["default"])
        self.assertIn("apps/android/**", android_events["push"]["paths"])
        self.assertIn("VERSION", android_events["push"]["paths"])
        build, release = android["jobs"]["build"], android["jobs"]["release"]
        self.assertIn("refs/heads/dev'", build["if"])
        self.assertNotIn("refs/heads/main'", build["if"])
        self.assertIn("refs/heads/main'", release["if"])
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.release", release["if"])
        self.assertNotIn("'push'", release["if"])
        # A release is made only from a commit signed with an allowed key, and only once.
        checks = "".join(s.get("run", "") for s in release["steps"])
        self.assertIn("allowedSignersFile=.github/allowed_signers", checks)
        self.assertIn('"${signers[@]}" verify-commit', checks)
        self.assertIn('"${signers[@]}" verify-tag', checks)
        publish = next(
            s for s in release["steps"] if s.get("name", "").startswith("Publish the GitHub")
        )
        self.assertEqual(publish["if"], "env.NEW_RELEASE == 'true'")
        gradle = next(
            s
            for s in android["jobs"]["build"]["steps"]
            if s.get("name", "").startswith("Compile Google Maps APK")
        )
        self.assertNotIn("test", gradle["run"])
        site = workflow("showcase.yaml")
        site_events = site.get("on", site.get("true"))
        self.assertEqual(site_events["push"]["branches"], ["main"])
        image = next(
            s for s in site["jobs"]["site"]["steps"] if s.get("name") == "Publish the site image"
        )
        self.assertEqual(image["if"], "github.ref == 'refs/heads/main'")
        linux = workflow("android-tests.yaml")["jobs"]["unit-tests"]["steps"]
        checks = next(s for s in linux if s.get("name", "").startswith("Kotlin style"))
        # assembleGooglePreview runs R8 the way the Play Store release does.
        for task in (
            "testOsmDebugUnitTest",
            "testGoogleDebugUnitTest",
            "lintGoogleDebug",
            "assembleGooglePreview",
        ):
            self.assertIn(task, checks["run"])
        # Every release keeps R8's mapping beside the bundle, for readable Play crash reports.
        android = workflow("android.yaml")["jobs"]
        collect = next(s for s in android["release"]["steps"] if s.get("id") == "collect")
        self.assertIn("mapping/googleRelease/mapping.txt", collect["run"])
        built = next(
            s for s in android["build"]["steps"] if s.get("name") == "Compile Google Maps APK"
        )
        self.assertIn("assembleGooglePreview", built["run"])
