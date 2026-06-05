#!/bin/bash
# Double-click in Finder (macOS) to stop + restart PHA on :8787 and run acceptance checks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

echo "PHA project: $ROOT"
bash "$ROOT/scripts/pha_restart_accept.sh"

echo ""
echo "Open: http://127.0.0.1:8787/"
echo "Log:  ${PHA_RESTART_LOG:-/tmp/pha-8787.log}"
read -r -p "Press Enter to close this window…" _
