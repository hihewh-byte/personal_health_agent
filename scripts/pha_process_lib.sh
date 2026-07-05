#!/usr/bin/env bash
# Shared PHA process lifecycle helpers (sourced by restart/stop scripts — not a user entrypoint).
# P0-0: pre-flight before kill, identity-verified stop, restart mutex lock.

if [[ -n "${PHA_PROCESS_LIB_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
PHA_PROCESS_LIB_LOADED=1

PHA_RESTART_LOCK_STALE_SECS="${PHA_RESTART_LOCK_STALE_SECS:-600}"

pha_process_lib_init() {
  local root="$1"
  ROOT="$root"
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
  PORT="${PHA_PORT:-8788}"
  HOST="${PHA_HOST:-127.0.0.1}"
  BASE="http://${HOST}:${PORT}"
  LOG="${PHA_RESTART_LOG:-/tmp/pha-${PORT}.log}"
  PIDFILE="${PHA_RESTART_PIDFILE:-/tmp/pha-${PORT}.pid}"
  WD="/tmp/pha-${PORT}.watchdog.pid"
  WD_LOG="/tmp/pha-${PORT}.watchdog.log"
  RESTART_LOCK="/tmp/pha-${PORT}.restart.lock"
  PY="${ROOT}/.venv/bin/python"
  DETACH="$ROOT/scripts/pha_detach_spawn.py"
  PHA_LAUNCHD_SUPPORT="${HOME}/Library/Application Support/pha"
  PHA_LAUNCHD_LOGS="${HOME}/Library/Logs/pha"
  PHA_LAUNCHD_LABEL="com.personal-health-agent.pha-${PORT}"
  PHA_LAUNCHD_DOMAIN="gui/$(id -u)"
  PHA_LAUNCHD_TARGET="${PHA_LAUNCHD_DOMAIN}/${PHA_LAUNCHD_LABEL}"
  PHA_LAUNCHD_PLIST="${HOME}/Library/LaunchAgents/${PHA_LAUNCHD_LABEL}.plist"
  PHA_LAUNCHD_WRAPPER="${PHA_LAUNCHD_SUPPORT}/run-${PORT}.sh"
  PHA_LAUNCHD_LOG="${PHA_LAUNCHD_LOGS}/pha-${PORT}.log"
  LOG="${PHA_RESTART_LOG:-${PHA_LAUNCHD_LOG}}"
}

pha_cmd_is_pha() {
  local pid="$1"
  local cmd=""
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  cmd="$(ps -p "$pid" -o command= 2>/dev/null | sed 's/^[[:space:]]*//')"
  [[ -z "$cmd" ]] && return 1
  case "$cmd" in
    *pha.main*|*pha_keepalive*|*pha_detach_spawn*|*Application\ Support/pha/run-*)
      return 0
      ;;
  esac
  return 1
}

pha_port_listener_pids() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  # LISTEN only — plain lsof -ti :PORT also matches outbound client sockets (false positives).
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u
}

