#!/bin/bash
# Refuses to publish an image that lost the settings CI built into it (ci/relay_defaults.py).
# Usage: check-relay-defaults.sh IMAGE EXPECTED_RELAY_DEFAULTS_FILE
set -euo pipefail
image="$1"
expected="$2"
if [[ ! -s "$expected" ]]; then
  echo 'No built-in settings configured; nothing to check.'
  exit 0
fi
if ! docker run --rm --entrypoint cat "$image" /app/narahem/relay-defaults.json | cmp -s - "$expected"; then
  echo '::error::The built image is missing the settings from the secrets. Not publishing.' >&2
  exit 1
fi
echo 'Built-in settings verified inside the image.'
