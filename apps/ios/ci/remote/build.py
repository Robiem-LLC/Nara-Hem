#!/usr/bin/env python3
"""Serialized local/SSH Xcode builds; never imports or unlocks signing keys."""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess as sp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".remote-build"
ENV = dict(os.environ)
ENV["DEVELOPER_DIR"] = ENV.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")

ENV["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + ENV.get(
    "PATH", ""
)

EXTENSION_BUNDLE = "com.robiem.narahem.notifications"
APP_GROUP = "group.com.robiem.narahem.notifications"

# Added to CI run numbers so builds stay above the pre-release builds, which stayed below 1000.
BUILD_OFFSET = 1000


def run(*args, capture=False):
    """Runs a command in the iOS directory and optionally returns its output."""
    result = sp.run(
        [str(a) for a in args], cwd=ROOT, env=ENV, stdout=sp.PIPE if capture else None, check=True
    )
    return result.stdout if capture else None


def decode_profile(path):
    """Verifies a provisioning profile's CMS signature and returns its contents, without a login
    keychain. -noverify skips certificate chain trust, not the signature check; the caller
    validates the profile's contents.
    """
    openssl = Path("/opt/homebrew/opt/openssl@3/bin/openssl")
    return plistlib.loads(
        run(
            openssl,
            "cms",
            "-verify",
            "-noverify",
            "-binary",
            "-inform",
            "DER",
            "-in",
            Path(path).expanduser().resolve(),
            capture=True,
        )
    )


def marketing_version(path=ROOT.parents[1] / "VERSION"):
    """Returns the version people see, from the repository's VERSION file, the same as Android's."""
    version = Path(path).read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("VERSION must look like 1.0.1")
    return version


def bundle_version(number):
    """Converts a CI run number to a valid CFBundleVersion."""
    number = int(number)
    if not 0 <= number < 99990000:
        raise ValueError("Build number is outside CFBundleVersion range")
    return f"{number // 10000 + 1}.{number // 100 % 100}.{number % 100}"


def check_devices(profile, method, label):
    """Checks that Ad Hoc and development profiles list devices and App Store profiles don't."""
    if method == "app-store":
        if profile.get("ProvisionedDevices") or profile.get("ProvisionsAllDevices"):
            raise ValueError(
                label
                + " is not an App Store profile; create an App Store Connect distribution profile"
            )
    elif not profile.get("ProvisionedDevices") or profile.get("ProvisionsAllDevices"):
        raise ValueError(label + " must contain registered devices")


def validate_profile(profile, method, now=None):
    """Checks a provisioning profile's bundle ID, team, signing method, entitlements and expiry."""
    now = now or dt.datetime.now(dt.timezone.utc)
    team = profile["TeamIdentifier"][0]
    ent = profile["Entitlements"]
    development = method == "development"
    if not re.fullmatch(r"[A-Z0-9]{10}", team) or not re.fullmatch(
        r"[A-Fa-f0-9-]{36}", profile["UUID"]
    ):
        raise ValueError("Invalid profile team/UUID")
    if ent.get("application-identifier") != team + ".com.robiem.narahem":
        raise ValueError("Profile must explicitly match com.robiem.narahem")
    check_devices(profile, method, "Profile")
    if bool(ent.get("get-task-allow")) != development or ent.get("aps-environment") != (
        "development" if development else "production"
    ):
        raise ValueError("Profile type/APNs environment does not match selected method")
    if profile["ExpirationDate"].replace(tzinfo=dt.timezone.utc) <= now:
        raise ValueError("Profile is expired")
    if APP_GROUP not in ent.get("com.apple.security.application-groups", []):
        raise ValueError(
            "App profile is missing the shared App Group; regenerate it after enabling App Groups"
        )
    if ent.get("com.apple.developer.usernotifications.time-sensitive") is not True:
        raise ValueError(
            "App profile is missing Time Sensitive Notifications; regenerate it after enabling the "
            "capability"
        )
    return team


