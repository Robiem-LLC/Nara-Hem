#!/bin/bash
# Review the PR first. Run locally with sudo; never invoke from Actions.
# Usage: sudo bash ci/runner/install-host.sh /absolute/path/to/registered-runner
set -euo pipefail
[[ "$EUID" == 0 && $# == 1 ]] || {
  echo "Usage: sudo bash $0 REGISTERED_RUNNER_DIRECTORY" >&2
  exit 2
}
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGING="$1"
ACCOUNT=narahemci
RUNNER=/Users/narahemci/actions-runner
POLICY='/Library/Application Support/NaraHemRunner'
PLIST=/Library/LaunchDaemons/com.narahem.github-runner.plist
[[ -f "$STAGING/.runner" && -f "$STAGING/.credentials" ]] || {
  echo 'Expected a registered runner directory' >&2
  exit 1
}
# The registration names the one repository this runner serves; the guard trusts only that.
REPOSITORY="$(
  /usr/bin/python3 - "$STAGING/.runner" << 'PY'
import json, re, sys
with open(sys.argv[1], encoding='utf-8-sig') as stream:
    data = json.load(stream)
match = re.fullmatch(r'https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)', data.get('gitHubUrl', '').rstrip('/'))
if (data.get('agentName') != 'narahem-ios-mac-mini' or not match
        or data.get('workFolder') != '/Users/narahemci/actions-work'):
    raise SystemExit('Staged runner/repository/work directory mismatch')
print(match.group(1))
PY
)"
[[ ! -e "$RUNNER" && ! -e "$PLIST" ]] || {
  echo 'Installation exists; refusing overwrite' >&2
  exit 1
}
if ! id "$ACCOUNT" > /dev/null 2>&1; then
  echo 'Create the dedicated standard account; enter a new account password at the local prompt.'
  /usr/sbin/sysadminctl -addUser "$ACCOUNT" -fullName 'NaraHem CI Runner' \
    -home /Users/narahemci -shell /bin/zsh -password -
fi
id "$ACCOUNT" > /dev/null
if /usr/bin/id -Gn "$ACCOUNT" | /usr/bin/grep -Eq '(^| )admin( |$)'; then
  echo 'Refusing to use an administrator account' >&2
  exit 1
fi
mkdir -p /Users/narahemci "$POLICY" /Users/narahemci/actions-work /Users/narahemci/runner-logs
chown "$ACCOUNT":staff /Users/narahemci /Users/narahemci/actions-work /Users/narahemci/runner-logs
chmod 700 /Users/narahemci /Users/narahemci/actions-work /Users/narahemci/runner-logs
/usr/bin/ditto "$STAGING" "$RUNNER"
chown -R "$ACCOUNT":staff "$RUNNER"
chmod -R go-w "$RUNNER"
chmod 700 "$RUNNER"
for file in .credentials .credentials_rsaparams; do
  if [[ -f "$RUNNER/$file" ]]; then
    chown "$ACCOUNT":staff "$RUNNER/$file"
    chmod 600 "$RUNNER/$file"
  fi
done
mkdir -p "$RUNNER/_diag"
chown -R "$ACCOUNT":staff "$RUNNER/_diag"
install -o root -g wheel -m 755 "$HERE/job-started.sh" "$POLICY/job-started.sh"
# Runner hooks must use a real executable with a space-free pathname.
mkdir -p /usr/local/libexec
install -o root -g wheel -m 755 "$HERE/job-started.sh" /usr/local/libexec/narahem-job-started.sh
install -o root -g wheel -m 644 "$HERE/guard.py" "$POLICY/guard.py"
printf '%s\n' "$REPOSITORY" > "$POLICY/repository"
chown root:wheel "$POLICY/repository"
chmod 644 "$POLICY/repository"
# The external policy remains root-owned; the supported runner needs writable runtime/update state.
printf '%s\n' "ACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/libexec/narahem-job-started.sh" > "$RUNNER/.env"
printf '%s\n' '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin' > "$RUNNER/.path"
chmod 644 "$RUNNER/.env" "$RUNNER/.path"
/usr/bin/python3 - "$RUNNER/.runner" << 'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8-sig') as stream:
    data = json.load(stream)
data['disableUpdate'] = False
with open(sys.argv[1], 'w') as stream:
    json.dump(data, stream, indent=2)
PY
if [[ ! -e "$POLICY/publish.json" ]]; then
  install -o root -g wheel -m 644 "$HERE/../publish/config.example.json" "$POLICY/publish.json"
fi
/usr/bin/python3 - "$PLIST" << 'PY'
import plistlib, sys
runner = '/Users/narahemci/actions-runner'
config = {
    'Label': 'com.narahem.github-runner',
    'UserName': 'narahemci', 'GroupName': 'staff',
    'ProgramArguments': ['/usr/bin/caffeinate', '-i', '/bin/bash', runner + '/bin/runsvc.sh'],
    'WorkingDirectory': runner,
    'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
    'SessionCreate': True, 'ProcessType': 'Background',
    'EnvironmentVariables': {
        'HOME': '/Users/narahemci',
        'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        'ACTIONS_RUNNER_SVC': '1',
        'DEVELOPER_DIR': '/Applications/Xcode.app/Contents/Developer',
        'ACTIONS_RUNNER_HOOK_JOB_STARTED': '/usr/local/libexec/narahem-job-started.sh',
    },
    'StandardOutPath': '/Users/narahemci/runner-logs/stdout.log',
    'StandardErrorPath': '/Users/narahemci/runner-logs/stderr.log',
}
with open(sys.argv[1], 'wb') as stream:
    plistlib.dump(config, stream)
PY
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
/usr/bin/plutil -lint "$PLIST"
echo 'Installed but NOT started. No sudoers, SSH, firewall, power, or signing settings changed.'
echo 'After PR review/merge and security review, approve activation separately:'
echo "sudo launchctl bootstrap system $PLIST"
echo 'Then verify simulator access as narahemci; a user-login LaunchAgent may be needed on this macOS release.'
