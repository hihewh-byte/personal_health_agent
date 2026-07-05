#!/usr/bin/env bash
# Offline PHA regression suite — single entry via selfcheck_manifest.json (P1-4).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" ]]; then
  echo "ERROR: no python3 found" >&2
  exit 1
fi

export PYTHONPATH=.
exec "$PY" scripts/pha_selfcheck_runner.py --python "$PY" "$@"
