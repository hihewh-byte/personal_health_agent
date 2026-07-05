#!/bin/bash
# Double-click: run PHA in this Terminal window (stays alive). Uses .env PHA_PORT (default 8788).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PORT="${PHA_PORT:-8788}"
HOST="${PHA_HOST:-127.0.0.1}"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: missing $PY — run: python3 -m venv .venv && pip install -r requirements.txt"
  read -r -p "Press Enter to close…" _
  exit 1
fi

echo "PHA — http://${HOST}:${PORT}/ (see build in /health)"
echo "Log also: /tmp/pha-${PORT}.log (if started via restart script)"
echo "Close this window or Ctrl+C to stop PHA."
echo ""

export PYTHONPATH=.
export PHA_HOST="${HOST}"
export PHA_PORT="${PORT}"

exec "$PY" -m pha.main 2>&1 | tee -a "/tmp/pha-${PORT}.log"