pha_assert_port_safe_for_restart() {
  local pid non_pha=()
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if ! pha_cmd_is_pha "$pid"; then
      non_pha+=("$pid")
    fi
  done < <(pha_port_listener_pids)

  if [[ ${#non_pha[@]} -gt 0 ]]; then
    echo "ERROR: port :${PORT} occupied by non-PHA process(es): ${non_pha[*]}" >&2
    for pid in "${non_pha[@]}"; do
      ps -p "$pid" -o pid=,command= 2>/dev/null | sed 's/^/    /' >&2 || true
    done
    echo "    Refusing to kill non-PHA listeners. Old PHA service (if any) is unchanged." >&2
    return 1
  fi
  return 0
}

pha_preflight_restart() {
  echo "==> Pre-flight (before any stop)"

  if [[ ! -x "$PY" ]]; then
    echo "ERROR: missing venv python at $PY" >&2
    echo "    Old service (if running) is unchanged." >&2
    return 1
  fi

  if ! (cd "$ROOT" && PYTHONPATH=. "$PY" -c "import pha.main" 2>/dev/null); then
    echo "ERROR: import pha.main failed (dry-run)" >&2
    (cd "$ROOT" && PYTHONPATH=. "$PY" -c "import pha.main") 2>&1 | tail -n 15 >&2 || true
    echo "    Old service (if running) is unchanged." >&2
    return 1
  fi

  if ! (cd "$ROOT" && PYTHONPATH=. "$PY" -c "from pha.build_marker import PHA_SERVER_BUILD; print(PHA_SERVER_BUILD)" >/dev/null 2>&1); then
    echo "ERROR: cannot read PHA_SERVER_BUILD from build_marker" >&2
    echo "    Old service (if running) is unchanged." >&2
    return 1
  fi

  if ! pha_assert_port_safe_for_restart; then
    return 1
  fi

  echo "OK  pre-flight passed"
  return 0
}

pha_acquire_restart_lock() {
  local started now holder

  if mkdir "$RESTART_LOCK" 2>/dev/null; then
    echo "$$" >"$RESTART_LOCK/pid"
    date +%s >"$RESTART_LOCK/started"
    return 0
  fi

  holder="$(cat "$RESTART_LOCK/pid" 2>/dev/null || true)"
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    echo "ERROR: another restart is in progress (lock holder pid=${holder})" >&2
    echo "    Refusing concurrent restart. Old service is unchanged." >&2
    return 1
  fi

  echo "WARN  reclaiming stale restart lock (holder pid=${holder:-none})" >&2
  rm -rf "$RESTART_LOCK"
  if mkdir "$RESTART_LOCK" 2>/dev/null; then
    echo "$$" >"$RESTART_LOCK/pid"
    date +%s >"$RESTART_LOCK/started"
    return 0
  fi

  echo "ERROR: could not acquire restart lock" >&2
  return 1
}

pha_release_restart_lock() {
  rm -rf "$RESTART_LOCK" 2>/dev/null || true
}

pha_kill_pid_if_pha() {
  local pid="$1"
  local label="${2:-process}"
  [[ -z "$pid" ]] && return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if ! pha_cmd_is_pha "$pid"; then
    echo "    skip kill ${label} pid=$pid (not PHA-owned)" >&2
    return 0
  fi
  kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  echo "    stopped ${label} pid=$pid"
}

pha_stop_pha_processes() {
  local old_wd app_pid pid

  echo "==> Stopping PHA on :${PORT} (identity-verified)"

  if [[ -f "$WD" ]]; then
    old_wd="$(cat "$WD" 2>/dev/null || true)"
    pha_kill_pid_if_pha "$old_wd" "keepalive"
    rm -f "$WD"
  fi

  if [[ -f "$PIDFILE" ]]; then
    app_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    pha_kill_pid_if_pha "$app_pid" "app"
    rm -f "$PIDFILE"
  fi

  if command -v lsof >/dev/null 2>&1; then
    local killed_any=0
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if pha_cmd_is_pha "$pid"; then
        kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        echo "    stopped port listener pid=$pid"
        killed_any=1
      else
        echo "    skip port listener pid=$pid (not PHA-owned)" >&2
      fi
    done < <(pha_port_listener_pids)
    if [[ "$killed_any" -eq 0 ]]; then
      if [[ -z "$(pha_port_listener_pids)" ]]; then
        echo "    no listener on :${PORT}"
      fi
    fi
  fi

  # Orphan supervisors (e.g. stale pidfile after recovery edge cases).
  if command -v pgrep >/dev/null 2>&1; then
    local orphan
    while IFS= read -r orphan; do
      [[ -z "$orphan" ]] && continue
      pha_kill_pid_if_pha "$orphan" "orphan keepalive"
    done < <(pgrep -f "pha_keepalive.py ${ROOT}" 2>/dev/null || true)
    while IFS= read -r orphan; do
      [[ -z "$orphan" ]] && continue
      if pha_cmd_is_pha "$orphan"; then
        local ocmd
        ocmd="$(ps -p "$orphan" -o command= 2>/dev/null || true)"
        if [[ "$ocmd" == *"-m pha.main"* ]]; then
          pha_kill_pid_if_pha "$orphan" "orphan app"
        fi
      fi
    done < <(pgrep -f "${ROOT}/.venv/bin/python -m pha.main" 2>/dev/null || true)
  fi

  echo "Done."
}

pha_spawn_supervisor() {
  local mode="${1:-}"
  export PYTHONPATH=.
  export PHA_HOST="${HOST}"
  export PHA_PORT="${PORT}"
  export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
  export PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE:-t0_plus_disclosure}"
  export PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE:-warn}"

  if [[ "$mode" == "foreground" ]]; then
    echo "INFO: foreground mode — keep Terminal open."
    exec env PYTHONPATH=. PATH="${PATH}" \
      PHA_HOST="${HOST}" \
      PHA_PORT="${PORT}" \
      PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE}" \
      PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE}" \
      "$PY" -m pha.main
  fi

  local keepalive="${PHA_ENABLE_KEEPALIVE:-1}"
  if [[ "$keepalive" == "1" ]]; then
    : >"$WD_LOG"
    local wd_pid
    wd_pid="$("$PY" "$DETACH" "$ROOT" "$WD_LOG" \
      "$PY" "$ROOT/scripts/pha_keepalive.py" \
      "$ROOT" "$PY" "$PIDFILE" "$LOG" \
      "$HOST" "$PORT" "$PHA_NUMERICS_AUDIT_SCOPE" "$PHA_NUMERICS_T1_M4_MODE" "$PATH")"
    echo "$wd_pid" >"$WD"
    echo "    keepalive pid=${wd_pid} log=$WD_LOG (will spawn pha.main)"
  else
    local pha_pid
    pha_pid="$("$PY" "$DETACH" "$ROOT" "$LOG" \
      env PYTHONPATH=. PATH="${PATH}" \
      PHA_HOST="${HOST}" PHA_PORT="${PORT}" \
      PHA_NUMERICS_AUDIT_SCOPE="${PHA_NUMERICS_AUDIT_SCOPE}" \
      PHA_NUMERICS_T1_M4_MODE="${PHA_NUMERICS_T1_M4_MODE}" \
      "$PY" -m pha.main)"
    echo "$pha_pid" >"$PIDFILE"
    echo "    pid=${pha_pid} log=$LOG (detached, no keepalive)"
  fi
}

