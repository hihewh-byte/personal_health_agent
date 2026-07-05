#!/usr/bin/env bash
# Installed copy lives in ~/Library/Application Support/pha/run-PORT.sh (outside Documents for TCC).
# launchd ProgramArguments target — do not run this template directly.
set -euo pipefail

ROOT="__PHA_ROOT__"
PORT="__PHA_PORT__"
PHA_LAUNCHD_SUPPORT="${HOME}/Library/Application Support/pha"
ENV_FILE="${PHA_LAUNCHD_SUPPORT}/env-${PORT}.sh"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export PYTHONPATH="${ROOT}"
export PHA_HOST="${PHA_HOST:-127.0.0.1}"
export PHA_PORT="${PORT}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"
export PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE:-t0_plus_disclosure}"
export PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE:-warn}"

exec "${ROOT}/.venv/bin/python" -m pha.main
