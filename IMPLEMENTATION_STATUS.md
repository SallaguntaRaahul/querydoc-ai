# QueryDoc AI — Implementation Status

Author: Raahul Sallagunta · Last updated: 2026-10-19

This file tracks progress so work can be resumed. Final, evidence-linked status
lives in `results/acceptance/ACCEPTANCE.md` and `docs/RESUME_CLAIM_VALIDATION.md`.

| # | Phase | Status | Notes |
|---|---|---|---|
| 1 | Environment & repo inspection | Done | Apple M3 Pro, 18 GB RAM, macOS 26.5, Python 3.12 venv, MPS available |
| 2 | Architecture & dependency selection | Done | see `docs/TECH_STACK_DECISIONS.md` |
| 3 | PDF ingestion | Done | PyMuPDF; rotated-text filter; scanned/blank detection; limits |
| 4 | Chunking | Done | fixed / recursive (LangChain) / sentence; page ranges |
| 5 | Embeddings | Done | all-MiniLM-L6-v2, streaming batches, content-hash cache |
| 6 | FAISS + persistence | Done | IndexIDMap2(Flat/HNSW), checksummed manifest, atomic save |
| 7 | Retrieval & relevance | Done | BM25 hybrid (RRF), dedup, MMR, cross-encoder rerank |
| 8 | Local HF generation | Done | Qwen2.5-0.5B-Instruct default (Apache-2.0), MPS/CPU |
| 9 | Citations | Done | tag parsing, existence/doc checks, lexical support scoring |
| 10 | Streamlit app | Done | workspace, chat, source explorer w/ page render, perf tab |
| 11 | Concurrency controls | Done | RW lock on index, generation gate (active/queue/timeout) |
| 12 | Automated tests | In progress | unit / integration / e2e (LLM) / performance / security |
| 13 | Benchmarks | In progress | `benchmarks/`, raw results in `results/` |
| 14 | Optimization & retest | In progress | see `docs/EXPERIMENTS.md` |
| 15 | Documentation | In progress | `docs/` |
| 16 | Acceptance validation | In progress | `scripts/acceptance.py` |
| 17 | Handover | In progress | README + final report |

## Known open items
- License not selected (author decision required) — see README "License".
- OCR is an optional extension (`QUERYDOC_ENABLE_OCR=true` + Tesseract); not exercised in tests.

## Notable engineering issues encountered
- macOS: FAISS and PyTorch wheels each bundle `libomp`; loading both segfaults/deadlocks.
  Fixed via `OMP_NUM_THREADS=1` at package import + `torch.set_num_threads()` and importing
  torch before faiss. See `docs/TROUBLESHOOTING.md`.
- NIST PDFs carry a rotated sidebar watermark that plain extraction interleaved into body
  sentences; extraction now keeps horizontal lines only.
