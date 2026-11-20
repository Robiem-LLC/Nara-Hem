#!/usr/bin/env python3
"""Publishes the GitHub Release for a version and uploads its files, creating the version tag at the
given commit when the release is new.

Runs on the Mac CI runner with macOS's Python 3.9 and only the standard library. The token is the
job's own GITHUB_TOKEN (contents: write). Running it again for the same version replaces the files.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
VERSION = re.compile(r"\d+\.\d+\.\d+(-(beta|rc)\.\d+)?")
CONTENT_TYPES = {".apk": "application/vnd.android.package-archive", ".aab": "application/zip"}


def release_details(version):
    """Returns the tag, title and pre-release flag for a version such as 1.0.0 or 1.0.0-beta.1."""
    if not VERSION.fullmatch(version):
        raise ValueError("release version must look like 1.0.0 or 1.0.0-beta.1")
    return {"tag_name": "v" + version, "name": "Nära Hem " + version, "prerelease": "-" in version}


def call(method, url, token, body=None, content_type="application/json"):
    """Makes one GitHub API request and returns its decoded JSON answer, if any."""
    data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "Content-Type": content_type,
        "User-Agent": "nara-hem-release",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=300) as response:
        text = response.read()
    return json.loads(text) if text else None


def publish(repo, version, files, token, request=call, target=None):
    """Creates the release if it doesn't exist yet (and its tag, at the commit target), uploads the
    files and returns its page.
    """
    details = release_details(version)
    tag = urllib.parse.quote(details["tag_name"])
    try:
        release = request("GET", f"{API}/repos/{repo}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        body = dict(details, generate_release_notes=True)
        if target:
            body["target_commitish"] = target
        release = request("POST", f"{API}/repos/{repo}/releases", token, body)
    existing = {asset["name"]: asset["id"] for asset in release.get("assets", [])}
    upload = release["upload_url"].split("{")[0]
    for path in files:
        if path.name in existing:
            asset = existing[path.name]
            request("DELETE", f"{API}/repos/{repo}/releases/assets/{asset}", token)
        kind = CONTENT_TYPES.get(path.suffix, "text/plain")
        url = upload + "?name=" + urllib.parse.quote(path.name)
        request("POST", url, token, path.read_bytes(), kind)
    return release["html_url"]


def main(argv=None):
    """Publishes every file in --dir as the release for --version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--target", help="commit to tag when the release is new")
    args = parser.parse_args(argv)
    files = sorted(p for p in args.dir.iterdir() if p.is_file())
    if not files:
        raise SystemExit("nothing to publish in " + str(args.dir))
    print(publish(args.repo, args.version, files, os.environ["GITHUB_TOKEN"], target=args.target))


if __name__ == "__main__":
    sys.exit(main())
