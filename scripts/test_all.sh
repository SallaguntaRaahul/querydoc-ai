#!/usr/bin/env bash
# All automated checks. Writes JUnit evidence to results/tests/.
# Set QUERYDOC_SKIP_LLM=1 to skip tests that need the cached generation model.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/.venv/bin/activate"
NODE_VERSION="$(cat "$ROOT/frontend/.nvmrc")"
if [ -d "$HOME/.nvm/versions/node/v$NODE_VERSION/bin" ]; then export PATH="$HOME/.nvm/versions/node/v$NODE_VERSION/bin:$PATH"; fi
mkdir -p "$ROOT/results/tests"
echo "==> Backend lint + types"; (cd "$ROOT/backend" && ruff check app querydoc tests && mypy)
echo "==> Backend tests"; (cd "$ROOT/backend" && pytest --junitxml="$ROOT/results/tests/junit.xml" -q)
echo "==> Frontend types + build"; (cd "$ROOT/frontend" && npx tsc -p tsconfig.app.json --noEmit && npm run build >/dev/null)
echo "==> Frontend unit/component tests"; (cd "$ROOT/frontend" && npx vitest run --reporter=default --reporter=junit --outputFile.junit="$ROOT/results/tests/vitest-junit.xml")
echo "==> End-to-end (Playwright; starts its own servers)"; (cd "$ROOT/frontend" && npx playwright test)
echo "All checks passed."
