#!/usr/bin/env bash
# Restart PHA (default 127.0.0.1:8788; override via .env PHA_PORT).
# P0-0 phase B: pre-flight before stop, identity-verified kill, mutex lock, keepalive recovery.
# P0-4 phase A: launchd kickstart -k when plist installed (PHA_USE_LAUNCHD=auto|1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/pha_process_lib.sh"
pha_process_lib_init "$ROOT"

MODE="${PHA_RUN_MODE:-nohup}"   # nohup | foreground
WAIT_SECS="${PHA_RESTART_WAIT_SECS:-45}"
KEEPALIVE="${PHA_ENABLE_KEEPALIVE:-1}"
USE_LAUNCHD=0
if pha_launchd_enabled; then
  USE_LAUNCHD=1
fi

PHA_RESTART_STOPPED=0
PHA_RESTART_NEW_READY=0
PHA_RESTART_RECOVERY_DONE=0
PHA_RESTART_FINAL_RC=0

pha_restart_on_exit() {
  local rc=$?
  pha_release_restart_lock

  if [[ "$PHA_RESTART_RECOVERY_DONE" -eq 1 ]]; then
    exit "$PHA_RESTART_FINAL_RC"
  fi

  if [[ "$PHA_RESTART_STOPPED" -eq 1 && "$PHA_RESTART_NEW_READY" -eq 0 && "$rc" -ne 0 ]]; then
    if [[ "$USE_LAUNCHD" -eq 1 ]]; then
      if pha_launchd_recovery; then
        PHA_RESTART_RECOVERY_DONE=1
        PHA_RESTART_FINAL_RC=70
        exit 70
      fi
    elif pha_recovery_spawn_keepalive; then
      PHA_RESTART_RECOVERY_DONE=1
      PHA_RESTART_FINAL_RC=70
      exit 70
    fi
    echo "ALERT: PHA service is DOWN after failed restart + failed recovery." >&2
    echo "    Manual recovery: bash scripts/pha_restart_accept.sh" >&2
    exit 71
  fi

  exit "$rc"
}

trap pha_restart_on_exit EXIT

if [[ "$MODE" == "foreground" ]]; then
  if ! pha_preflight_restart; then
    exit 1
  fi
  echo "==> Starting PHA on ${HOST}:${PORT} mode=foreground"
  pha_spawn_supervisor "foreground"
fi

if ! pha_acquire_restart_lock; then
  exit 1
fi

if ! pha_preflight_restart; then
  exit 1
fi

if [[ "$USE_LAUNCHD" -eq 1 ]]; then
  echo "==> Restarting PHA via launchd on ${HOST}:${PORT}"
  echo "    target=${PHA_LAUNCHD_TARGET}"
  echo "    log=${PHA_LAUNCHD_LOG}"
  PHA_RESTART_STOPPED=1
  pha_launchd_restart
  sleep 2
else
  echo "==> Starting PHA on ${HOST}:${PORT} mode=${MODE} keepalive=${KEEPALIVE}"
  echo "    PHA_NUMERICS_AUDIT_SCOPE=${PHA_NUMERICS_AUDIT_SCOPE:-t0_plus_disclosure}"
  echo "    PHA_NUMERICS_T1_M4_MODE=${PHA_NUMERICS_T1_M4_MODE:-warn}"
  pha_stop_pha_processes
  PHA_RESTART_STOPPED=1
  pha_spawn_supervisor "$MODE"
  sleep 2
fi

if ! pha_wait_health "$WAIT_SECS"; then
  echo "ERROR: server did not become ready; tail log:" >&2
  tail -n 40 "$LOG" >&2 || true
  exit 1
fi
PHA_RESTART_NEW_READY=1

PHA_PID="$(pha_launchd_app_pid 2>/dev/null || true)"
if [[ -z "$PHA_PID" ]]; then
  PHA_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
fi
if [[ -z "$PHA_PID" ]] || ! kill -0 "$PHA_PID" 2>/dev/null; then
  echo "ERROR: PHA not running after start; tail log:" >&2
  tail -n 40 "$LOG" >&2 || true
  [[ -f "$WD_LOG" ]] && tail -n 20 "$WD_LOG" >&2 || true
  exit 1
fi
echo "    app pid=${PHA_PID}"

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

if ! kill -0 "$PHA_PID" 2>/dev/null; then
  echo "ERROR: PHA exited after acceptance; tail log:" >&2
  tail -n 40 "$LOG" >&2 || true
  exit 1
fi

echo "Acceptance PASSED (${BASE}, build in /health, pid=${PHA_PID} still running)"
echo ""
echo ">>> Open in browser: ${BASE}/"
echo ">>> Stop: bash scripts/pha_stop.sh"
if command -v open >/dev/null 2>&1; then
  open "${BASE}/" 2>/dev/null || true
fi

if [[ "$USE_LAUNCHD" -eq 1 ]]; then
  echo "Supervisor: launchd KeepAlive (${PHA_LAUNCHD_TARGET})"
  echo "Logs: tail -f ${PHA_LAUNCHD_LOG}"
elif [[ "$KEEPALIVE" == "1" ]]; then
  echo "Supervisor: keepalive (watchdog pid=$(cat "$WD" 2>/dev/null) log=$WD_LOG)"
  echo "Tip: bash scripts/pha_install_launchd.sh install  # system-level KeepAlive"
else
  echo "Keepalive OFF. Set PHA_ENABLE_KEEPALIVE=1 or install launchd."
fi
