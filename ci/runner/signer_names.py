#!/usr/bin/env python3
"""Hides the signing certificate owner's name from CI logs.

Apple names certificates after the developer account, e.g. "Apple Distribution: Name (TEAMID)",
and xcodebuild prints that name. This reads the name from the certificate in IOS_P12_BASE64 and
asks GitHub to mask it for the rest of the job, so the name never has to be in the repository.
"""

import base64
import os
import re
import subprocess
import sys


def names(subject):
    """Returns the owner names in a certificate subject from `openssl x509 -subject`."""
    found = set()
    subject = re.sub(r"^\s*subject\s*=\s*", "", subject)
    for key, value in re.findall(r"(?:^|[/,])\s*(CN|O)\s*=\s*([^/,]+)", subject):
        value = value.strip()
        found.add(value)
        inner = re.fullmatch(r"[^:]+:\s*(.+?)\s*\([A-Z0-9]+\)", value) if key == "CN" else None
        if inner:
            found.add(inner.group(1))
    return sorted(n for n in found if len(n) >= 3)


def subject(p12, password):
    """Returns the certificate subject line from a PKCS#12 file's bytes ("" if unreadable)."""
    env = dict(os.environ, P12_PASSWORD=password)
    certs = subprocess.run(
        ["openssl", "pkcs12", "-nokeys", "-passin", "env:P12_PASSWORD"],
        input=p12,
        capture_output=True,
        env=env,
    ).stdout
    result = subprocess.run(
        ["openssl", "x509", "-noout", "-subject"], input=certs, capture_output=True
    )
    return result.stdout.decode(errors="replace").strip()


def main():
    """Prints one mask command per owner name."""
    p12 = base64.b64decode(os.environ.get("IOS_P12_BASE64", ""))
    for name in names(subject(p12, os.environ.get("IOS_P12_PASSWORD", ""))):
        print("::add-mask::" + name)


if __name__ == "__main__":
    sys.exit(main())
