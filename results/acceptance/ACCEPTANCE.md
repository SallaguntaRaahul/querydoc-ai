# Acceptance results

Generated 2026-10-19T19:52:55+00:00 by `python scripts/acceptance.py`.

| Requirement | Target | Status | Measured | Evidence |
|---|---|---|---|---|
| PDF ingestion | Works for 100+ pages | **PASS** | synthetic_100p.pdf: 100 pages in 1.8s, synthetic_200p.pdf: 200 pages in 3.5s, NIST.SP.800-37r2.pdf: 183 pages in 10.8s | `results/ingestion/results.json` |
| Multiple PDFs | Functional | **PASS** | test_multi_document_isolation_and_delete: passed | `results/tests/junit.xml` |
| Local embeddings | Functional | **PASS** | 11 strategies benchmarked | `results/embeddings/results.json` |
| FAISS indexing | Functional | **PASS** | test_store_add_search_filter_delete: passed | `results/tests/junit.xml` |
| Persistent indexes | Functional | **PASS** | test_index_persists_across_restart: passed | `results/tests/junit.xml` |
| Local Hugging Face LLM | Functional | **PASS** | Qwen/Qwen2.5-0.5B-Instruct on mps; Qwen/Qwen2.5-1.5B-Instruct on mps | `results/generation/results.json` |
| Citation-grounded answers | Tested | **PASS** | test_supported_question_answered_with_valid_citation: passed | `results/tests/junit.xml` |
| Retrieval latency | p95 < 300 ms on 100+ page docs (optimized pipeline, warm) | **PASS** | worst p95 128 ms / p50 80 ms (nist_800-37r2_183p) | `results/retrieval_latency/results.json` |
| Retrieval latency, CPU-only reranker | p95 < 300 ms on 100+ page docs | **FAIL** | worst p95 556 ms (nist_800-37r2_183p) | `results/retrieval_latency_cpu/results.json` |
| End-to-end answer latency (default LLM) | < 300 ms (stretch; not a stated target) | **FAIL** | p50 1.9 s, p95 4.4 s | `results/generation/results.json` |
| Context relevance improvement | >= 40% relative (nDCG@5, held-out test split) | **PASS** | 0.578 -> 0.831 = +43.8% (CI95 +17..+91%); all 63 questions +36.7% | `results/relevance/results.json` |
| Peak-memory reduction | >= 35% peak RSS, batched streaming vs unbatched single pass | **PASS** | 78.5% vs single pass; 52.8% vs batch-256; -0.8% vs library default batch-32 | `results/embeddings/results.json` |
| Concurrent generation | info: bounded admission control | **PASS** | 0 errors up to 5 users; 10u: {'QueueFullError': 3, 'GenerationTimeoutError': 3}, 20u: {'QueueFullError': 23, 'GenerationTimeoutError': 4} | `results/concurrency/results.json` |
| Concurrent retrieval | Tested at multiple loads | **PASS** | 1u: 12 rps p95 110 ms, 2u: 12 rps p95 198 ms, 5u: 12 rps p95 516 ms, 10u: 12 rps p95 935 ms, 20u: 13 rps p95 1711 ms | `results/concurrency/results.json` |
| Streamlit application | Launches successfully | **PASS** | healthy in 1.03 s | `results/streamlit/launch.json` |
| Automated tests | Pass | **PASS** | 97 tests, 0 failures, 0 errors, 0 skipped | `results/tests/junit.xml` |
| Documentation | Complete | **PASS** | all required documents present | `docs/` |
