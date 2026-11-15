#!/bin/bash
# Writes the runner guard and its policy into a root-owned folder on a runner's host: the
# repository, the accounts that may start jobs, the workflows this runner may run and the signing
# keys commits must carry. Run with sudo from a checkout you have reviewed; never from Actions.
# Usage: sudo bash ci/runner/install-policy.sh mac|linux POLICY_FOLDER OWNER/REPOSITORY ACCOUNT
#   mac:   POLICY_FOLDER is '/Library/Application Support/NaraHemRunner' (install-host.sh's).
#   linux: POLICY_FOLDER is mounted read-only into the runner container; its job-started.sh is
#          the container's ACTIONS_RUNNER_HOOK_JOB_STARTED.
set -euo pipefail
usage() {
  echo "Usage: sudo bash $0 mac|linux POLICY_FOLDER OWNER/REPOSITORY ACCOUNT" >&2
  exit 2
}
[[ "$EUID" == 0 && $# == 4 ]] || usage
KIND="$1"
POLICY="$2"
REPOSITORY="$3"
ACCOUNT="$4"
HERE="$(cd "$(dirname "$0")" && pwd)"
SIGNERS="$HERE/../../.github/allowed_signers"
case "$KIND" in
  mac)
    GROUP=wheel
    WORKFLOWS='ios-mac.yaml android.yaml showcase.yaml'
    ;;
  linux)
    GROUP=root
    WORKFLOWS='format.yaml container.yaml android-tests.yaml linux-runner-smoke.yaml showcase.yaml'
    ;;
  *) usage ;;
esac
[[ "$POLICY" == /* ]] || {
  echo 'POLICY_FOLDER must be an absolute path' >&2
  exit 2
}
[[ "$REPOSITORY" =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]] || {
  echo 'OWNER/REPOSITORY looks wrong' >&2
  exit 2
}
[[ "$ACCOUNT" =~ ^[A-Za-z0-9-]{1,39}$ ]] || {
  echo 'ACCOUNT must be a GitHub account name' >&2
  exit 2
}
grep -q 'ssh-' "$SIGNERS" || {
  echo "No signing key in $SIGNERS" >&2
  exit 1
}
mkdir -p "$POLICY"
chown root:"$GROUP" "$POLICY"
chmod 755 "$POLICY"
install -o root -g "$GROUP" -m 644 "$HERE/guard.py" "$POLICY/guard.py"
install -o root -g "$GROUP" -m 644 "$SIGNERS" "$POLICY/allowed_signers"
printf '%s\n' "$REPOSITORY" > "$POLICY/repository"
printf '%s\n' "$ACCOUNT" > "$POLICY/actors"
printf '%s\n' $WORKFLOWS > "$POLICY/workflows"
if [[ "$KIND" == linux ]]; then
  install -o root -g "$GROUP" -m 755 "$HERE/job-started-linux.sh" "$POLICY/job-started.sh"
fi
for file in repository actors workflows; do
  chown root:"$GROUP" "$POLICY/$file"
  chmod 644 "$POLICY/$file"
done
echo "Guard installed in $POLICY for $REPOSITORY."
echo "Jobs may be started by: $ACCOUNT"
echo "Workflows this runner runs: $WORKFLOWS"
echo 'Commits must be signed with:'
cut -d' ' -f1-2 "$POLICY/allowed_signers"
