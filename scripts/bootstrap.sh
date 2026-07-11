#!/usr/bin/env bash
# Clone-to-run bootstrap for Personal Health Agent (PHA).
#
# Default: create/use .venv, install deps, run no-LLM golden run (must PASS).
#
# Usage (from repo root):
#   bash scripts/bootstrap.sh              # first clone — recommended
#   bash scripts/bootstrap.sh --verify-only # skip install; golden run only
#   bash scripts/bootstrap.sh --skip-venv   # use active Python (CI / advanced)
#
# Override Python: PHA_PYTHON=python3.12 bash scripts/bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERIFY_ONLY=0
SKIP_VENV=0

for arg in "$@"; do
  case "$arg" in
    --verify-only) VERIFY_ONLY=1 ;;
    --skip-venv) SKIP_VENV=1 ;;
    -h | --help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

find_python310() {
  local cmd ver major minor
  # Prefer `python` (setup-python / active venv) before versioned binaries (CI mismatch fix).
  for cmd in ${PHA_PYTHON:-} python python3.12 python3.11 python3.10 python3; do
    [[ -n "$cmd" ]] || continue
    if ! command -v "$cmd" >/dev/null 2>&1; then
      continue
    fi
    ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    major="${ver%%.*}"
    minor="${ver#*.}"
    if (( major > 3 || (major == 3 && minor >= 10) )); then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

PY="$(find_python310 || true)"
if [[ -z "${PY:-}" ]]; then
  cat >&2 <<'EOF'
ERROR: Python 3.10+ is required.

macOS often ships python3 = 3.9. Install a newer runtime, then re-run:
  brew install python@3.12
  PHA_PYTHON=python3.12 bash scripts/bootstrap.sh

Linux:
  sudo apt install python3.11 python3.11-venv   # Debian/Ubuntu example
EOF
  exit 1
fi

python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

echo "==> PHA bootstrap (repo: $ROOT)"
echo "==> Python: $("$PY" --version) ($PY)"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  if python_ok python; then
    PY=python
    echo "==> Using active virtualenv: $VIRTUAL_ENV ($(python --version))"
  else
    cat >&2 <<EOF
ERROR: Active virtualenv uses Python < 3.10: $(python --version 2>&1)

  deactivate
  rm -rf .venv
  PHA_PYTHON=$PY bash scripts/bootstrap.sh
EOF
    exit 1
  fi
elif [[ "$SKIP_VENV" -eq 0 ]]; then
  if [[ ! -d "$ROOT/.venv" ]]; then
    echo "==> Creating virtualenv at .venv"
    "$PY" -m venv "$ROOT/.venv"
  fi
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  if ! python_ok python; then
    cat >&2 <<EOF
ERROR: .venv uses Python < 3.10 ($(python --version 2>&1)).

Remove the old venv and re-run bootstrap:
  rm -rf .venv
  PHA_PYTHON=$PY bash scripts/bootstrap.sh
EOF
    exit 1
  fi
  PY=python
  echo "==> Activated .venv ($(python --version))"
else
  if ! python_ok "$PY"; then
    echo "ERROR: $PY is < 3.10 (use PHA_PYTHON=python3.12 or drop --skip-venv)." >&2
    exit 1
  fi
  echo "==> Using system/active Python (--skip-venv)"
fi

if [[ "$VERIFY_ONLY" -eq 0 ]]; then
  echo "==> Upgrading pip / setuptools / wheel"
  "$PY" -m pip install --upgrade pip setuptools wheel

  echo "==> Installing Python dependencies"
  "$PY" -m pip install -r requirements.txt
  "$PY" -m pip install -e .
  "$PY" -m pip install -e packages/harness_core

  if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "==> Created .env from .env.example"
  fi
else
  echo "==> --verify-only: skipping pip install"
fi

echo ""
echo "==> No-LLM golden run (Plan → Tier0 → BuildReport; no Ollama)"
if ! "$PY" scripts/pha_harness_golden_run.py; then
  echo >&2
  echo "ERROR: golden run failed — clone is not verified." >&2
  exit 1
fi

echo ""
echo "==> Environment doctor (--quick; Ollama/Tesseract optional for harness-only)"
if "$PY" scripts/doctor.py --quick; then
  :
else
  echo "WARN: doctor reported issues (chat UI may need Ollama + qwen2.5:7b-instruct)."
fi

cat <<'EOF'

✅ Clone verified — harness control plane runs without an LLM.

Next (full app with chat UI):
  source .venv/bin/activate          # if not already active
  ollama pull qwen2.5:7b-instruct    # ~4–5 GB; skip if already installed
  python -m pha.main                 # → http://127.0.0.1:8788

Re-check anytime:
  bash scripts/bootstrap.sh --verify-only

EOF
