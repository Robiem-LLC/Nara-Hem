#!/usr/bin/env python3
"""Defense in depth before checkout; not a sandbox against trusted code/admins."""

import json
import os
import re
import sys
from pathlib import Path

# owner/name of the one repository this runner serves. install-host.sh writes it,
# root-owned, beside this file from the runner's own registration.
REPOSITORY_FILE = Path(__file__).with_name("repository")
# Owner-merged branches only. PR heads, forks and other branches stay refused.
TRUSTED_BRANCHES = ("main", "dev")


def trusted_repository(path=REPOSITORY_FILE):
    """Returns the repository this runner accepts jobs from."""
    name = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", name):
        raise ValueError("trusted repository file is not owner/name")
    return name


def allowed(env, event, repo):
    """Returns True if the job comes from the trusted repository and not from a fork or external
    pull request.
    """

    def same_repo(name):
        """Compares repository names case-insensitively."""
        return isinstance(name, str) and name.lower() == repo.lower()

    prefix = repo + "/.github/workflows/"
    ref = env.get("GITHUB_REF")
    if not same_repo(env.get("GITHUB_REPOSITORY")) or ref not in [
        "refs/heads/" + b for b in TRUSTED_BRANCHES
    ]:
        return False
    if not same_repo(event.get("repository", {}).get("full_name")):
        return False
    workflow = env.get("GITHUB_WORKFLOW_REF") or ""
    if same_repo(workflow[: len(repo)]):
        workflow = repo + workflow[len(repo) :]
    kind = env.get("GITHUB_EVENT_NAME")
    # The workflow file must come from the same trusted branch being built. The showcase
    # workflow films the apps in the iPhone Simulator and Android emulator; it never signs.
    if workflow in (
        prefix + name + "@" + ref for name in ("ios-mac.yaml", "android.yaml", "showcase.yaml")
    ):
        return kind in ("push", "workflow_dispatch") and (kind != "push" or event.get("ref") == ref)
    return False


if __name__ == "__main__":
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if not allowed(os.environ, event, trusted_repository()):
            raise ValueError("repository, workflow, branch, event or source run is not allowlisted")
    except (KeyError, ValueError, OSError) as error:
        print("Runner refused job: " + str(error), file=sys.stderr)
        sys.exit(1)
    print("Runner accepted trusted " + os.environ["GITHUB_REF"].rsplit("/", 1)[-1] + " workflow.")
