#!/usr/bin/env python3
"""Keeps only the newest few build files (Actions artifacts) of each kind, deleting the oldest.

Run it before an upload: for each kind (a name pattern such as "NaraHem-Android-*"), it deletes
all but the newest keep - 1, so after the upload there are keep. GitHub only recounts artifact
storage every 6-12 hours, so this keeps room free ahead of time. Runs on the CI runners with
Python 3.9 and only the standard library; the token needs actions: write.
"""

import argparse
import fnmatch
import os
import sys

from github_release import API, call


def to_delete(artifacts, kind, keep, current_run=None):
    """Returns the artifacts of one kind to delete, oldest first, leaving the newest keep - 1 to
    make room for one more. Expired artifacts and the current run's are left alone.
    """
    same = [
        a
        for a in artifacts
        if fnmatch.fnmatchcase(a["name"], kind)
        and not a.get("expired")
        and (a.get("workflow_run") or {}).get("id") != current_run
    ]
    same.sort(key=lambda a: a["created_at"], reverse=True)
    return list(reversed(same[max(0, keep - 1) :]))


def artifacts(repo, token, request=call):
    """Returns every artifact in the repository."""
    found, page = [], 1
    while True:
        url = f"{API}/repos/{repo}/actions/artifacts?per_page=100&page={page}"
        batch = request("GET", url, token)["artifacts"]
        found += batch
        if len(batch) < 100:
            return found
        page += 1


def main(argv=None):
    """Deletes the oldest build files of each kind given."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--keep", type=int, default=5)
    parser.add_argument("kinds", nargs="+", help="artifact name patterns, e.g. NaraHem-Android-*")
    args = parser.parse_args(argv)
    token = os.environ["GITHUB_TOKEN"]
    run = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None
    stored = artifacts(args.repo, token)
    for kind in args.kinds:
        doomed = to_delete(stored, kind, args.keep, run)
        for artifact in doomed:
            call("DELETE", f"{API}/repos/{args.repo}/actions/artifacts/{artifact['id']}", token)
            print(f"Deleted {artifact['name']} from {artifact['created_at']}")
        print(f"{kind}: kept the newest {args.keep - 1}, deleted {len(doomed)}.")


if __name__ == "__main__":
    sys.exit(main())
