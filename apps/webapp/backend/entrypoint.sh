#!/bin/sh
# Nära Hem runs with Docker cap_drop: ALL, cap_add: CHOWN/FOWNER/SETUID/SETGID.
# This privileged setup window exists only to repair a fresh bind mount;
# the actual API and road matcher execute unprivileged thereafter.
set -eu

DATA_DIR="${NARAHEM_DATA_DIR:-/data}"
if [ "$DATA_DIR" != "/data" ]; then
  echo "Nära Hem startup requires NARAHEM_DATA_DIR=/data" >&2
  exit 1
fi
if [ ! -d "$DATA_DIR" ] || [ -L "$DATA_DIR" ]; then
  echo "Nära Hem data mount /data must be a real directory" >&2
  exit 1
fi
if [ "$(stat -c '%u:%g' "$DATA_DIR")" != "10001:10001" ]; then
  chown 10001:10001 "$DATA_DIR" || {
    echo "Cannot set /data ownership; add CHOWN and FOWNER to Nära Hem cap_add" >&2
    exit 1
  }
fi
chmod 0700 "$DATA_DIR" || {
  echo "Cannot secure /data; check Nära Hem cap_add and volume permissions" >&2
  exit 1
}
# Optional readable exports folder (redacted reports only, never keys).
# Unlike /data it is world-readable so a host file share can open reports.
EXPORT_DIR="/exports"
if [ -d "$EXPORT_DIR" ] && [ ! -L "$EXPORT_DIR" ]; then
  if [ "$(stat -c '%u' "$EXPORT_DIR")" != "10001" ]; then
    chown 10001:10001 "$EXPORT_DIR" 2> /dev/null ||
      echo "Note: could not take ownership of /exports; reports there may be unavailable" >&2
  fi
  chmod 0755 "$EXPORT_DIR" 2> /dev/null || true
fi
exec gosu 10001:10001 "$@"
