#!/usr/bin/env python3
"""Use approved Actions secrets in a temporary user keychain for one IPA build."""

import argparse
import base64
import os
import secrets
import shlex
import signal
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/ios/ci/remote"))
# The iOS build helpers live with the iOS app, so they are imported by path.
from build import decode_profile, validate_extension_profile, validate_profile  # noqa: E402


def run(*args, capture=False, env=None):
    """Runs a command and prints its error output if it fails."""
    try:
        return subprocess.run(
            [str(a) for a in args], check=True, env=env, stdout=subprocess.PIPE if capture else None
        ).stdout
    except subprocess.CalledProcessError as error:
        # security takes passwords in arguments: never include its argv in errors.
        raise RuntimeError(
            f"{Path(args[0]).name} failed (exit {error.returncode}); arguments withheld"
        ) from None


def main():
    """Creates a temporary keychain with the signing certificate, runs the given command and
    deletes the keychain.
    """
    os.umask(0o077)

    def stop(signum, _frame):
        """Converts a termination signal into SystemExit so cleanup runs."""
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["ad-hoc", "development", "app-store"], required=True)
    args = parser.parse_args()
    values = {
        k: os.environ.pop(k, "")
        for k in [
            "IOS_P12_BASE64",
            "IOS_P12_PASSWORD",
            "IOS_PROFILE_BASE64",
            "IOS_EXTENSION_PROFILE_BASE64",
        ]
    }
    if not all(values.values()):
        parser.error(
            "P12, password, app profile and alert extension profile secrets are required; no "
            "signing performed"
        )
    openssl = Path("/opt/homebrew/opt/openssl@3/bin/openssl")
    if not openssl.is_file():
        parser.error("Install openssl@3 before enabling signing")
    with tempfile.TemporaryDirectory(
        prefix="narahem-signing-", dir=os.environ.get("RUNNER_TEMP")
    ) as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        p12, profile_file = directory / "identity.p12", directory / "profile.mobileprovision"
        extension_file = directory / "extension.mobileprovision"
        p12.write_bytes(base64.b64decode(values["IOS_P12_BASE64"], validate=True))
        data = base64.b64decode(values["IOS_PROFILE_BASE64"], validate=True)
        profile_file.write_bytes(data)
        profile = decode_profile(profile_file)
        validate_profile(profile, args.method)
        extension_data = base64.b64decode(values["IOS_EXTENSION_PROFILE_BASE64"], validate=True)
        extension_file.write_bytes(extension_data)
        extension = decode_profile(extension_file)
        validate_extension_profile(extension, args.method)
        env = dict(
            os.environ,
            NARAHEM_P12_PASSWORD=values["IOS_P12_PASSWORD"],
            NARAHEM_PEM_PASSWORD=secrets.token_urlsafe(48),
        )
        run(
            openssl,
            "pkcs12",
            "-in",
            p12,
            "-passin",
            "env:NARAHEM_P12_PASSWORD",
            "-noout",
            env=env,
        )
        pem, compatible = directory / "encrypted.pem", directory / "compatible.p12"
        run(
            openssl,
            "pkcs12",
            "-in",
            p12,
            "-passin",
            "env:NARAHEM_P12_PASSWORD",
            "-passout",
            "env:NARAHEM_PEM_PASSWORD",
            "-out",
            pem,
            env=env,
        )
        run(
            openssl,
            "pkcs12",
            "-export",
            "-in",
            pem,
            "-out",
            compatible,
            "-passin",
            "env:NARAHEM_PEM_PASSWORD",
            "-passout",
            "env:NARAHEM_P12_PASSWORD",
            "-legacy",
            "-macalg",
            "sha1",
            "-keypbe",
            "PBE-SHA1-3DES",
            "-certpbe",
            "PBE-SHA1-3DES",
            env=env,
        )
        pem.unlink()
        password, keychain = secrets.token_urlsafe(48), directory / "build.keychain-db"
        original = shlex.split(
            run("security", "list-keychains", "-d", "user", capture=True).decode()
        )
        with ExitStack() as cleanup:
            run("security", "create-keychain", "-p", password, keychain)
            cleanup.callback(run, "security", "delete-keychain", keychain)
            run("security", "set-keychain-settings", "-lut", "7200", keychain)
            run("security", "unlock-keychain", "-p", password, keychain)
            cleanup.callback(run, "security", "list-keychains", "-d", "user", "-s", *original)
            run("security", "list-keychains", "-d", "user", "-s", keychain, *original)
            run(
                "security",
                "import",
                compatible,
                "-k",
                keychain,
                "-P",
                values["IOS_P12_PASSWORD"],
                "-T",
                "/usr/bin/codesign",
                "-T",
                "/usr/bin/security",
            )
            run(
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                password,
                keychain,
                capture=True,
            )
            # Make the keychain explicit for find-identity and xcodebuild in a
            # background LaunchDaemon session with no login/default keychain.
            os.environ["NARAHEM_SIGNING_KEYCHAIN"] = str(keychain)
            cleanup.callback(os.environ.pop, "NARAHEM_SIGNING_KEYCHAIN", None)
            for base in [
                Path.home() / "Library/MobileDevice/Provisioning Profiles",
                Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
            ]:
                base.mkdir(parents=True, exist_ok=True)
                for uuid, contents in [
                    (profile["UUID"], data),
                    (extension["UUID"], extension_data),
                ]:
                    installed = base / (uuid + ".mobileprovision")
                    if installed.exists():
                        if installed.read_bytes() != contents:
                            raise ValueError("A different installed profile already uses this UUID")
                    else:
                        with installed.open("xb") as stream:
                            stream.write(contents)
                        installed.chmod(0o600)
                        cleanup.callback(installed.unlink)
            run(
                "/bin/bash",
                ROOT / "apps/ios/ci/remote/build.sh",
                "ipa",
                "--method",
                args.method,
                "--profile",
                profile_file,
                "--extension-profile",
                extension_file,
                "--approve-signing",
            )
        print("Temporary signing keychain removed and original search list restored.")


if __name__ == "__main__":
    main()
