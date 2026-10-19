#!/usr/bin/env bash
# Development: FastAPI on :8000 and Vite (hot reload) on :5173. Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/run_backend.sh" & BACK=$!
trap 'kill $BACK 2>/dev/null; wait $BACK 2>/dev/null' EXIT INT TERM
for _ in $(seq 1 120); do curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null && break; sleep 1; done
echo "Backend ready: http://127.0.0.1:8000/api/docs"
"$ROOT/scripts/run_frontend.sh"
