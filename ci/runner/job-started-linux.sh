#!/bin/bash
# The Linux runner container's ACTIONS_RUNNER_HOOK_JOB_STARTED: runs the guard from the read-only
# policy folder before any job step. Default-deny: without the tools it needs, every job is refused.
set -euo pipefail
for tool in python3 git ssh-keygen; do
  command -v "$tool" > /dev/null || {
    echo "Runner refused job: $tool is missing, so the guard can't check it" >&2
    exit 1
  }
done
exec python3 "$(dirname "$0")/guard.py"
