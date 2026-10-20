# QueryDoc AI — Implementation Status

Author: Raahul Sallagunta · Last updated: 2026-10-19

Final evidence-linked verdicts: `results/acceptance/ACCEPTANCE.md` and
`docs/RESUME_CLAIM_VALIDATION.md`.

## Phase 1 — RAG engine (complete)

| Area | Status | Evidence |
|---|---|---|
| PDF ingestion (PyMuPDF), cleaning, scanned/blank detection | Done | engine unit/integration tests |
| Chunking (fixed / recursive / sentence, page ranges) | Done | `results/relevance` sweep |
| Batched embeddings + cache | Done | `results/embeddings` |
| FAISS index, persistence, filtering, delete | Done | unit tests, `results/retrieval_latency` |
| Hybrid retrieval, dedup, MMR, cross-encoder rerank | Done | `results/relevance` |
| Local HF generation (Qwen2.5-1.5B default) | Done | `results/generation` |
| Citation verification + attribution | Done | unit + e2e tests |
| Benchmarks (relevance, latency GPU/CPU, memory, concurrency, generation, ingestion) | Done | `results/*` |

## Phase 2 — Full-stack upgrade (complete)

| Area | Status | Evidence |
|---|---|---|
| Monorepo: `backend/` (FastAPI + engine), `frontend/` (React) | Done | repository |
| Streamlit removed as a runtime dependency | Done | `backend/pyproject.toml` |
| REST API v1 + OpenAPI (documents, chat, SSE, conversations, analytics, settings, health) | Done | `docs/API.md`, 22 API tests |
| SQLAlchemy + SQLite (WAL) + Alembic migrations | Done | migration `bd60d90d22a9` |
| Background ingestion worker, progress, re-index, restart reconciliation | Done | API tests |
| SSE streaming with disconnect cancellation; follow-up history; regenerate | Done | API + Playwright tests |
| React frontend: design system, 6 pages, three-panel chat, PDF viewer, analytics, settings | Done | build, Vitest, Playwright |
| Frontend unit/component tests incl. axe | Done | 22 Vitest tests |
| Playwright E2E (real stack, real models) | Done | 10 functional tests |
| Visual QA: desktop/tablet/mobile × dark/light + states | Done | 12 visual tests, `docs/images/ui/` |
| HTTP API end-to-end latency benchmark | Done | `results/api_e2e` |
| Startup scripts (setup, dev, prod, tests), CI for both apps | Done | `scripts/`, `.github/workflows/ci.yml` |
| Documentation updated for the full stack | Done | `docs/` |
| Acceptance script for the new definition of done | Done | `scripts/acceptance.py` |

Latest full run (`./scripts/test_all.sh`): backend 119 passed (incl. real-LLM e2e), Vitest 22 passed, frontend build OK, Playwright 22 passed.

## Not done / out of scope

- Docker Compose — intentionally not provided (macOS containers cannot use the Apple GPU).
- Authentication, multi-tenancy, TLS — local single-user mode only.
- OCR tested on synthetic image-only PDFs only (unit + API tests; requires Tesseract); CUDA, Windows and non-Chromium browsers untested. CI runs on GitHub Actions (Ubuntu) for backend and frontend.
- Generation timeouts at 10–20 concurrent generation users under memory pressure — observed, not root-caused.
- License: MIT (chosen by the author).

## Run

```bash
./scripts/setup.sh --with-models   # once
./scripts/dev.sh                   # API :8000 + UI :5173
./scripts/start_prod.sh            # one process on :8000
./scripts/test_all.sh              # all tests
```

## Environment notes
- The project folder is `querydoc-ai.nosync` (symlink `querydoc-ai`) so iCloud does not evict files; it is not iCloud-backed — push to a git remote.
- Frontend tooling requires Node 22 (`frontend/.nvmrc`).