pha_wait_health() {
  local wait_secs="${1:-45}"
  local i ready=0
  echo "==> Waiting for ${BASE}/health (max ${wait_secs}s)"
  for ((i = 1; i <= wait_secs; i++)); do
    if curl -sf "${BASE}/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  [[ "$ready" -eq 1 ]]
}

pha_recovery_spawn_keepalive() {
  local old_wd
  echo "==> RECOVERY: restoring service after failed restart (post-stop)" >&2

  old_wd="$(cat "$WD" 2>/dev/null || true)"
  if [[ -n "$old_wd" ]] && pha_cmd_is_pha "$old_wd" && kill -0 "$old_wd" 2>/dev/null; then
    echo "    keepalive pid=${old_wd} still running; waiting for /health" >&2
    sleep 2
    if pha_wait_health 60; then
      echo "RECOVERY OK: /health reachable via existing keepalive" >&2
      return 0
    fi
    echo "    keepalive alive but /health still down; replacing supervisor" >&2
    pha_kill_pid_if_pha "$old_wd" "keepalive"
    rm -f "$WD"
  fi

  export PHA_ENABLE_KEEPALIVE=1
  pha_spawn_supervisor "nohup"
  sleep 2
  if pha_wait_health 60; then
    echo "RECOVERY OK: /health reachable after keepalive re-spawn" >&2
    return 0
  fi
  echo "RECOVERY FAILED: service is DOWN — run: bash scripts/pha_restart_accept.sh" >&2
  return 1
}

pha_launchd_installed() {
  [[ -f "$PHA_LAUNCHD_PLIST" ]]
}

pha_launchd_enabled() {
  local mode="${PHA_USE_LAUNCHD:-auto}"
  case "$mode" in
    0|false|no|off) return 1 ;;
    1|true|yes|on) pha_launchd_installed ;;
    auto|*)
      pha_launchd_installed
      ;;
  esac
}

