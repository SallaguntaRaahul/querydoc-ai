# Resume Claim Validation

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

This document checks the intended resume statement claim by claim against what was
built and measured. Each verdict cites a raw evidence file. A target that was not met
stays FAIL, and a claim that holds only under conditions says what those conditions are.

## Intended (target) statement

> "Designed an end-to-end RAG pipeline using LangChain, FAISS vector search, and SentenceTransformers with Hugging Face open LLMs for on-device generative responses, achieving a 40% improvement in context relevance and sub-300ms query latency across 100+ page documents, with batched embeddings reducing memory footprint by 35% and supporting concurrent document queries on commodity hardware."

## Claim-to-evidence table

| # | Claim | Exact interpretation used | Implementation | Test / benchmark | Raw evidence | Measured result | Verdict | Important limitations |
|---|---|---|---|---|---|---|---|---|
| 1 | End-to-end RAG pipeline | PDF → extract → chunk → embed → index → retrieve → generate → cited answer, in one working app | `src/querydoc/services/rag_service.py` (`QueryDocService.ingest`, `.answer`), `app/main.py` | `tests/integration/test_service.py`, `tests/e2e/test_generation.py`, manual UI run | `results/tests/junit.xml`, `docs/images/ui_*.jpg`, `results/streamlit/launch.json` | 97/97 tests pass; UI answered with page citations | **PASS** | Single-user, single-process; no auth |
| 2 | LangChain | LangChain components used where they add value | `chunking/chunkers.py` (`RecursiveCharacterTextSplitter`, `Document`), `generation/prompts.py` (`ChatPromptTemplate`) | `tests/unit/test_chunking.py` | `results/tests/junit.xml` | Used for splitting, document model and prompt templating | **PASS** | Retrieval, vector store and LLM calls are custom code, not LangChain chains (LangChain's FAISS store persists metadata with pickle) |
| 3 | FAISS vector search | Local FAISS index with persistence, filtering, deletion | `vectorstore/faiss_store.py` (`IndexIDMap2(IndexFlatIP)`, HNSW optional) | `tests/unit/test_embeddings_and_store.py` | `results/tests/junit.xml`, `results/retrieval_latency/results.json` (`vector_search` 0.1–0.2 ms) | Exact search < 0.3 ms on 1,532 vectors | **PASS** | Flat index; HNSW implemented but not needed or benchmarked at this scale |
| 4 | SentenceTransformers | Embeddings produced by a SentenceTransformers model | `embeddings/embedder.py` (`all-MiniLM-L6-v2`), `retrieval/retriever.py` (`CrossEncoder`) | unit + benchmarks | `results/embeddings/results.json` | 384-d normalised embeddings, 81–106 chunks/s on CPU | **PASS** | 256-token input window truncates long chunks |
| 5 | Hugging Face open LLMs, on-device | Open-weight HF model generating locally, no API | `generation/llm.py` (`Qwen/Qwen2.5-1.5B-Instruct`, Apache-2.0) | `tests/e2e/test_generation.py`, `benchmark_generation.py` | `results/generation/results.json` | Runs on Apple GPU (MPS); 84% keyword accuracy on held-out questions; 18 tok/s | **PASS** | Small model; occasional off-target answers; generation p50 1.9 s |
| 6 | 100+ page documents | Ingest, index and query documents of ≥ 100 pages | `ingestion/pdf_loader.py` | `benchmark_ingestion.py`, `benchmark_retrieval.py`, `test_large_document_preserves_page_numbers` | `results/ingestion/results.json` | 183-page NIST SP 800-37r2 in 10.8 s; 200-page synthetic in 3.5 s; 391-page corpus queried | **PASS** | Scanned PDFs need optional OCR (not tested) |
| 7 | 40% improvement in context relevance | Context Relevance = mean nDCG@5 with evidence-span relevance, defined before experiments (commit `ffad4b0`); optimized config chosen on dev split; ≥ 40% relative on the **held-out test split** | `retrieval/retriever.py` (hybrid BM25+dense, dedup, cross-encoder rerank top-20) | `benchmarks/benchmark_relevance.py` | `results/relevance/results.json`, `per_query.csv` | Test: 0.578 → 0.831 = **+43.8%** (95% CI +16.6 … +90.6%); all 63 questions: 0.601 → 0.821 = **+36.7%** | **PASS** (test split) — below 40% on the full set | 63 questions / 4 documents; AI-assisted labels; wide CI; baseline is a plain dense retriever |
| 8a | Sub-300 ms query latency — **retrieval** | Warm retrieval (query → ranked passages) p95 < 300 ms on every ≥ 100-page dataset, optimized pipeline | `retrieval/retriever.py`, reranker on Apple GPU (`reranker_device=auto`) | `benchmarks/benchmark_retrieval.py` (200 queries × 3 trials) | `results/retrieval_latency/results.json` | p50 49–80 ms, **p95 55–129 ms** | **PASS** (with GPU reranker) | Needs the laptop's integrated GPU |
| 8b | Sub-300 ms — retrieval, **CPU only** | same, reranker on CPU | same | same with `--reranker-device cpu` | `results/retrieval_latency_cpu/results.json` | Synthetic 100–200 pp: p95 159–167 ms; **real NIST docs: p95 541–556 ms** | **FAIL** | CPU-only users should use `RERANK_K=10` or dense-only (p95 ≈ 18 ms, lower quality) |
| 8c | Sub-300 ms — **full answer** | question → generated cited answer | `services/rag_service.py` | `benchmarks/benchmark_generation.py` | `results/generation/results.json` | p50 1.9 s, p95 4.4 s (1.5B); p50 0.53 s (0.5B) | **FAIL** | Never claim sub-300 ms *responses*; only retrieval |
| 9 | Batched embeddings reduce memory by 35% | Peak process RSS embedding a 183-page document: bounded mini-batches (QueryDoc streaming, 32) vs **unbatched single pass** | `embeddings/embedder.py::embed_texts` | `benchmarks/benchmark_embeddings.py` (fresh process, 3 reps) | `results/embeddings/results.json` | **−78.5%** (4,502 → 970 MB); vs batch-256 −52.8%; vs batch-128 −35.1%; vs library default batch-32 **±0%** | **PASS** (as interpreted) | The saving is from bounding batch size; QueryDoc's wrapper is no better than calling `encode(batch_size=32)` |
| 10 | Concurrent document queries | Multiple simultaneous queries over a multi-document index without errors or corruption | RW lock (`faiss_store.py`), device lock (`devices.py`), `GenerationGate` | `benchmark_concurrency.py`, `test_concurrent_retrieval_during_ingest` | `results/concurrency/results.json` | Retrieval: 1–20 users, 380 requests, **0 errors**, ~12 req/s. Generation: 0 errors ≤ 5 users; at 10–20 users back-pressure rejects + 7 timeouts | **PASS** (retrieval) / partial (generation) | Throughput does not scale with users (single reranker, serialised GPU); 20 concurrent generations not supported |
| — | "Commodity hardware" | A consumer laptop, no server GPU | — | — | `environment` blocks | Apple M3 Pro MacBook Pro, 18 GB | **PASS** with caveat | Latency claim depends on its integrated GPU; CPU-only misses it |

## Verified Resume Bullet

Uses only demonstrated functionality and measured results:

> **Built QueryDoc AI, a local PDF question-answering system (Python, LangChain, SentenceTransformers, FAISS, Hugging Face Transformers, Streamlit) that answers with verified page-level citations using an on-device Qwen2.5 LLM; improved retrieval nDCG@5 by 44% on held-out questions (0.58 → 0.83) with BM25 hybrid search and cross-encoder reranking, held warm retrieval p95 under 130 ms on 180+ page documents on a laptop GPU, cut embedding peak memory 78% through bounded batching, and served up to 20 concurrent retrieval users with zero errors.**

Shorter variant:

> Built a local PDF RAG system (LangChain, FAISS, SentenceTransformers, Hugging Face Qwen2.5) with verified page citations; +44% retrieval nDCG@5 on held-out questions, < 130 ms p95 retrieval on 180+ page PDFs, 78% lower embedding peak memory.

If asked, be ready to say: "+44% on the 31 held-out test questions, +37% across all 63; the confidence interval is wide because the benchmark is small."

## Target Resume Bullet (original wording, partly unverified)

> Designed an end-to-end RAG pipeline using LangChain, FAISS vector search, and SentenceTransformers with Hugging Face open LLMs for on-device generative responses, achieving a 40% improvement in context relevance *[verified on the held-out split: +43.8%; +36.7% on all questions]* and sub-300ms query latency *[verified for retrieval with a GPU reranker only; CPU-only retrieval and full generated responses are NOT sub-300 ms]* across 100+ page documents, with batched embeddings reducing memory footprint by 35% *[verified against unbatched encoding: −78.5%; no reduction versus the library's default batching]* and supporting concurrent document queries *[verified for retrieval, 0 errors at 1-20 users; throughput does not scale]* on commodity hardware.

Do not use the target wording without those qualifications.
