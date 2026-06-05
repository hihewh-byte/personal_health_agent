#!/usr/bin/env bash
# Restart PHA on 127.0.0.1:8787 and run curl acceptance checks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PHA_PORT:-8787}"
HOST="${PHA_HOST:-127.0.0.1}"
BASE="http://${HOST}:${PORT}"
LOG="${PHA_RESTART_LOG:-/tmp/pha-${PORT}.log}"
PIDFILE="${PHA_RESTART_PIDFILE:-/tmp/pha-${PORT}.pid}"
WAIT_SECS="${PHA_RESTART_WAIT_SECS:-45}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: missing venv python at $PY" >&2
  exit 1
fi

echo "==> Stopping anything on :${PORT}"
if command -v lsof >/dev/null 2>&1; then
  lsof -ti ":${PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true
fi
sleep 1

echo "==> Starting PHA (PYTHONPATH=. $PY -m pha.main)"
export PYTHONPATH=.
# Homebrew Tesseract (Stage 3A OCR) — required on PATH for pytesseract
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
# Production numerics tier (Manifest Tier v1) — rollback: PHA_NUMERICS_AUDIT_SCOPE=t0_strict
export PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE:-t0_plus_disclosure}"
export PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE:-warn}"
echo "    PHA_NUMERICS_AUDIT_SCOPE=${PHA_NUMERICS_AUDIT_SCOPE}"
echo "    PHA_NUMERICS_T1_M4_MODE=${PHA_NUMERICS_T1_M4_MODE}"
nohup env PYTHONPATH=. PATH="${PATH}" \
  PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE}" \
  PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE}" \
  "$PY" -m pha.main >>"$LOG" 2>&1 </dev/null &
PHA_PID=$!
echo "$PHA_PID" >"$PIDFILE"
disown "$PHA_PID" 2>/dev/null || true
echo "    pid=${PHA_PID} log=$LOG"
sleep 1
if ! kill -0 "$PHA_PID" 2>/dev/null; then
  echo "ERROR: PHA exited immediately after start; tail log:" >&2
  tail -n 40 "$LOG" >&2 || true
  exit 1
fi

echo "==> Waiting for ${BASE}/health (max ${WAIT_SECS}s)"
ready=0
for ((i = 1; i <= WAIT_SECS; i++)); do
  if curl -sf "${BASE}/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "ERROR: server did not become ready; tail log:" >&2
  tail -n 40 "$LOG" >&2 || true
  exit 1
fi

fail=0
check() {
  local name="$1"
  shift
  if "$@"; then
    echo "OK  $name"
  else
    echo "FAIL $name" >&2
    fail=1
  fi
}

echo "==> Curl acceptance"
HEALTH_JSON="$(curl -sf "${BASE}/health")"
echo "    /health => $HEALTH_JSON"
check "/health JSON" test -n "$HEALTH_JSON"
check "/health has pha_build" echo "$HEALTH_JSON" | grep -q '"pha_build"'

check "GET /" curl -sf "${BASE}/" -o /dev/null
check "GET /api/chat/config" curl -sf "${BASE}/api/chat/config" -o /dev/null

REF_END="$(date +%Y-%m-%d)"
REF_START="$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d '7 days ago' +%Y-%m-%d)"
DATA_URL="${BASE}/health/data?user_id=default&start_date=${REF_START}&end_date=${REF_END}&metrics=hrv,activity_kcal"
DATA_JSON="$(curl -sf "$DATA_URL")"
echo "    /health/data => $(echo "$DATA_JSON" | head -c 200)…"
check "/health/data JSON" test -n "$DATA_JSON"
check "/health/data metrics field" echo "$DATA_JSON" | grep -q '"metrics"'

EXPECTED_BUILD="$("$PY" -c "from pha.build_marker import PHA_SERVER_BUILD; print(PHA_SERVER_BUILD)" 2>/dev/null || true)"
ASSET_VER="$("$PY" -c "from pha.build_marker import asset_cache_version; print(asset_cache_version())" 2>/dev/null || true)"
if [[ -n "$EXPECTED_BUILD" ]]; then
  check "/health build matches build_marker" echo "$HEALTH_JSON" | grep -q "\"pha_build\":\"${EXPECTED_BUILD}\""
  check "index app.js cache bust (build_marker)" test -n "$ASSET_VER"
  check "index app.js cache bust" echo "$(curl -sf "${BASE}/")" | grep -q "app.js?v=${ASSET_VER}"
else
  echo "WARN  could not read PHA_SERVER_BUILD from build_marker" >&2
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Acceptance FAILED" >&2
  exit 1
fi

echo "Acceptance PASSED (${BASE}, build in /health)"
