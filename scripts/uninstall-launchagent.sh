#!/usr/bin/env bash
set -euo pipefail

PLIST_LABEL="com.market-morning.backend"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
rm -f "$PLIST_PATH"
echo "Market Morning background service stopped and removed."
