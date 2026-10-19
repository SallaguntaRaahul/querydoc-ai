#!/usr/bin/env bash
# Start the Vite dev server for the React frontend (proxies /api to the backend).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
[ -d node_modules ] || npm ci
exec npm run dev -- --host 127.0.0.1 --port "${PORT:-5173}" --strictPort
