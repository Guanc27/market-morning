#!/usr/bin/env bash
# One-time install: Market Morning backend runs on login, no terminal needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
PLIST_LABEL="com.market-morning.backend"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
UVICORN="$BACKEND/.venv/bin/uvicorn"

echo "Market Morning — install background service"
echo ""

# Ensure venv + deps
cd "$BACKEND"
if [ ! -d .venv ]; then
  echo "Creating Python venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created backend/.env — edit MOCK_MODE / API keys if needed."
fi

if [ ! -x "$UVICORN" ]; then
  echo "Error: uvicorn not found at $UVICORN"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>${BACKEND}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${UVICORN}</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8742</string>
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/market-morning.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/market-morning.err</string>
</dict>
</plist>
EOF

# Reload if already loaded
launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

sleep 1
if curl -sf http://127.0.0.1:8742/health >/dev/null; then
  echo ""
  echo "Done. Backend is running at http://127.0.0.1:8742"
  echo "It will start automatically every time you log in."
  echo ""
  echo "Logs:  tail -f /tmp/market-morning.log"
  echo "Stop:  ./scripts/uninstall-launchagent.sh"
else
  echo ""
  echo "Installed, but health check failed. Check: tail /tmp/market-morning.err"
  exit 1
fi
