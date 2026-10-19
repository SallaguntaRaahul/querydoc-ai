# QueryDoc AI — Implementation Status

Author: Raahul Sallagunta · Last updated: 2026-10-19 (full-stack upgrade, in progress)

## Full-stack upgrade (React + FastAPI)

| Area | Status | Notes |
|---|---|---|
| Repo restructure (backend/, frontend/) | Done | RAG engine preserved as `backend/querydoc`; Streamlit removed |
| FastAPI API v1 (documents, chat, SSE stream, conversations, analytics, settings, health) | Done | Verified live with curl: upload → background index → stream → cancel → follow-up |
| SQLAlchemy + SQLite + Alembic | Done | migration `bd60d90d22a9`, runs on startup |
| Background ingestion worker, reindex, reconciliation | Done | |
| Engine: answer_stream, cancellable generation, follow-up history | Done | 97 engine tests pass |
| React frontend: design system, shell, 6 pages, PDF viewer, analytics, settings | Done | `npm run build` + `tsc` clean; verified in browser (mobile width): stream, citation → highlighted page |
| Frontend tests (Vitest + RTL + axe) | Done | 22 passing |
| Backend API tests (pytest + HTTPX) | **TODO** | `backend/tests/api/` is empty |
| Playwright E2E (upload → index → ask → stream → cite → reload → delete) | **TODO** | `@playwright/test` installed, no specs yet |
| Desktop/tablet/light-theme visual QA + README screenshots | **TODO** | only mobile-width browser checks done |
| API end-to-end latency benchmark (`results/api_e2e`) | **TODO** | engine benchmarks from phase 1 remain valid |
| Scripts: `scripts/dev.sh` (both servers), prod build serving | Partial | run_backend.sh / run_frontend.sh exist; FastAPI serves `frontend/dist` when built |
| Docs update for full-stack architecture (guide, README, API, SSE, React) | **TODO** | docs still describe the Streamlit UI |
| Acceptance script update for new criteria | **TODO** | |

## Run (development)
```bash
./scripts/run_backend.sh     # http://127.0.0.1:8000/api/docs
./scripts/run_frontend.sh    # http://127.0.0.1:5173 (Node 22, see frontend/.nvmrc)
```

## Known issues
- Project lives in `querydoc-ai.nosync` (symlink `querydoc-ai`) to stop iCloud eviction; not iCloud-backed.
- Phase-1 measured results and caveats: see docs/PERFORMANCE_REPORT.md.
