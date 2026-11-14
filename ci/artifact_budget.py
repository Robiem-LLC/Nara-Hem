#!/usr/bin/env python3
"""Keeps this repository's build files (Actions artifacts) under a storage budget, deleting the
oldest first.

GitHub counts artifact storage for the whole organization and only recalculates it every 6-12
hours, so a failed upload can't simply be retried. Running this before each upload keeps room
free instead. Runs on the CI runners with Python 3.9 and only the standard library; the token
needs actions: write.
"""

import argparse
import glob
import os
import sys
from pathlib import Path

from github_release import API, call

MIB = 1024 * 1024


def to_delete(artifacts, budget, current_run=None):
    """Returns the artifacts to delete, oldest first, so the newest ones fit in budget bytes.
    Expired artifacts take no space; the current run's are never deleted.
    """
    live = [a for a in artifacts if not a.get("expired")]
    live.sort(key=lambda a: a["created_at"], reverse=True)
    kept, doomed = 0, []
    for artifact in live:
        own = (artifact.get("workflow_run") or {}).get("id") == current_run
        if own or (not doomed and kept + artifact["size_in_bytes"] <= budget):
            kept += artifact["size_in_bytes"]
        else:
            doomed.append(artifact)
    return list(reversed(doomed))


def size_of(patterns):
    """Returns the total size in bytes of the files matching the patterns (folders included)."""
    total = 0
    for pattern in patterns:
        for match in glob.glob(pattern, recursive=True):
            path = Path(match)
            files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
            total += sum(f.stat().st_size for f in files)
    return total


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
    """Deletes the oldest artifacts until the newest fit in the budget minus what's about to be
    uploaded.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--budget-mb", type=float, default=250)
    parser.add_argument("--reserve", nargs="*", default=[], help="files about to be uploaded")
    args = parser.parse_args(argv)
    token = os.environ["GITHUB_TOKEN"]
    reserve = size_of(args.reserve)
    budget = max(0, int(args.budget_mb * MIB) - reserve)
    run = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None
    doomed = to_delete(artifacts(args.repo, token), budget, run)
    for artifact in doomed:
        call("DELETE", f"{API}/repos/{args.repo}/actions/artifacts/{artifact['id']}", token)
        print(f"Deleted {artifact['name']} ({artifact['size_in_bytes'] / MIB:.1f} MiB)")
    print(f"Made room for {reserve / MIB:.1f} MiB; {len(doomed)} old build files deleted.")


if __name__ == "__main__":
    sys.exit(main())
