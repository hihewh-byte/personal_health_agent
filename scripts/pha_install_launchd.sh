#!/usr/bin/env bash
# Install / uninstall PHA as a user LaunchAgent (launchd KeepAlive).
# Wrapper script is installed under ~/Library/Application Support/pha/ (TCC-safe).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/pha_process_lib.sh"
pha_process_lib_init "$ROOT"

ACTION="${1:-install}"

usage() {
  cat <<EOF
Usage: bash scripts/pha_install_launchd.sh [install|uninstall|status|verify]

  install    Stop legacy keepalive, write wrapper + plist, bootstrap launchd job
  uninstall  bootout launchd job, remove plist + wrapper (legacy fallback available)
  status     Show launchd job state
  verify     10s TCC smoke test (bootstrap + /health + bootout)

Env: PHA_PORT (from .env), PHA_USE_LAUNCHD=auto|1|0
EOF
}

pha_launchd_write_wrapper() {
  mkdir -p "$PHA_LAUNCHD_SUPPORT"
  local tpl="$ROOT/scripts/macos/pha-launchd-wrapper.template.sh"
  sed \
    -e "s|__PHA_ROOT__|${ROOT}|g" \
    -e "s|__PHA_PORT__|${PORT}|g" \
    "$tpl" >"$PHA_LAUNCHD_WRAPPER"
  chmod +x "$PHA_LAUNCHD_WRAPPER"
  echo "    wrapper=$PHA_LAUNCHD_WRAPPER"
}

pha_launchd_write_plist() {
  mkdir -p "$PHA_LAUNCHD_LOGS" "$HOME/Library/LaunchAgents"
  cat >"$PHA_LAUNCHD_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PHA_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PHA_LAUNCHD_WRAPPER}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PHA_LAUNCHD_SUPPORT}</string>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>5</integer>
  <key>StandardOutPath</key>
  <string>${PHA_LAUNCHD_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${PHA_LAUNCHD_LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
PLIST
  echo "    plist=$PHA_LAUNCHD_PLIST"
  echo "    log=$PHA_LAUNCHD_LOG"
}

cmd_install() {
  if ! pha_preflight_restart; then
    exit 1
  fi

  echo "==> Installing launchd service ${PHA_LAUNCHD_TARGET}"
  pha_launchd_bootout 2>/dev/null || true
  pha_stop_pha_processes

  pha_launchd_sync_env
  pha_launchd_write_wrapper
  pha_launchd_write_plist

  if ! launchctl bootstrap "$PHA_LAUNCHD_DOMAIN" "$PHA_LAUNCHD_PLIST"; then
    echo "ERROR: launchctl bootstrap failed (TCC / plist error). See $PHA_LAUNCHD_LOG" >&2
    exit 1
  fi

  if ! launchctl kickstart "$PHA_LAUNCHD_TARGET"; then
    echo "ERROR: launchctl kickstart failed; tail log:" >&2
    tail -n 30 "$PHA_LAUNCHD_LOG" 2>/dev/null >&2 || true
    exit 1
  fi

  if ! pha_wait_health 45; then
    echo "ERROR: /health not ready after launchd install; tail log:" >&2
    tail -n 40 "$PHA_LAUNCHD_LOG" 2>/dev/null >&2 || true
    exit 1
  fi

  echo "OK  launchd installed and /health ready at ${BASE}/"
  echo "    restart: bash scripts/pha_restart_accept.sh"
  echo "    stop:    bash scripts/pha_stop.sh"
  echo "    logs:    tail -f $PHA_LAUNCHD_LOG"
}

cmd_uninstall() {
  echo "==> Uninstalling launchd service ${PHA_LAUNCHD_TARGET}"
  pha_launchd_bootout || true
  rm -f "$PHA_LAUNCHD_PLIST" "$PHA_LAUNCHD_WRAPPER" "${PHA_LAUNCHD_SUPPORT}/env-${PORT}.sh"
  pha_stop_pha_processes
  echo "Done. Legacy keepalive: PHA_USE_LAUNCHD=0 bash scripts/pha_restart_accept.sh"
}

cmd_status() {
  echo "label=${PHA_LAUNCHD_LABEL}"
  echo "target=${PHA_LAUNCHD_TARGET}"
  echo "plist=${PHA_LAUNCHD_PLIST} ($([[ -f $PHA_LAUNCHD_PLIST ]] && echo present || echo missing))"
  echo "wrapper=${PHA_LAUNCHD_WRAPPER} ($([[ -x $PHA_LAUNCHD_WRAPPER ]] && echo present || echo missing))"
  if pha_launchd_installed; then
    launchctl print "$PHA_LAUNCHD_TARGET" 2>/dev/null | head -20 || echo "(not loaded)"
  else
    echo "(not installed)"
  fi
}

cmd_verify() {
  echo "==> TCC smoke test (bootstrap → health → bootout)"
  pha_launchd_bootout 2>/dev/null || true
  pha_stop_pha_processes
  pha_launchd_sync_env
  pha_launchd_write_wrapper
  pha_launchd_write_plist
  launchctl bootstrap "$PHA_LAUNCHD_DOMAIN" "$PHA_LAUNCHD_PLIST"
  launchctl kickstart "$PHA_LAUNCHD_TARGET"
  if pha_wait_health 30; then
    echo "OK  TCC smoke test passed (/health 200)"
    pha_launchd_bootout
    rm -f "$PHA_LAUNCHD_PLIST" "$PHA_LAUNCHD_WRAPPER" "${PHA_LAUNCHD_SUPPORT}/env-${PORT}.sh"
    echo "OK  cleaned up test plist/wrapper"
    exit 0
  fi
  echo "FAIL TCC smoke test — /health timeout; see $PHA_LAUNCHD_LOG" >&2
  tail -n 20 "$PHA_LAUNCHD_LOG" 2>/dev/null >&2 || true
  exit 1
}

case "$ACTION" in
  install) cmd_install ;;
  uninstall) cmd_uninstall ;;
  status) cmd_status ;;
  verify) cmd_verify ;;
  -h|--help|help) usage ;;
  *) echo "Unknown action: $ACTION" >&2; usage; exit 2 ;;
esac
