#!/usr/bin/env python3
"""Runs on a self-hosted runner before every job, outside the checkout, and refuses the job unless
all of these hold:

- it comes from the one trusted repository, on main or dev, from a push or a manual run;
- the workflow is one this runner may run, taken from that same branch;
- the account that pushed or started it, and the account GitHub says triggered it, are allowed;
- the commit being built is signed with an allowed SSH key, checked here against a local copy of
  the keys rather than taken from GitHub.

The policy files sit beside this file, root-owned (install-policy.sh writes them). A missing or
unreadable file refuses every job. Defense in depth, not a sandbox for trusted code.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# The policy folder: this file's own, which jobs can't write to.
POLICY = Path(__file__).resolve().parent
# Owner-merged branches only. Pull request heads, forks and other branches stay refused.
TRUSTED_BRANCHES = ("main", "dev")
# Environment passed to git, so a proxy or certificate store the runner needs still works.
NETWORK_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "SSL_CERT_FILE",
    "GIT_SSL_CAINFO",
)


def policy_lines(path):
    """Returns a policy file's lines, without blanks and comments; raises if it has none."""
    lines = [line.strip() for line in path.read_text().splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if not lines:
        raise ValueError(path.name + " lists nothing")
    return lines


def trusted_repository(path=POLICY / "repository"):
    """Returns the repository this runner accepts jobs from."""
    name = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", name):
        raise ValueError("trusted repository file is not owner/name")
    return name


def trusted_actors(path=POLICY / "actors"):
    """Returns the GitHub accounts allowed to start jobs on this runner."""
    names = policy_lines(path)
    if not all(re.fullmatch(r"[A-Za-z0-9-]{1,39}", name) for name in names):
        raise ValueError("actors file holds something other than GitHub account names")
    return names


def trusted_workflows(path=POLICY / "workflows"):
    """Returns the workflow file names this runner may run."""
    names = policy_lines(path)
    if not all(re.fullmatch(r"[A-Za-z0-9._-]+\.ya?ml", name) for name in names):
        raise ValueError("workflows file holds something other than workflow file names")
    return names


def allowed(env, event, repo, actors, workflows):
    """Returns True if the job is a push or manual run of an allowed workflow on a trusted branch of
    the trusted repository, started by an allowed account.
    """

    def same(name, expected):
        """Compares names case-insensitively, as GitHub does."""
        return isinstance(name, str) and name.lower() == expected.lower()

    ref = env.get("GITHUB_REF")
    if not same(env.get("GITHUB_REPOSITORY"), repo) or ref not in [
        "refs/heads/" + b for b in TRUSTED_BRANCHES
    ]:
        return False
    if not same(event.get("repository", {}).get("full_name"), repo):
        return False
    started_by = (
        env.get("GITHUB_ACTOR"),
        env.get("GITHUB_TRIGGERING_ACTOR"),
        event.get("sender", {}).get("login"),
    )
    if not all(any(same(name, actor) for actor in actors) for name in started_by):
        return False
    workflow = env.get("GITHUB_WORKFLOW_REF") or ""
    if same(workflow[: len(repo)], repo):
        workflow = repo + workflow[len(repo) :]
    kind = env.get("GITHUB_EVENT_NAME")
    prefix = repo + "/.github/workflows/"
    # The workflow file must come from the same trusted branch being built.
    if workflow in (prefix + name + "@" + ref for name in workflows):
        return kind in ("push", "workflow_dispatch") and (kind != "push" or event.get("ref") == ref)
    return False


def signed(repo, sha, signers, url=None, git="git", timeout=120):
    """Returns True if the commit is signed with a key in the signers file. Fetches that one commit
    into a throwaway folder and checks it with git and ssh-keygen, so GitHub's word isn't needed.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        return False
    signers = Path(signers).resolve()
    env = {name: os.environ[name] for name in NETWORK_VARIABLES if name in os.environ}
    env |= {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_TERMINAL_PROMPT": "0"}
    with tempfile.TemporaryDirectory() as home:
        env |= {"HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        folder = str(Path(home) / "commit")

        def run(*args):
            """Runs git in the throwaway folder; True if it succeeds."""
            command = [git, "-C", folder, *args]
            return (
                subprocess.run(command, env=env, capture_output=True, timeout=timeout).returncode
                == 0
            )

        os.mkdir(folder)
        source = url or f"https://github.com/{repo}.git"
        return (
            run("init", "--quiet")
            and run("fetch", "--quiet", "--depth=1", "--no-tags", source, sha)
            and run(
                "-c",
                "gpg.format=ssh",
                "-c",
                f"gpg.ssh.allowedSignersFile={signers}",
                "verify-commit",
                sha,
            )
        )


def main():
    """Checks the job against the policy; exits non-zero to refuse it."""
    try:
        repo = trusted_repository()
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if not allowed(os.environ, event, repo, trusted_actors(), trusted_workflows()):
            raise ValueError("repository, branch, event, account or workflow is not allowed")
        policy_lines(POLICY / "allowed_signers")
        if not signed(repo, os.environ.get("GITHUB_SHA"), POLICY / "allowed_signers"):
            raise ValueError("the commit isn't signed with an allowed key")
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        print("Runner refused job: " + str(error), file=sys.stderr)
        sys.exit(1)
    branch = os.environ["GITHUB_REF"].rsplit("/", 1)[-1]
    print("Runner accepted a signed " + branch + " job from " + os.environ["GITHUB_ACTOR"] + ".")


if __name__ == "__main__":
    main()
