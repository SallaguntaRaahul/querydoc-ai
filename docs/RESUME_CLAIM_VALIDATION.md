# Resume Claim Validation

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

This document checks the intended resume statement claim by claim against what was
built and measured. Each verdict cites a raw evidence file. A target that was not met
stays FAIL, and a claim that holds only under conditions says what those conditions are.
Paths are relative to the repository root.

## Intended (target) statement

> "Designed an end-to-end RAG pipeline using LangChain, FAISS vector search, and SentenceTransformers with Hugging Face open LLMs for on-device generative responses, achieving a 40% improvement in context relevance and sub-300ms query latency across 100+ page documents, with batched embeddings reducing memory footprint by 35% and supporting concurrent document queries on commodity hardware."

## Claim-to-evidence table

| # | Claim | Exact interpretation used | Implementation | Test / benchmark | Raw evidence | Measured result | Verdict | Important limitations |
|---|---|---|---|---|---|---|---|---|
| 1 | End-to-end RAG pipeline | Upload PDF in the UI → extract → chunk → embed → index → retrieve → generate → verified, clickable page citations | `backend/querydoc/services/rag_service.py` (`ingest`, `answer_stream`), `backend/app/api/v1/*`, `frontend/src/pages/chat-page.tsx` | Playwright `e2e/app.spec.ts` (real stack, real models); API tests; engine tests | `results/tests/playwright-junit.xml`, `results/tests/junit.xml`, `docs/images/ui/` | Full journey passes in a real browser: upload 183-page PDF → streamed answer → citation opens the cited page | **PASS** | Local single-user; no authentication |
| 2 | LangChain | LangChain components used where they add value | `backend/querydoc/chunking/chunkers.py` (`RecursiveCharacterTextSplitter`, `Document`), `generation/prompts.py` (`ChatPromptTemplate`) | `tests/unit/test_chunking.py` | `results/tests/junit.xml` | Splitting, document model and prompt templating | **PASS** | Retrieval, vector store and LLM calls are custom code (LangChain's FAISS store persists metadata with pickle) |
| 3 | FAISS vector search | Local FAISS index with persistence, filtering, deletion | `backend/querydoc/vectorstore/faiss_store.py` (`IndexIDMap2(IndexFlatIP)`, HNSW optional) | unit + API delete/reindex tests | `results/tests/junit.xml`, `results/retrieval_latency/results.json` | Exact search 0.1–0.2 ms on 1,532 vectors; delete removes vectors (API test) | **PASS** | Flat index; HNSW not needed at this scale |
| 4 | SentenceTransformers | Embeddings by a SentenceTransformers model | `backend/querydoc/embeddings/embedder.py` (all-MiniLM-L6-v2), cross-encoder reranker | unit + benchmarks | `results/embeddings/results.json` | 384-d normalised embeddings, 81–106 chunks/s on CPU | **PASS** | 256-token window truncates long chunks |
| 5 | Hugging Face open LLMs, on-device | Open-weight HF model generating locally, no API key | `backend/querydoc/generation/llm.py` (Qwen2.5-1.5B-Instruct, Apache-2.0) | engine e2e, Playwright, `benchmark_generation.py`, `benchmark_api.py` | `results/generation/results.json`, `results/api_e2e/results.json` | Runs on Apple GPU; 84% keyword accuracy (held-out); ~18 tok/s; streamed to the browser over SSE | **PASS** | Small model; occasional off-target answers |
| 6 | 100+ page documents | Ingest, index and query ≥ 100-page PDFs | `backend/querydoc/ingestion/pdf_loader.py`, background worker | Playwright upload test (183 pages), `benchmark_ingestion.py`, `benchmark_api.py` | `results/ingestion/results.json`, `results/api_e2e/results.json` | 183-page NIST SP 800-37r2: 10.8 s engine, **12.9 s upload → ready via the API**; 391-page corpus queried | **PASS** | Scanned PDFs need optional OCR (Tesseract); OCR is tested on synthetic image-only pages, not on real-world scans |
| 7 | 40% improvement in context relevance | Context Relevance = mean nDCG@5 with evidence-span relevance, defined before experiments (commit `ffad4b0`); optimized config chosen on the dev split; ≥ 40% on the **held-out test split** | `backend/querydoc/retrieval/retriever.py` (BM25 + dense RRF, dedup, cross-encoder top-20) | `benchmarks/benchmark_relevance.py` | `results/relevance/results.json`, `per_query.csv` | Test: 0.578 → 0.831 = **+43.8%** (95% CI +16.6…+90.6%); all 63: **+36.7%** | **PASS** (test split) — below 40% on the full set | 63 questions / 4 documents; AI-assisted labels; wide CI; baseline is plain dense retrieval |
| 8a | Sub-300 ms query latency — **retrieval** | Warm retrieval p95 < 300 ms on every ≥ 100-page dataset | retriever with reranker on Apple GPU (`reranker_device=auto`) | `benchmarks/benchmark_retrieval.py` (200 queries × 3 trials) | `results/retrieval_latency/results.json` | p50 51–73 ms, **p95 58–103 ms** | **PASS** (GPU reranker) | Needs the laptop's integrated GPU |
| 8b | …retrieval **through the HTTP API** | request → SSE evidence event, real server, 4-document index | FastAPI SSE bridge | `benchmarks/benchmark_api.py` (31 questions) | `results/api_e2e/results.json` | **p50 100 ms, p95 269 ms** | **PASS** (GPU reranker) | Close to the limit under heavy swap; single client |
| 8c | …retrieval, **CPU only** | same, reranker on CPU | same | `--reranker-device cpu` | `results/retrieval_latency_cpu/results.json` | **p95 175–244 ms** on 100–391 pages (was 541–556 ms before 256-token truncation, chosen in `results/cpu_profile`) | **PASS** (Apple M3 Pro CPU, 4 threads) | Slower CPUs may exceed 300 ms |
| 8d | …**full answer** | question → complete generated, verified answer | engine + API | `benchmark_generation.py`, `benchmark_api.py` | `results/api_e2e/results.json` | p50 **2.0 s**, p95 4.7 s; first token p50 1.08 s | **FAIL** | Never claim sub-300 ms *responses* |
| 9 | Batched embeddings reduce memory by 35% | Peak RSS embedding a 183-page document: bounded mini-batches vs **unbatched single pass** | `embeddings/embedder.py::embed_texts` | `benchmarks/benchmark_embeddings.py` (fresh process, 3 reps) | `results/embeddings/results.json` | **−78.5%** (4,502 → 970 MB); vs batch-256 −52.8%; vs library default batch-32 ±0% | **PASS** (as interpreted) | Saving comes from bounding batch size, not from custom code |
| 10 | Concurrent document queries | Simultaneous queries over a multi-document index without errors or corruption | RW lock, shared GPU lock, `GenerationGate`, thread-safe API | `benchmark_concurrency.py`, API concurrency tests | `results/concurrency/results.json`, `results/tests/junit.xml` | Retrieval 1–20 users: **0 errors**, ~12 req/s; generation 0 errors ≤ 5 users, bounded rejection (429) beyond | **PASS** (retrieval) / partial (generation) | Throughput does not scale with users (single reranker, serialised GPU) |
| 11 | Full-stack product (React + FastAPI) | Typed React SPA + documented REST/SSE API, tested in a real browser | `frontend/`, `backend/app/` | 22 API tests, 22 Vitest, 22 Playwright (10 functional + 12 visual) | `results/tests/*.xml`, `results/app/launch.json`, `docs/images/ui/` | All pass; builds; launches as one process | **PASS** | Chromium only; no auth |
| — | "Commodity hardware" | A consumer laptop, no server GPU | — | — | `environment` blocks | Apple M3 Pro MacBook Pro, 18 GB | **PASS** with caveat | Latency claims depend on its integrated GPU |

## Verified Resume Bullet

Uses only demonstrated functionality and measured results:

> **Built QueryDoc AI, a local PDF question-answering app (React/TypeScript, FastAPI, LangChain, SentenceTransformers, FAISS, Hugging Face Transformers) that streams answers from an on-device Qwen2.5 model with verified, clickable page-level citations; improved retrieval nDCG@5 by 44% on held-out questions (0.58 → 0.83) using BM25 hybrid search and cross-encoder reranking, kept retrieval p95 under 130 ms on 180+ page PDFs (269 ms end to end over HTTP), cut embedding peak memory 78% with bounded batching, and served 20 concurrent retrieval users with zero errors.**

Shorter variant:

> Built a full-stack local PDF RAG app (React, FastAPI, FAISS, SentenceTransformers, Hugging Face Qwen2.5) with streamed answers and verified page citations; +44% retrieval nDCG@5 on held-out questions, < 130 ms p95 retrieval on 180+ page PDFs, 78% lower embedding peak memory.

If asked: "+44% on the 31 held-out test questions, +37% across all 63; the interval is wide because the benchmark is small. The latency figures are for retrieval with the reranker on the laptop GPU; full answers take about 2 seconds."

## Target Resume Bullet (original wording, partly unverified)

> Designed an end-to-end RAG pipeline using LangChain, FAISS vector search, and SentenceTransformers with Hugging Face open LLMs for on-device generative responses, achieving a 40% improvement in context relevance *[verified on the held-out split: +43.8%; +36.7% on all questions]* and sub-300ms query latency *[verified for retrieval, GPU and CPU reranker, incl. over HTTP; full generated responses are NOT sub-300 ms]* across 100+ page documents, with batched embeddings reducing memory footprint by 35% *[verified against unbatched encoding: −78.5%; no reduction versus the library's default batching]* and supporting concurrent document queries *[verified for retrieval, 0 errors at 1–20 users; throughput does not scale]* on commodity hardware.

Do not use the target wording without those qualifications.
