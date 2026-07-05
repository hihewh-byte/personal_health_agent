#!/usr/bin/env bash
# Stop PHA on PHA_PORT (default from .env).
# P0-4: launchctl bootout when LaunchAgent installed; legacy identity-verified kill otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT/scripts/pha_process_lib.sh"
pha_process_lib_init "$ROOT"

if pha_launchd_enabled; then
  pha_launchd_stop
else
  pha_stop_pha_processes
fi
