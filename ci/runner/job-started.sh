#!/bin/bash
set -euo pipefail
# Installed outside checkout by an administrator; default-deny before any job step.
exec /usr/bin/python3 '/Library/Application Support/NaraHemRunner/guard.py'
