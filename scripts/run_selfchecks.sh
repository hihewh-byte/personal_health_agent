#!/usr/bin/env bash
# Offline PHA regression suite — single entry via selfcheck_manifest.json (P1-4).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer active/CI python (PHA_PYTHON / python) before repo .venv — avoids stale venv on runners.
if [[ -n "${PHA_PYTHON:-}" ]] && command -v "${PHA_PYTHON}" >/dev/null 2>&1; then
  PY="$(command -v "${PHA_PYTHON}")"
elif command -v python >/dev/null 2>&1 && python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  PY="$(command -v python)"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
if [[ -z "${PY:-}" ]]; then
  echo "ERROR: no python3 found" >&2
  exit 1
fi

export PYTHONPATH=.
# Fail-closed on CJK goldens / alias strings even when runner LANG is C.
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
exec "$PY" scripts/pha_selfcheck_runner.py --python "$PY" "$@"
