#!/usr/bin/env bash
# Optional: Robinhood MCP bridge for live portfolio sync on extension open.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
PLIST_LABEL="com.market-morning.robinhood-bridge"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
PYTHON="$BACKEND/.venv/bin/python3"
BRIDGE="$ROOT/scripts/robinhood-mcp-bridge.py"
AUTH="$ROOT/scripts/robinhood-mcp-auth.py"

echo "Market Morning — install Robinhood MCP bridge"
echo ""

cd "$BACKEND"
if [ ! -d .venv ]; then
  echo "Creating Python venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Python $PY_VERSION"
if [[ "$(printf '%s\n' "3.10" "$PY_VERSION" | sort -V | head -1)" != "3.10" ]]; then
  echo "Error: Python 3.10+ required for Robinhood OAuth bridge."
  echo "Run: brew install python@3.12 && ./scripts/upgrade-python-venv.sh"
  exit 1
fi

if ! grep -q '^ROBINHOOD_SYNC_PROXY_URL=' "$BACKEND/.env" 2>/dev/null; then
  echo "ROBINHOOD_SYNC_PROXY_URL=http://127.0.0.1:8743" >> "$BACKEND/.env"
  echo "Added ROBINHOOD_SYNC_PROXY_URL to backend/.env"
fi

chmod +x "$AUTH" "$BRIDGE"

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
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${BRIDGE}</string>
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/market-morning-bridge.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/market-morning-bridge.err</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo ""
if [ ! -f "$BACKEND/data/robinhood_mcp_oauth.json" ]; then
  echo "Next step — one-time Robinhood login (browser opens):"
  echo "  ./scripts/robinhood-mcp-auth.sh"
  echo ""
else
  echo "Robinhood tokens found. Restarting bridge…"
  launchctl kickstart -k "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
fi

sleep 1
curl -sf http://127.0.0.1:8743/health >/dev/null 2>&1 && echo "Bridge: http://127.0.0.1:8743" || echo "Bridge starting — check: tail -f /tmp/market-morning-bridge.err"

echo ""
echo "Restart backend: launchctl kickstart -k gui/\$(id -u)/com.market-morning.backend"