def validate_extension_profile(profile, method, now=None):
    """Checks the notification extension's profile: its own bundle ID and the shared App Group,
    without push entitlements.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    team = profile["TeamIdentifier"][0]
    ent = profile["Entitlements"]
    if not re.fullmatch(r"[A-Z0-9]{10}", team) or not re.fullmatch(
        r"[A-Fa-f0-9-]{36}", profile["UUID"]
    ):
        raise ValueError("Invalid extension profile team/UUID")
    if ent.get("application-identifier") != team + "." + EXTENSION_BUNDLE:
        raise ValueError("Extension profile must explicitly match " + EXTENSION_BUNDLE)
    check_devices(profile, method, "Extension profile")
    if bool(ent.get("get-task-allow")) != (method == "development"):
        raise ValueError("Extension profile type does not match selected method")
    if APP_GROUP not in ent.get("com.apple.security.application-groups", []):
        raise ValueError("Extension profile is missing the shared App Group")
    if profile["ExpirationDate"].replace(tzinfo=dt.timezone.utc) <= now:
        raise ValueError("Extension profile is expired")
    return team


def simulator(requested=None):
    """Returns the iPhone simulator to build and test on."""
    devices = json.loads(run("xcrun", "simctl", "list", "devices", "available", "-j", capture=True))
    phones = [
        (runtime, d)
        for runtime, group in devices["devices"].items()
        for d in group
        if d.get("isAvailable") and d["name"].startswith("iPhone")
    ]
    # Prefer the stable iOS 17.2 runtime over the problematic iOS 27.1 simulator.
    preferred = next(
        (
            d["udid"]
            for runtime, d in phones
            if runtime.endswith("iOS-17-2") and d["name"] == "iPhone 15 Pro"
        ),
        None,
    )
    device = requested or preferred or (phones[0][1]["udid"] if phones else None)
    if not device or device not in [d["udid"] for _, d in phones]:
        sys.exit(
            "No matching available iPhone simulator. Install a runtime in Xcode Settings > "
            "Components."
        )
    return device


def main():
    """Command line entry point: doctor, build, test, ipa or showcase-build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["doctor", "build", "test", "ipa", "showcase-build"])
    parser.add_argument("--method", choices=["development", "ad-hoc", "app-store"])
    parser.add_argument("--profile", type=Path, help="Already installed .mobileprovision file")
    parser.add_argument(
        "--extension-profile", type=Path, help="Installed profile for the alert extension"
    )
    parser.add_argument(
        "--approve-signing", action="store_true", help="Explicit approval to sign locally"
    )
    parser.add_argument("--device", help="Simulator UDID for tests")
    args = parser.parse_args()
    if args.action == "ipa" and not (
        args.approve_signing and args.method and args.profile and args.extension_profile
    ):
        parser.error(
            "ipa requires --approve-signing, --method, --profile and --extension-profile; "
            "credentials must already be installed"
        )
    OUT.mkdir(exist_ok=True, mode=0o700)
    with (OUT / "build.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Another remote build is running; retry after it finishes.")
        run("xcodebuild", "-version")
        run("xcodegen", "--version")
        if args.action == "doctor":
            run("xcodebuild", "-checkFirstLaunchStatus")
            run("xcrun", "simctl", "list", "devices", "available")
            run("security", "find-identity", "-v", "-p", "codesigning")
            return
        stamp = dt.datetime.now(dt.timezone.utc)
        folder = OUT / (stamp.strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid()))
        folder.mkdir(mode=0o700)
        spec = json.loads(
            run(
                "/usr/bin/ruby",
                "-ryaml",
                "-rjson",
                "-e",
                "puts JSON.generate(YAML.load_file(ARGV[0]))",
                ROOT / "project.yml",
                capture=True,
            )
        )
        for name, target in spec["targets"].items():
            for source in target.get("sources", []):
                source["path"] = str(ROOT / source["path"])
            if "info" in target:
                target["info"]["path"] = str(folder / f"{name}-Info.plist")
            base = target.get("settings", {}).get("base", {})
            if "CODE_SIGN_ENTITLEMENTS" in base:
                base["CODE_SIGN_ENTITLEMENTS"] = str(ROOT / base["CODE_SIGN_ENTITLEMENTS"])
        app = spec["targets"]["NaraHem"]["settings"]
        app["base"]["NARAHEM_BUILD_UTC"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        commit = run("git", "rev-parse", "--short=10", "HEAD", capture=True).decode().strip()
        if run("git", "status", "--porcelain", "--untracked-files=no", capture=True).strip():
            commit += "-dirty"
        app["base"]["NARAHEM_BUILD_COMMIT"] = commit
        app["base"]["MARKETING_VERSION"] = marketing_version()
        app["base"]["CURRENT_PROJECT_VERSION"] = bundle_version(
            int(ENV.get("GITHUB_RUN_NUMBER", int(stamp.timestamp()) // 60)) + BUILD_OFFSET
        )
        extension = spec["targets"]["NaraHemNotifications"]["settings"]
        # An app extension must carry exactly its app's version numbers.
        for setting in ("CURRENT_PROJECT_VERSION", "MARKETING_VERSION"):
            extension["base"][setting] = app["base"][setting]
        maps_key = ENV.get("NARAHEM_GOOGLE_MAPS_IOS_API_KEY")
        if maps_key:
            if not re.fullmatch(r"AIza[A-Za-z0-9_-]+", maps_key):
                sys.exit("Invalid Google Maps API key format")
            app["base"]["NARAHEM_GOOGLE_MAPS_IOS_API_KEY"] = maps_key
        profile = None
        if args.action == "ipa":
            (OUT / "signed-ipa.json").unlink(missing_ok=True)
            profile = decode_profile(args.profile)
            team = validate_profile(profile, args.method, stamp)
            extension_profile = decode_profile(args.extension_profile)
            if validate_extension_profile(extension_profile, args.method, stamp) != team:
                sys.exit("App and alert extension profiles belong to different teams")
            development = args.method == "development"
            expected_apns = "development" if development else "production"
            signing_keychain = ENV.get("NARAHEM_SIGNING_KEYCHAIN")
            identity_args = ["security", "find-identity", "-v", "-p", "codesigning"]
            if signing_keychain:
                identity_args.append(signing_keychain)
            identities = run(*identity_args, capture=True).decode()
            hashes = [
                hashlib.sha1(cert).hexdigest().upper()
                for cert in profile.get("DeveloperCertificates", [])
            ]
            identity = next((value for value in hashes if value in identities), None)
            if not identity:
                valid = re.search(r"([0-9]+) valid identities found", identities)
                count = int(valid.group(1)) if valid else -1
                if count == 0:
                    sys.exit(
                        "No valid code-signing identity (certificate AND private key) found in the "
                        "temporary signing keychain"
                    )
                sys.exit(
                    "Signing certificate/private key exists, but its fingerprint does not match "
                    "any DeveloperCertificates in the provisioning profile"
                )
            app["configs"]["Release"].update(
                {
                    "CODE_SIGN_STYLE": "Manual",
                    "CODE_SIGN_IDENTITY": identity,
                    "DEVELOPMENT_TEAM": team,
                    "PROVISIONING_PROFILE_SPECIFIER": profile["UUID"],
                    "NARAHEM_APNS_ENVIRONMENT": expected_apns,
                }
            )
            extension["configs"]["Release"].update(
                {
                    "CODE_SIGN_STYLE": "Manual",
                    "CODE_SIGN_IDENTITY": identity,
                    "DEVELOPMENT_TEAM": team,
                    "PROVISIONING_PROFILE_SPECIFIER": extension_profile["UUID"],
                }
            )
        if args.action == "showcase-build":
            # Showcase only: a UI test that films the app (tools/showcase). Never in app builds.
            spec["targets"]["NaraHemShowcase"] = {
                "type": "bundle.ui-testing",
                "platform": "iOS",
                "sources": [{"path": str(ROOT / "Showcase")}],
                "dependencies": [{"target": "NaraHem"}],
                "settings": {
                    "base": {
                        "PRODUCT_BUNDLE_IDENTIFIER": "com.robiem.narahem.showcase",
                        "TARGETED_DEVICE_FAMILY": "1",
                        "GENERATE_INFOPLIST_FILE": "YES",
                        "TEST_TARGET_NAME": "NaraHem",
                    }
                },
            }
            spec["schemes"] = {
                "NaraHemShowcase": {
                    "build": {"targets": {"NaraHem": "all", "NaraHemShowcase": ["test"]}},
                    "test": {"config": "Debug", "targets": ["NaraHemShowcase"]},
                }
            }
        spec_path = folder / "project.json"
        spec_path.write_text(json.dumps(spec))
        run("xcodegen", "generate", "--spec", spec_path, "--project", folder)
        common = [
            "xcodebuild",
            "-project",
            folder / "NaraHem.xcodeproj",
            "-scheme",
            "NaraHem",
            "-derivedDataPath",
            OUT / "DerivedData",
        ]
        if args.action == "showcase-build":
            products = OUT / "showcase"
            shutil.rmtree(products, ignore_errors=True)
            device = simulator(args.device)
            run(
                "xcodebuild",
                "-project",
                folder / "NaraHem.xcodeproj",
                "-scheme",
                "NaraHemShowcase",
                "-derivedDataPath",
                products,
                "-configuration",
                "Debug",
                "-destination",
                "platform=iOS Simulator,id=" + device,
                # "Sign to Run Locally": no certificate or profile, but the app gets the
                # simulator entitlements it needs to keep its device keys in the Keychain.
                "ARCHS=arm64",
                "-jobs",
                "4",
                "CODE_SIGN_IDENTITY=-",
                "CODE_SIGN_STYLE=Manual",
                "DEVELOPMENT_TEAM=",
                "PROVISIONING_PROFILE_SPECIFIER=",
                "build-for-testing",
            )
            (xctestrun,) = (products / "Build/Products").glob("*.xctestrun")
            print("SHOWCASE_XCTESTRUN=" + str(xctestrun))
            print("SHOWCASE_SIMULATOR=" + device)
        elif args.action == "build":
            run(
                *common,
                "-configuration",
                "Debug",
                "-destination",
                "generic/platform=iOS Simulator",
                "ARCHS=arm64",
                "-jobs",
                "4",
                "CODE_SIGNING_ALLOWED=NO",
                "build",
            )
        elif args.action == "test":
            device = simulator(args.device)
            run(
                *common,
                "-configuration",
                "Debug",
                "-destination",
                "platform=iOS Simulator,id=" + device,
                "-parallel-testing-enabled",
                "NO",
                "-jobs",
                "4",
                "ARCHS=arm64",
                "CODE_SIGNING_ALLOWED=NO",
                "-enableCodeCoverage",
                "YES",
                "-resultBundlePath",
                folder / "Tests.xcresult",
                "test",
            )
            # Line coverage per target and file, for the CI log.
            run("xcrun", "xccov", "view", "--report", folder / "Tests.xcresult")
        else:
            archive = folder / "NaraHem.xcarchive"
            archive_args = [
                "-configuration",
                "Release",
                "-destination",
                "generic/platform=iOS",
                "-archivePath",
                archive,
            ]
            if signing_keychain:
                archive_args.append("OTHER_CODE_SIGN_FLAGS=--keychain " + signing_keychain)
            run(*common, *archive_args, "archive")
            options = folder / "ExportOptions.plist"
            options.write_bytes(
                plistlib.dumps(
                    {
                        "method": {
                            "development": "debugging",
                            "ad-hoc": "release-testing",
                            "app-store": "app-store-connect",
                        }[args.method],
                        "destination": "export",
                        "signingStyle": "manual",
                        "teamID": team,
                        "signingCertificate": "Apple Development"
                        if development
                        else "Apple Distribution",
                        "provisioningProfiles": {
                            "com.robiem.narahem": profile["UUID"],
                            EXTENSION_BUNDLE: extension_profile["UUID"],
                        },
                        "thinning": "<none>",
                    }
                )
            )
            run(
                "xcodebuild",
                "-exportArchive",
                "-archivePath",
                archive,
                "-exportOptionsPlist",
                options,
                "-exportPath",
                folder / "export",
            )
            (ipa,) = (folder / "export").glob("*.ipa")
            verify = folder / "verify"
            run("ditto", "-x", "-k", ipa, verify)
            embedded_app = verify / "Payload/NaraHem.app"
            run("codesign", "--verify", "--deep", "--strict", embedded_app)
            embedded = decode_profile(embedded_app / "embedded.mobileprovision")
            if embedded["UUID"] != profile["UUID"]:
                sys.exit("Exported IPA has unexpected provisioning profile")
            signed = plistlib.loads(
                run("codesign", "-d", "--entitlements", ":-", embedded_app, capture=True)
            )
            if (
                signed.get("aps-environment") != expected_apns
                or signed.get("application-identifier") != team + ".com.robiem.narahem"
            ):
                sys.exit(
                    "Exported IPA signature has unexpected capabilities or application identifier"
                )
            if bool(signed.get("get-task-allow")) != development:
                sys.exit("Exported IPA has the wrong debug entitlement")
            embedded_extension = embedded_app / "PlugIns/NaraHemNotifications.appex"
            if (
                decode_profile(embedded_extension / "embedded.mobileprovision")["UUID"]
                != extension_profile["UUID"]
            ):
                sys.exit("Exported alert extension has unexpected provisioning profile")
            extension_signed = plistlib.loads(
                run("codesign", "-d", "--entitlements", ":-", embedded_extension, capture=True)
            )
            if (
                extension_signed.get("application-identifier") != team + "." + EXTENSION_BUNDLE
                or APP_GROUP
                not in extension_signed.get("com.apple.security.application-groups", [])
                or APP_GROUP not in signed.get("com.apple.security.application-groups", [])
            ):
                sys.exit("Exported app or alert extension is missing the shared App Group")
            info = plistlib.loads((embedded_app / "Info.plist").read_bytes())
            if info.get("CFBundleIdentifier") != "com.robiem.narahem":
                sys.exit("Exported IPA has the wrong bundle identifier")
            # App Store Connect rejects iPad-capable builds without every orientation (ITMS-90474).
            if info.get("UIDeviceFamily") != [1] or not info.get(
                "UISupportedInterfaceOrientations"
            ):
                sys.exit("Exported IPA must be iPhone-only with declared orientations")
            receipt = {
                "type": "signed-device-ipa",
                "method": args.method,
                "ipa": str(ipa),
                "commit": run("git", "rev-parse", "HEAD", capture=True).decode().strip(),
                "sha256": hashlib.sha256(ipa.read_bytes()).hexdigest(),
                "profile_uuid": profile["UUID"],
                "team": team,
                "bundle_id": info["CFBundleIdentifier"],
            }
            receipt_path = OUT / "signed-ipa.json"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            if ENV.get("GITHUB_OUTPUT"):
                with open(ENV["GITHUB_OUTPUT"], "a") as output:
                    output.write(f"ipa={ipa}\nreceipt={receipt_path}\n")
            print("IPA:", ipa)
        print("Build output:", folder)


if __name__ == "__main__":
    try:
        main()
    except sp.CalledProcessError as error:
        sys.exit(error.returncode)
