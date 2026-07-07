#!/usr/bin/env bash
# Start Market Morning in hosted SaaS mode (standalone web app at /app)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export SAAS_MODE="${SAAS_MODE:-1}"
export BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
export BACKEND_PORT="${BACKEND_PORT:-8742}"
export WEB_APP_URL="${WEB_APP_URL:-http://localhost:${BACKEND_PORT}/app}"

echo "Market Morning SaaS → http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Web app          → ${WEB_APP_URL}"
echo "API docs         → http://localhost:${BACKEND_PORT}/docs"

exec .venv/bin/uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload
