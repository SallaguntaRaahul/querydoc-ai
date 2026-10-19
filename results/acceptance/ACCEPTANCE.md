# Acceptance results

Generated 2026-10-19T21:47:52+00:00 by `python scripts/acceptance.py`.

## Definition of done

| Requirement | Target | Status | Measured | Evidence |
|---|---|---|---|---|
| 1. React frontend builds | vite build succeeds | **PASS** | built in 1.6 s | `results/app/launch.json` |
| 2. FastAPI backend starts | health OK, SPA + OpenAPI served | **PASS** | healthy in 9.12 s; 15 API paths | `results/app/launch.json` |
| 3–4. Real PDF uploaded and indexed (incl. 183 pages) | Playwright test passes | **PASS** | upload: validation error, then two real PDFs index (including 183 pages): passed | `results/tests/playwright-junit.xml` |
| 5–7. Question retrieves evidence, local LLM answers, citation opens the page | Playwright test passes | **PASS** | ask a question: streamed answer with citations, open the cited page: passed | `results/tests/playwright-junit.xml` |
| 8. Conversations persist (follow-up, reload, history) | Playwright test passes | **PASS** | follow-up question, persistence after reload, reopen from history: passed | `results/tests/playwright-junit.xml` |
| 9. Settings work (validation + persistence) | Playwright test passes | **PASS** | settings: invalid input is blocked, valid change persists: passed | `results/tests/playwright-junit.xml` |
| 10. Analytics shows real data | Playwright test passes | **PASS** | analytics shows live telemetry and benchmark evidence: passed | `results/tests/playwright-junit.xml` |
| Stop generation | Playwright test passes | **PASS** | stop a generation mid-stream: passed | `results/tests/playwright-junit.xml` |
| Delete document and index entries | Playwright test passes | **PASS** | delete a document removes it and its index entries: passed | `results/tests/playwright-junit.xml` |
| 11. Automated tests — backend pytest | 0 failures, 0 errors | **PASS** | 119 tests, 0 failed, 0 errors, 0 skipped | `results/tests/junit.xml` |
| 11. Automated tests — frontend Vitest | 0 failures, 0 errors | **PASS** | 22 tests, 0 failed, 0 errors, 0 skipped | `results/tests/vitest-junit.xml` |
| 12. End-to-end tests (Playwright, real stack) | all pass | **PASS** | 10/10 passed | `results/tests/playwright-junit.xml` |
| 13. Visual inspection (desktop/tablet/mobile × dark/light, states) | visual specs pass and screenshots captured | **PASS** | 12/12 visual checks; 33 screenshots | `docs/images/ui/` |
| 14. Benchmark results recorded | all benchmark result files present | **PASS** | 8/8: relevance, retrieval_latency, retrieval_latency_cpu, embeddings, concurrency, generation, ingestion, api_e2e | `results/` |
| 15. Documentation complete | all required documents present | **PASS** | all present | `docs/` |
| 16. Every resume claim has an evidence status | claim table with statuses | **PASS** | 15 verdicts in claim table | `docs/RESUME_CLAIM_VALIDATION.md` |

## Performance targets

| Requirement | Target | Status | Measured | Evidence |
|---|---|---|---|---|
| Context relevance improvement | ≥ 40% relative nDCG@5 (held-out test split) | **PASS** | 0.578 → 0.831 = +43.8% (CI95 +17…+91%); all 63: +36.7% | `results/relevance/results.json` |
| Retrieval latency, 100+ pages (GPU reranker) | p95 < 300 ms | **PASS** | worst p95 128 ms, p50 80 ms (nist_800-37r2_183p) | `results/retrieval_latency/results.json` |
| Retrieval latency, 100+ pages (CPU-only reranker) | p95 < 300 ms | **FAIL** | worst p95 556 ms, p50 274 ms (nist_800-37r2_183p) | `results/retrieval_latency_cpu/results.json` |
| Peak-memory reduction | ≥ 35% peak RSS (batched vs unbatched embedding) | **PASS** | 78.5% vs unbatched; 52.8% vs batch-256; -0.8% vs library default | `results/embeddings/results.json` |
| Concurrent retrieval | tested at ≥ 3 loads, 0 errors | **PASS** | 1u 12.2 rps p95 110 ms, 2u 11.6 rps p95 198 ms, 5u 11.9 rps p95 516 ms, 10u 12.1 rps p95 935 ms, 20u 12.5 rps p95 1711 ms | `results/concurrency/results.json` |
| Local LLM generation latency (engine) | measured (no target) | **PASS** | p50 1.81 s, TTFT p50 0.96 s, 18.2 tok/s | `results/generation/results.json` |
| End-to-end answer latency via HTTP API | < 300 ms (stretch, not a stated target) | **FAIL** | evidence p50 100 ms · first token p50 1078 ms · total p50 2.05 s / p95 4.66 s | `results/api_e2e/results.json` |
