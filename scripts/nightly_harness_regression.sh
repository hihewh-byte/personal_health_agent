#!/usr/bin/env bash
# Nightly Harness regression: Stage 3H 148 mixed battery + Stage 3G Bank 164.
# Prerequisites: PHA on PHA_PORT (default 8788), Ollama/LLM, image assets (PHA_JUN11_ASSETS).
# On failure, pha_universal_attachment_stress_battery.py writes anti-regression-constraints.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export PYTHONPATH=.
export PHA_PORT="${PHA_PORT:-8788}"
export PHA_UNIVERSAL_ATTACHMENT_LANE="${PHA_UNIVERSAL_ATTACHMENT_LANE:-1}"
export PHA_HEALTH_INTENT_CATALOG="${PHA_HEALTH_INTENT_CATALOG:-1}"
SEED="${PHA_NIGHTLY_SEED:-20260626}"
REPORT_ROOT="${PHA_NIGHTLY_REPORT_DIR:-/tmp/pha-nightly-harness}"
mkdir -p "$REPORT_ROOT"

echo "== nightly harness regression seed=$SEED port=$PHA_PORT =="

if ! curl -sf "http://127.0.0.1:${PHA_PORT}/health" >/dev/null; then
  echo "FAIL: PHA not reachable at http://127.0.0.1:${PHA_PORT}/health" >&2
  echo "Start the server before running nightly regression." >&2
  exit 2
fi

STRESS_LOG="$REPORT_ROOT/stress_3h_${SEED}.log"
BANK_LOG="$REPORT_ROOT/bank_3g_${SEED}.log"
EN_LOG="$REPORT_ROOT/en10_${SEED}.log"
FAIL=0

echo "-- Stage 3H mixed battery (148 target) --"
if ! "$PY" scripts/pha_universal_attachment_stress_battery.py \
  --seed="$SEED" \
  --sessions=20 \
  2>&1 | tee "$STRESS_LOG"; then
  echo "FAIL: Stage 3H stress battery" >&2
  FAIL=1
fi

echo "-- Stage 3G Bank battery (164 target) --"
export PHA_E2E_USE_QUESTION_BANK=1
export PHA_E2E_BANK_SEED="$SEED"
export PHA_E2E_REPORT_DIR="$REPORT_ROOT/bank"
mkdir -p "$PHA_E2E_REPORT_DIR"
if ! "$PY" scripts/pha_e2e_browser_battery_20x.py 2>&1 | tee "$BANK_LOG"; then
  echo "FAIL: Stage 3G Bank battery" >&2
  FAIL=1
fi

if [[ "${PHA_NIGHTLY_EN10:-0}" == "1" || "${PHA_E2E_EN_STRESS:-0}" == "1" ]]; then
  echo "-- English RLP EN10 subset (opt-in) --"
  export PHA_E2E_BANK_SEED="${PHA_E2E_BANK_SEED:-20260711}"
  export PHA_E2E_SESSIONS="${PHA_E2E_SESSIONS:-EN01,EN06,EN07,EN08,EN15,EN20,EN39,EN44,EN48,EN50}"
  export PHA_E2E_REPORT_DIR="$REPORT_ROOT/en10"
  mkdir -p "$PHA_E2E_REPORT_DIR"
  if ! "$PY" scripts/pha_e2e_en_stress_50x.py 2>&1 | tee "$EN_LOG"; then
    echo "FAIL: English RLP EN10 subset" >&2
    FAIL=1
  fi
fi

CONSTRAINTS="$ROOT/docs/rfcs/anti-regression-constraints.md"
if [[ -f "$CONSTRAINTS" ]]; then
  cp -f "$CONSTRAINTS" "$REPORT_ROOT/anti-regression-constraints.md"
  echo "constraints snapshot: $REPORT_ROOT/anti-regression-constraints.md"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "==> NIGHTLY HARNESS REGRESSION FAILED (see logs in $REPORT_ROOT)" >&2
  exit 1
fi

echo "==> NIGHTLY HARNESS REGRESSION PASSED"
exit 0
