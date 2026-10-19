#!/usr/bin/env bash
# One-time setup: Python env + backend deps, frontend deps, database migration.
# Usage: ./scripts/setup.sh [--with-models]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -e .venv ]; then
  echo "==> Creating Python 3.12 environment"
  if command -v uv >/dev/null; then uv venv -p 3.12 .venv; else python3.12 -m venv .venv; fi
fi
source .venv/bin/activate
echo "==> Installing backend (FastAPI + RAG engine)"
if command -v uv >/dev/null; then uv pip install -e "./backend[dev]"; else pip install -e "./backend[dev]"; fi

echo "==> Installing frontend"
NODE_VERSION="$(cat frontend/.nvmrc)"
if [ -d "$HOME/.nvm/versions/node/v$NODE_VERSION/bin" ]; then export PATH="$HOME/.nvm/versions/node/v$NODE_VERSION/bin:$PATH"; fi
node --version
(cd frontend && npm ci)

echo "==> Applying database migrations"
(cd backend && alembic upgrade head)

if [ "${1:-}" = "--with-models" ]; then
  echo "==> Downloading local models (~3.3 GB, one time)"
  python scripts/download_models.py
fi
echo "Done. Start with: ./scripts/dev.sh"
