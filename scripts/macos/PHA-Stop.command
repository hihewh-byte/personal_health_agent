#!/bin/bash
# Double-click in Finder to kill whatever listens on PHA port (default 8787).
set -euo pipefail

PORT="${PHA_PORT:-8787}"

echo "Stopping processes on port ${PORT}…"
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti ":${PORT}" 2>/dev/null || true)
  if [[ -n "${PIDS}" ]]; then
    echo "${PIDS}" | xargs kill -9 2>/dev/null || true
    echo "Done."
  else
    echo "No process on :${PORT}."
  fi
else
  echo "lsof not found." >&2
  exit 1
fi

read -r -p "Press Enter to close…" _