pha_launchd_bootout() {
  if [[ -f "$PHA_LAUNCHD_PLIST" ]] && launchctl print "$PHA_LAUNCHD_TARGET" >/dev/null 2>&1; then
    launchctl bootout "$PHA_LAUNCHD_DOMAIN" "$PHA_LAUNCHD_PLIST"
    echo "    launchd bootout ${PHA_LAUNCHD_LABEL}"
    return 0
  fi
  return 1
}

pha_launchd_kickstart() {
  local force="${1:-}"
  if ! pha_launchd_installed; then
    echo "ERROR: launchd plist not installed; run: bash scripts/pha_install_launchd.sh install" >&2
    return 1
  fi
  if ! launchctl print "$PHA_LAUNCHD_TARGET" >/dev/null 2>&1; then
    launchctl bootstrap "$PHA_LAUNCHD_DOMAIN" "$PHA_LAUNCHD_PLIST"
  fi
  if [[ "$force" == "-k" ]]; then
    launchctl kickstart -k "$PHA_LAUNCHD_TARGET"
  else
    launchctl kickstart "$PHA_LAUNCHD_TARGET"
  fi
}

pha_launchd_sync_env() {
  mkdir -p "$PHA_LAUNCHD_SUPPORT"
  local dest="${PHA_LAUNCHD_SUPPORT}/env-${PORT}.sh"
  if [[ -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env" "$dest"
    chmod 600 "$dest"
  else
    printf 'PHA_HOST=%s\nPHA_PORT=%s\n' "$HOST" "$PORT" >"$dest"
    chmod 600 "$dest"
  fi
  echo "    env=${dest}"
}

pha_launchd_restart() {
  echo "==> launchd kickstart -k ${PHA_LAUNCHD_TARGET}"
  pha_launchd_sync_env
  pha_launchd_legacy_cleanup
  pha_launchd_kickstart -k
}

pha_launchd_legacy_cleanup() {
  # Remove pre-launchd keepalive supervisors; do not kill launchd-managed app.
  local old_wd app_pid
  if [[ -f "$WD" ]]; then
    old_wd="$(cat "$WD" 2>/dev/null || true)"
    pha_kill_pid_if_pha "$old_wd" "legacy keepalive"
    rm -f "$WD"
  fi
  if [[ -f "$PIDFILE" ]]; then
    app_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$app_pid" ]] && pha_cmd_is_pha "$app_pid"; then
      local ocmd
      ocmd="$(ps -p "$app_pid" -o command= 2>/dev/null || true)"
      if [[ "$ocmd" != *"Application Support/pha/run-"* ]]; then
        pha_kill_pid_if_pha "$app_pid" "legacy app"
      fi
    fi
    rm -f "$PIDFILE"
  fi
  if command -v pgrep >/dev/null 2>&1; then
    local orphan
    while IFS= read -r orphan; do
      [[ -z "$orphan" ]] && continue
      pha_kill_pid_if_pha "$orphan" "orphan keepalive"
    done < <(pgrep -f "pha_keepalive.py ${ROOT}" 2>/dev/null || true)
  fi
}

pha_launchd_stop() {
  echo "==> Stopping launchd service ${PHA_LAUNCHD_TARGET}"
  pha_launchd_bootout || true
  pha_launchd_legacy_cleanup
  if command -v lsof >/dev/null 2>&1; then
    local pid
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if pha_cmd_is_pha "$pid"; then
        kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        echo "    stopped lingering listener pid=$pid"
      fi
    done < <(pha_port_listener_pids)
  fi
  echo "Done."
}

pha_launchd_app_pid() {
  pha_port_listener_pids | head -1
}

pha_launchd_recovery() {
  echo "==> RECOVERY: launchd kickstart after failed restart" >&2
  if pha_launchd_kickstart; then
    sleep 2
    if pha_wait_health 60; then
      echo "RECOVERY OK: /health reachable via launchd" >&2
      return 0
    fi
  fi
  echo "RECOVERY FAILED: run: bash scripts/pha_install_launchd.sh install" >&2
  return 1
}
