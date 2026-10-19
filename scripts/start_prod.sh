#!/usr/bin/env bash
# Production-style local run: build the React app once, then serve UI + API from one
# FastAPI process on http://127.0.0.1:8000 (no Vite, no Node at runtime).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_VERSION="$(cat "$ROOT/frontend/.nvmrc")"
if [ -d "$HOME/.nvm/versions/node/v$NODE_VERSION/bin" ]; then export PATH="$HOME/.nvm/versions/node/v$NODE_VERSION/bin:$PATH"; fi
(cd "$ROOT/frontend" && npm run build)
cd "$ROOT/backend"
source "$ROOT/.venv/bin/activate"
exec uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" --workers 1
