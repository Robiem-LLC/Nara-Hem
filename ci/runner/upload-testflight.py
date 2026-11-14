#!/usr/bin/env python3
"""Upload one verified App Store IPA to App Store Connect (TestFlight) with an API key.

The .p8 key exists only in a private temporary folder for the duration of the upload.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def credentials(environ):
    """Removes the App Store Connect key from the environment and returns it, so child processes
    never see it.
    """
    values = {
        k: environ.pop(k, "").strip()
        for k in [
            "APP_STORE_CONNECT_API_KEY_ID",
            "APP_STORE_CONNECT_ISSUER_ID",
            "APP_STORE_CONNECT_API_KEY_P8",
        ]
    }
    key_id, issuer, key = (
        values[k]
        for k in [
            "APP_STORE_CONNECT_API_KEY_ID",
            "APP_STORE_CONNECT_ISSUER_ID",
            "APP_STORE_CONNECT_API_KEY_P8",
        ]
    )
    if not re.fullmatch(r"[A-Z0-9]{10}", key_id):
        raise ValueError("APP_STORE_CONNECT_API_KEY_ID must be the 10-character key ID")
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", issuer
    ):
        raise ValueError(
            "APP_STORE_CONNECT_ISSUER_ID must be the issuer UUID shown above the keys list"
        )
    if not (
        key.startswith("-----BEGIN PRIVATE KEY-----") and key.endswith("-----END PRIVATE KEY-----")
    ):
        raise ValueError(
            "APP_STORE_CONNECT_API_KEY_P8 must be the full contents of the downloaded AuthKey .p8 "
            "file"
        )
    return key_id, issuer, key


def upload(ipa, key_id, issuer, key, run=subprocess.run):
    """Uploads an IPA with altool, using a private temporary directory for the key."""
    with tempfile.TemporaryDirectory(
        prefix="narahem-asc-", dir=os.environ.get("RUNNER_TEMP")
    ) as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        keys = directory / "private_keys"
        keys.mkdir(mode=0o700)
        key_file = keys / f"AuthKey_{key_id}.p8"
        with key_file.open("x") as stream:
            stream.write(key + "\n")
        key_file.chmod(0o600)
        # altool looks for AuthKey_<ID>.p8 in API_PRIVATE_KEYS_DIR (and ./private_keys).
        env = dict(os.environ, API_PRIVATE_KEYS_DIR=str(keys))
        result = run(
            [
                "xcrun",
                "altool",
                "--upload-app",
                "--type",
                "ios",
                "--file",
                str(ipa),
                "--apiKey",
                key_id,
                "--apiIssuer",
                issuer,
            ],
            cwd=directory,
            env=env,
        )
    return result.returncode


def main():
    """Command line entry point: uploads one IPA to TestFlight."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipa", type=Path, required=True)
    args = parser.parse_args()
    if args.ipa.suffix != ".ipa" or not args.ipa.is_file():
        parser.error("--ipa must be an exported .ipa file")
    try:
        key_id, issuer, key = credentials(os.environ)
    except ValueError as error:
        parser.error(str(error))
    code = upload(args.ipa, key_id, issuer, key)
    if code:
        sys.exit(f"App Store Connect upload failed (exit {code})")
    print(
        "Uploaded to App Store Connect. The build appears in TestFlight after Apple finishes "
        "processing it."
    )


if __name__ == "__main__":
    main()
