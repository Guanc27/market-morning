#!/usr/bin/env bash
# One-time Robinhood MCP login (uses project venv).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python3"

if [ ! -x "$PY" ]; then
  echo "Creating venv…"
  python3 -m venv "$BACKEND/.venv"
fi

"$PY" -m pip install -q -r "$BACKEND/requirements.txt"
exec "$PY" "$ROOT/scripts/robinhood-mcp-auth.py" "$@"
