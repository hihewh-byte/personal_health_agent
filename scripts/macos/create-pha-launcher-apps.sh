#!/usr/bin/env bash
# Build PHA-Restart.app and PHA-Stop.app (double-click, no Terminal required for restart).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${1:-$ROOT/macos-apps}"
mkdir -p "$OUT_DIR"

make_app() {
  local name="$1"
  local shell_body="$2"
  local app_dir="$OUT_DIR/${name}.app"
  local macos_dir="$app_dir/Contents/MacOS"
  local resources_dir="$app_dir/Contents/Resources"

  rm -rf "$app_dir"
  mkdir -p "$macos_dir" "$resources_dir"

  cat >"$macos_dir/$name" <<'HEADER'
#!/bin/bash
set -euo pipefail
HEADER
  echo "$shell_body" >>"$macos_dir/$name"
  chmod +x "$macos_dir/$name"

  cat >"$app_dir/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>${name}</string>
  <key>CFBundleIdentifier</key>
  <string>com.pha.local.${name}</string>
  <key>CFBundleName</key>
  <string>${name}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

  echo "Created $app_dir"
}

RESTART_BODY=$(cat <<EOF
ROOT="$ROOT"
PORT="\${PHA_PORT:-8787}"
HOST="\${PHA_HOST:-127.0.0.1}"
LOG="\${PHA_RESTART_LOG:-/tmp/pha-8787.log}"
PY="\$ROOT/.venv/bin/python"
export PATH="/opt/homebrew/bin:/usr/local/bin:\${PATH}"
export PYTHONPATH="\$ROOT"
exec >>/tmp/pha-restart-app.log 2>&1
echo "=== PHA-Restart.app \$(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
osascript -e 'display notification "Restarting PHA…" with title "PHA"' || true
if [[ ! -x "\$PY" ]]; then
  osascript -e 'display alert "PHA venv missing"'
  exit 1
fi
if command -v lsof >/dev/null 2>&1; then
  lsof -ti ":\${PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true
fi
sleep 1
cd "\$ROOT"
nohup "\$PY" -m pha.main >"\$LOG" 2>&1 &
echo \$! >/tmp/pha-\${PORT}.pid
ready=0
for _ in \$(seq 1 45); do
  curl -sf "http://\${HOST}:\${PORT}/health" >/dev/null 2>&1 && ready=1 && break
  sleep 1
done
if [[ "\$ready" -eq 1 ]]; then
  open "http://\${HOST}:\${PORT}/"
  osascript -e 'display notification "PHA is ready" with title "PHA Restart"' || true
else
  osascript -e "display alert \"PHA did not start\" message \"See \${LOG}\""
  exit 1
fi
EOF
)

STOP_BODY=$(cat <<EOF
PORT="\${PHA_PORT:-8787}"
if command -v lsof >/dev/null 2>&1; then
  lsof -ti ":\${PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true
  osascript -e "display notification \"Stopped port \${PORT}\" with title \"PHA Stop\""
else
  osascript -e 'display alert "lsof not found"'
  exit 1
fi
EOF
)

make_app "PHA-Restart" "$RESTART_BODY"
make_app "PHA-Stop" "$STOP_BODY"

echo ""
echo "Apps written to: $OUT_DIR"
echo "Tip: drag PHA-Restart.app to the Dock. First run: right-click → Open (Gatekeeper)."
