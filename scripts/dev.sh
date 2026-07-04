#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Backend
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created backend/.env — add your ANTHROPIC_API_KEY"
fi

# Extension (load unpacked)
#   extension/dist/   ← no build required (vanilla JS)
# Optional React rebuild (requires Node.js):
#   cd extension && npm install && npm run build

echo ""
echo "Starting backend on http://127.0.0.1:8742"
echo "Load extension from: $ROOT/extension/dist"
echo ""
cd "$ROOT/backend"
source .venv/bin/activate
exec uvicorn app.main:app --host 127.0.0.1 --port 8742 --reload
