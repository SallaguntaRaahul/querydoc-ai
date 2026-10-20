#!/usr/bin/env bash
# Share QueryDoc AI with other people from this Mac: accounts on, served through a free
# Cloudflare quick tunnel (public https://*.trycloudflare.com link, no Cloudflare account).
# Uses the Mac's GPU, so answers are fast, but the app is only reachable while this keeps
# running and the Mac is awake and online. Ctrl-C stops everything.
#   ./scripts/serve_public.sh [admin@email]
# Author: Raahul Sallagunta
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${QUERYDOC_PUBLIC_PORT:-8400}"
command -v cloudflared >/dev/null || { echo "cloudflared is missing: brew install cloudflared"; exit 1; }
source "$ROOT/.venv/bin/activate"
NODE_VERSION="$(cat "$ROOT/frontend/.nvmrc")"
[ -d "$HOME/.nvm/versions/node/v$NODE_VERSION/bin" ] && export PATH="$HOME/.nvm/versions/node/v$NODE_VERSION/bin:$PATH"

echo "==> Building the web app"
(cd "$ROOT/frontend" && npx vite build --logLevel error)

export QUERYDOC_AUTH_ENABLED=true \
       QUERYDOC_COOKIE_SECURE=true \
       QUERYDOC_COOKIE_SAMESITE=lax \
       QUERYDOC_CLIENT_IP_HEADER=cf-connecting-ip \
       QUERYDOC_DATA_DIR="$ROOT/data/public" \
       QUERYDOC_MAX_UPLOAD_MB=20 \
       QUERYDOC_LOG_LEVEL=WARNING \
       HF_HUB_OFFLINE=1
[ -n "${1:-}" ] && export QUERYDOC_ADMIN_EMAILS="[\"$1\"]"

cleanup() { kill "${SERVER_PID:-}" "${AWAKE_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "==> Starting the app on 127.0.0.1:$PORT (separate data folder: data/public)"
(cd "$ROOT/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) &
SERVER_PID=$!
caffeinate -dimsu -w "$SERVER_PID" &  # keep the Mac awake while serving
AWAKE_PID=$!
until curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; do
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "The app failed to start."; exit 1; }
  sleep 1
done

echo "==> Opening the public tunnel. Share the https://….trycloudflare.com address printed below."
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT"
