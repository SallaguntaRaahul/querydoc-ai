# Testing and Validation

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

Four layers of automated tests plus benchmark evidence. One command runs everything:

```bash
./scripts/test_all.sh          # lint, types, pytest, build, Vitest, Playwright → results/tests/*.xml
python scripts/check_app.py     # production-style launch check → results/app/launch.json
python scripts/acceptance.py    # PASS/FAIL table → results/acceptance/ACCEPTANCE.md
```

## 1. Test inventory

| Layer | Tool | Where | Count | What it proves |
|---|---|---|---|---|
| Engine unit | pytest | `backend/tests/unit/` | 80 | ingestion validation and extraction (rotated text, soft-wrap reflow, scanned/blank pages, encryption, limits), chunk offsets/page ranges, embeddings and cache, FAISS add/search/filter/delete/persist/tamper, retrieval helpers, citation verification and attribution, prompt delimiting and injection redaction, admission gate, no-pickle AST check |
| Engine integration | pytest | `backend/tests/integration/` | 11 | ingest → retrieve on a 120-page PDF, duplicates, invalid uploads, multi-document isolation, delete, restart persistence, insufficient-evidence gate, retrieval-only fallback, queries during ingestion, bounded admission |
| Engine e2e (real Qwen 1.5B) | pytest `-m llm` | `backend/tests/e2e/` | 5 | supported answer with a valid citation on the right page, unsupported question declined, injected instruction not obeyed, document filter, concurrent answers on the shared GPU |
| Performance guard | pytest | `backend/tests/performance/` | 1 | warm retrieval p95 < 300 ms on a 120-page PDF |
| **API** | pytest + HTTPX `TestClient` | `backend/tests/api/` | 22 | health/OpenAPI; upload 202 → background ready; duplicate 409, non-PDF 422, wrong type 415, oversize 413, multi-file partial errors; failed (scanned) ingestion reported; path traversal / bad ids 404; delete removes vectors and file; re-index applies new chunking; blocking chat with verified citation, conversation CRUD and feedback; SSE event order and persistence; follow-up and regenerate; scope isolation; validation errors; off-topic declined without calling the LLM; prompt injection flagged; settings validation, presets, unavailable device 409, embedding lock 409, persistence across restart; analytics runtime vs benchmark; restart persistence of documents and conversations; 6 concurrent chats; queue-full 429; client disconnect → `cancelled` |
| **Frontend unit/component** | Vitest + React Testing Library + vitest-axe | `frontend/src/**/*.test.ts(x)` | 22 | SSE parser (partial chunks, keep-alives, CRLF), formatters, PDF text helpers (HTML escaping, honest passage matching), upload validation, settings Zod schema, citation linkification, assistant message chips/pills/copy, dashboard real counts and backend-offline alert, library filter and delete via API, settings validation and PUT, theme toggle persistence, **axe accessibility checks** |
| **End-to-end** | Playwright (Chromium) | `frontend/e2e/app.spec.ts` | 10 | real stack, real models: onboarding empty states; invalid upload error; upload of two real NIST PDFs incl. **183 pages** with live progress; duplicate rejected; streamed answer with verified citations; evidence panel; **citation opens the cited PDF page** with highlight status; follow-up; reload persistence; reopen from history; **stop** mid-stream; viewer search; settings validation and persistence; analytics; theme; delete document and index entries |
| **Visual QA** | Playwright | `frontend/e2e/visual.spec.ts` | 12 | 30+ screenshots: overview, library, chat, analytics, settings at desktop 1440×900, tablet 834×1112, mobile 390×844 in dark and light; citation + PDF side by side; viewer search; long titles truncate; empty / loading / backend-offline states; long answer with 8 citations; focus visibility; reduced motion; **no horizontal overflow** asserted on every page |

The API tests run the real ingestion pipeline, embeddings, FAISS, SQLite and background worker; only the generator is a deterministic stub (it quotes the top passage and cites it), so the HTTP contract is tested quickly and repeatably. The real model is exercised by the engine e2e tests, the Playwright suite and `benchmarks/benchmark_api.py`.

## 2. Commands

```bash
# backend (from backend/)
pytest                                   # all backend tests (LLM tests skip if the model is not cached)
pytest tests/api -q                      # API only (~20 s)
ruff check app querydoc tests && mypy

# frontend (from frontend/, Node 22 — see frontend/.nvmrc)
npx vitest run
npx tsc -p tsconfig.app.json --noEmit && npm run build
npx playwright install chromium          # once
npx playwright test                      # starts its own server on :8300 with a fresh workspace
npx playwright show-report
```

Playwright's server (`frontend/e2e/start-server.sh`) builds the frontend, wipes `frontend/e2e/.data` and starts FastAPI with real models, so every run starts from an empty library.

## 3. What the acceptance script checks

`scripts/acceptance.py` reads only evidence files:

| Definition-of-done item | Evidence |
|---|---|
| 1–2 frontend builds; backend starts (health, SPA, client routes, OpenAPI) | `results/app/launch.json` |
| 3–10 upload, indexing, retrieval, local LLM answer, citation navigation, conversation persistence, settings, analytics | named Playwright cases in `results/tests/playwright-junit.xml` |
| 11 automated tests | `results/tests/junit.xml` (pytest), `results/tests/vitest-junit.xml` |
| 12 end-to-end tests | Playwright functional cases |
| 13 visual inspection | Playwright visual cases and screenshot count in `docs/images/ui/` |
| 14 benchmarks recorded | all eight `results/*/results.json` |
| 15 documentation | required files present |
| 16 resume claims | verdicts in `docs/RESUME_CLAIM_VALIDATION.md` |

Performance targets (relevance, latency GPU/CPU, memory, concurrency, generation, API end-to-end) are evaluated separately; a missed target is reported as FAIL.

## 4. Manual and visual inspection performed

- The running app was used in the in-app browser (mobile width): streamed answer, citation → page 79 with highlight, analytics, settings. Fixed as a result: duplicate close buttons in the mobile drawer, selected toggles indistinguishable in dark mode, chunking-sweep labels dropped, embedding-model select overflowing its column, "% points" wording.
- Playwright screenshots at every viewport and theme were reviewed. Fixed as a result: evidence cards and sidebar titles clipped by Radix ScrollArea (`display: table`), charts captured mid-animation, isolated words highlighted on cited pages.

## 5. Known gaps

- Relevance labels were AI-assisted (one annotator); 63 questions.
- Generation quality is keyword-scored; small models can give grounded but off-target answers.
- OCR, CUDA, Linux/Windows and Safari/Firefox were not exercised (Playwright runs Chromium only).
- All runs used one laptop under heavy memory pressure (7–13 GB swap in use).
