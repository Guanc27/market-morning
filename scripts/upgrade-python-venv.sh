#!/usr/bin/env bash
# Recreate backend venv with Python 3.10+ (for MCP OAuth SDK, optional).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"

pick_python() {
  for cmd in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      if [[ "$(printf '%s\n' "3.10" "$ver" | sort -V | head -1)" == "3.10" ]]; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python || true)"
if [ -z "$PY" ]; then
  echo "Python 3.10+ not found."
  echo "Install with Homebrew: brew install python@3.12"
  echo "Then re-run this script."
  exit 1
fi

echo "Using $("$PY" --version)"
cd "$BACKEND"
rm -rf .venv
"$PY" -m venv .venv
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

echo ""
echo "Venv upgraded. Reinstall services:"
echo "  ./scripts/install-launchagent.sh"
echo "  ./scripts/install-robinhood-bridge.sh"
