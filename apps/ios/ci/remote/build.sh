#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
# Hold off idle sleep for the lifetime of the build, including an SSH session.
exec /usr/bin/caffeinate -i /usr/bin/python3 "$HERE/build.py" "$@"
