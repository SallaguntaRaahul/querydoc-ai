#!/usr/bin/env bash
# Start the FastAPI backend (development, auto-reload off for stable model memory).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
source "$ROOT/.venv/bin/activate"
exec uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" --timeout-graceful-shutdown 5
