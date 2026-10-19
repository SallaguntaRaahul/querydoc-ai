#!/usr/bin/env bash
# Starts a fresh, isolated QueryDoc AI stack for Playwright: production build of the
# React app served by FastAPI on :8300 with an empty temporary workspace and real models.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DATA="$HERE/.data"
rm -rf "$DATA" && mkdir -p "$DATA"
(cd "$ROOT/frontend" && npm run build >/dev/null)
cd "$ROOT/backend"
export QUERYDOC_DATA_DIR="$DATA" QUERYDOC_LOAD_MODELS_ON_STARTUP=true QUERYDOC_MAX_NEW_TOKENS="${QUERYDOC_MAX_NEW_TOKENS:-160}"
exec "$ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8300
