# Testing and Validation

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

This guide explains what is tested, how to reproduce every result, and how the
acceptance verdicts are derived. Latest executed results: `results/tests/junit.xml`
(test suite) and `results/acceptance/ACCEPTANCE.md` (acceptance table).

## 1. Setup

```bash
uv venv -p 3.12 .venv.nosync && ln -s .venv.nosync .venv   # .nosync: see TROUBLESHOOTING #2
source .venv/bin/activate
uv pip install -e ".[dev]"
python scripts/download_corpus.py        # NIST evaluation PDFs, checksum-verified
```
Models download on first use into `~/.cache/huggingface` (MiniLM ~90 MB, cross-encoder ~90 MB,
Qwen2.5-0.5B-Instruct ~1 GB). After that, `HF_HUB_OFFLINE=1` works.

## 2. Test suite layout

| Folder | Kind | What it proves |
|---|---|---|
| `tests/unit/test_ingestion.py` | unit | text cleaning & soft-wrap reflow; filename sanitisation (traversal, control chars); rejects non-PDF, empty, corrupt, oversized, too-many-pages, password-protected; blank & image-only page detection; 120-page extraction keeps page numbers; stable content-hash ids; rotated watermark text excluded |
| `tests/unit/test_chunking.py` | unit | all three strategies respect size and exact offsets; page ranges incl. cross-page chunks; empty pages keep numbering; stable unique ids; overlap; min-length filter; invalid configs; LangChain `Document` round trip |
| `tests/unit/test_embeddings_and_store.py` | unit | normalised float32 vectors; batched == unbatched; duplicate texts encoded once; cache hit rate; cache persistence/model mismatch/corruption; FAISS flat **and** HNSW add/search/filter/delete; dimension check; persistence round trip; model mismatch, tampered files and garbage manifests rejected |
| `tests/unit/test_retrieval_citations.py` | unit | tokenizer; dedup; MMR; evidence-span location & coverage; IR metrics; relative improvement; prompt delimiter defusing & token budget; citation verification (valid, invalid tag, uncited claim, unsupported claim, no citations, tag-only answer, insufficient evidence, other-document citation, stale chunk); generation gate queue-full and timeout |
| `tests/unit/test_security.py` | security | no pickle/eval anywhere in `src/`; `allow_pickle` only ever `False`; pickled object arrays in the cache are refused; filenames never contain path components; oversized upload rejected before parsing; tampered manifest rejected; injected text cannot escape `<source>` or reach the system role; citations cannot reference unselected documents |
| `tests/integration/test_service.py` | integration | ingest → retrieve finds every planted fact on the right page (120-page PDF, production config); duplicate upload rejected; invalid upload leaves index untouched; scanned-only PDF reports OCR disabled; multi-document filter isolation and delete; `document_path` traversal rejected; index survives restart; off-topic question declined without the LLM; retrieval-only fallback when the LLM is unavailable; 60 concurrent queries during 3 concurrent ingests, persisted index still consistent |
| `tests/e2e/test_generation.py` | end-to-end (real Qwen model) | supported question answered with the right code and a valid citation to the right page; citations ⊆ retrieved chunks; unsupported question declined; instruction injected into a PDF page is not obeyed; document filter restricts citations |
| `tests/performance/test_latency_smoke.py` | performance guard | warm retrieval p95 < 300 ms on a 120-page PDF with hybrid + rerank |

Markers: `slow` (model-heavy), `llm` (needs the cached generation model; auto-skipped otherwise).

## 3. Commands

```bash
pytest -q                                          # everything (LLM tests skip if model not cached)
pytest -m "not llm"                                # what CI runs
pytest --junitxml=results/tests/junit.xml          # write evidence for the acceptance script
ruff check src app benchmarks scripts tests
mypy
python scripts/check_streamlit.py                  # headless launch + health + page served
python benchmarks/run_all_benchmarks.py            # all benchmarks + charts (~45-60 min)
python scripts/acceptance.py                       # PASS/FAIL table → results/acceptance/
```

## 4. How acceptance verdicts are derived

`scripts/acceptance.py` reads evidence files only — it never re-labels a result:

| Criterion | Evidence | PASS rule |
|---|---|---|
| PDF ingestion 100+ pages | `results/ingestion/results.json` | a document with ≥ 100 pages ingested |
| Multiple PDFs, FAISS, persistence, citations | `results/tests/junit.xml` | the named test case passed (skipped ⇒ BLOCKED, missing ⇒ NOT TESTED) |
| Local HF LLM | `results/generation/results.json` | generated answers recorded |
| Retrieval latency | `results/retrieval_latency/results.json` | optimized pipeline p95 < 300 ms on **every** dataset ≥ 100 pages |
| Context relevance | `results/relevance/results.json` | nDCG@5 relative improvement ≥ 40% on the **held-out test split** |
| Peak memory | `results/embeddings/results.json` | peak RSS reduction ≥ 35% (batched streaming vs unbatched single pass); the stricter batch-256 comparison is shown alongside |
| Concurrent retrieval | `results/concurrency/results.json` | ≥ 3 load levels and 0 errors |
| Streamlit | `results/streamlit/launch.json` | health endpoint `ok` and page served |
| Tests | `results/tests/junit.xml` | 0 failures, 0 errors |
| Documentation | files in `docs/` | all required files present |

Functional tests never count as benchmark passes, and a missed target is reported as FAIL.

## 5. Manual UI verification

The app was launched and exercised in a browser (see `docs/images/ui_*.png`, captured from the
running app): upload, chat with citations, "Open page" rendering with the excerpt highlighted,
and the performance tab.

## 6. Known gaps in validation

- Evaluation labels were authored with AI assistance during development and not reviewed by a second annotator.
- 63 questions over 4 documents is a small benchmark; confidence intervals are reported for that reason.
- Generation quality is scored with keyword matching, not human judgment.
- OCR, CUDA, and Linux/Windows were not exercised (CI covers Linux without the LLM).
- The latency/memory numbers come from one laptop under real background load (swap in use); see each result's `environment` block.
