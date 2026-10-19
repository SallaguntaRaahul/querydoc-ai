# Technology Stack Decisions

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

Every dependency is listed with what it does, why it is here, where it is used,
the alternatives considered and when the choice should be revisited. Versions are
the ones installed and measured (`results/*/results.json → environment.packages`).

## Decision matrix (summary)

| Concern | Chosen | Main alternatives | Why chosen | Revisit when |
|---|---|---|---|---|
| Language | Python 3.12 | Java, TypeScript, Go | The ML ecosystem (PyTorch, HF, FAISS bindings) is Python-first | Serving needs > 1 process per model, or a typed backend team owns it |
| PDF parsing | PyMuPDF 1.27 | pdfplumber, pypdf, pdfminer.six, Unstructured, Docling | Fastest pure-local option, exposes per-line direction (used to drop rotated watermarks), renders pages for citation previews | Complex tables/forms/OCR become core requirements |
| Text splitting | LangChain `RecursiveCharacterTextSplitter` (+ own fixed & sentence splitters) | LlamaIndex node parsers, NLTK/spaCy sentence splitters, semantic chunking | Well-known, separator hierarchy, `add_start_index` gives exact offsets for page mapping | Structure-aware (heading/table) chunking is needed |
| Embeddings | SentenceTransformers + `all-MiniLM-L6-v2` (384-d) | bge-small/base, e5-small, gte-small, nomic-embed, OpenAI embeddings | 22 M params, ~90 MB, fast on CPU, Apache-2.0, already the de-facto baseline | Retrieval quality is the bottleneck (try bge-small/e5 first) |
| Vector index | FAISS `IndexIDMap2(IndexFlatIP)` (HNSW optional) | Chroma, Qdrant, pgvector, Pinecone, Milvus, Weaviate | In-process, zero ops, exact search is < 1 ms at this scale, supports ID removal + ID-selector filtering | > ~1 M vectors per node, multi-node, rich metadata filters, multi-tenant ACLs |
| Lexical retrieval | `rank-bm25` (Okapi BM25) fused by RRF | Elasticsearch/OpenSearch, Tantivy, SQLite FTS5 | Pure Python, no service; corpus is a few thousand chunks | Corpus grows beyond ~100 k chunks (BM25Okapi rescans all docs per query) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | bge-reranker-base, Cohere Rerank, ColBERT | Small (22 M), strong MS MARCO reranker, local | Latency budget allows a larger reranker or domain shift hurts quality |
| Generation | HF Transformers + `Qwen/Qwen2.5-0.5B-Instruct` (Apache-2.0) | Qwen2.5-1.5B/3B, Llama-3.2-1B/3B (gated license), Phi-3.5-mini, llama.cpp/GGUF, Ollama, vLLM | Ungated, permissive license, runs on MPS/CPU in ~1 GB, chat template supported | Answer quality matters more than latency, or a GPU server is available (vLLM) |
| Tensor runtime | PyTorch 2.x (CPU + Apple MPS) | ONNX Runtime, MLX, llama.cpp | Required by Transformers and SentenceTransformers; MPS gives free GPU on Apple silicon | Need int4/int8 quantized CPU inference (llama.cpp / ONNX) |
| UI | Streamlit | FastAPI + React, Gradio, Chainlit | Fastest path to a usable, Python-only app with caching primitives (`st.cache_resource`) | Multi-user auth, custom UX or horizontal scaling is required |
| Config | pydantic-settings | dynaconf, plain env vars | Typed, validated, `.env` support, `QUERYDOC_` prefix | — |
| Data analysis | NumPy, Pandas | Polars | NumPy is the embedding/FAISS interchange format; Pandas renders tables in Streamlit | — |
| Testing | pytest, Ruff, mypy, GitHub Actions | unittest, flake8+black, pyright | Standard Python tooling | — |
| Metrics | psutil, `time.perf_counter` | tracemalloc, memray, py-spy | RSS includes native (torch/faiss) memory that tracemalloc cannot see | Need allocation-level attribution (memray) |

---

## Python
- **What:** the implementation language for everything (library, app, benchmarks, tests).
- **Why needed / chosen:** PyTorch, Transformers, SentenceTransformers, FAISS and PyMuPDF all ship first-class Python APIs; there is no glue layer.
- **Internals relevant here:** the GIL serialises pure-Python bytecode, but PyTorch, FAISS and tokenizers release it inside native kernels, which is why thread-based concurrency still scales retrieval (`results/concurrency`).
- **Where:** `src/querydoc/**`, `app/`, `benchmarks/`.
- **Limitations:** per-process model copies make multi-process serving memory-hungry; pure-Python hot loops (BM25 scoring, dedup) are slower than native equivalents.
- **Revisit:** if serving moves behind a high-QPS API, keep Python for the model workers and front them with a gateway.

## PyMuPDF (`pymupdf`)
- **What:** Python bindings to MuPDF, a C PDF renderer/parser.
- **Why:** text extraction with layout information, encryption detection (`doc.needs_pass`), image detection (scanned-page heuristic), page rendering to PNG (citation viewer) and an optional Tesseract OCR bridge.
- **How it works:** MuPDF parses the PDF object graph, interprets page content streams, and groups glyphs into spans → lines → blocks with direction vectors.
- **Where:** `src/querydoc/ingestion/pdf_loader.py` (`extract_pdf`, `_horizontal_text`, `_ocr_page`), `app/components/viewer.py` (`render_page`), `src/querydoc/evaluation/synthetic.py` (test PDF generation).
- **Key decision:** extraction uses `get_text("dict")` and keeps only lines whose direction is horizontal. NIST PDFs have a rotated sidebar ("This publication is available free of charge…") that plain `get_text("text")` interleaved into body sentences (e.g. "The sessionpublication SHALL…"). See `docs/TROUBLESHOOTING.md`.
- **Alternatives:** *pypdf* (pure Python, slower, weaker layout), *pdfplumber/pdfminer* (good tables, ~10× slower), *Unstructured/Docling* (heavier, model-based layout; better for tables/figures).
- **Limitations:** multi-column reading order is heuristic (`sort=True`); tables become plain text; scanned pages need OCR. **License:** AGPL-3.0 (or commercial) — relevant if the project is distributed as a closed-source service.
- **Revisit:** documents dominated by tables/forms, or when AGPL is unacceptable.

## LangChain (`langchain-core`, `langchain-text-splitters`)
- **What:** abstractions for LLM applications. Only the two light packages are used — no `langchain` umbrella, no community integrations.
- **Concrete value here:**
  1. `RecursiveCharacterTextSplitter` with `add_start_index=True` — the start offsets are what makes page-range metadata exact (`src/querydoc/chunking/chunkers.py::_recursive_spans`).
  2. `Document` as the interchange format (`Chunk.to_document`).
  3. `ChatPromptTemplate` to build role-tagged messages that are then rendered with the model's own chat template (`src/querydoc/generation/prompts.py`).
- **Deliberately not used:** LangChain's FAISS vector store (it persists metadata with **pickle** — `allow_dangerous_deserialization` — which conflicts with the "never load untrusted pickle" requirement), LangChain HF pipelines and chains (the custom service gives explicit control over timeouts, admission control and citation verification).
- **Alternatives:** LlamaIndex (more opinionated indexing), Haystack, plain Python.
- **Revisit:** if agentic tool use or many provider integrations become necessary.

## SentenceTransformers + all-MiniLM-L6-v2
- **What:** a library for bi-encoder embedding models; MiniLM-L6 is a 6-layer, 384-dimensional distilled model trained contrastively on >1 B sentence pairs.
- **How it works:** tokenise (WordPiece, max 256 tokens — longer inputs are truncated) → transformer → mean pooling → L2 normalisation (we request `normalize_embeddings=True`) so inner product == cosine similarity.
- **Where:** `src/querydoc/embeddings/embedder.py::Embedder` (batched encode into a preallocated matrix, duplicate skipping, `.npz` cache loaded with `allow_pickle=False`); reranker via `CrossEncoder` in `retrieval/retriever.py::Reranker`.
- **Why chosen:** CPU-friendly (hundreds of chunks/s on an M3 Pro), small download, permissive license, widely used baseline → results are comparable to other work.
- **Limitations:** 256-token truncation means chunks above ~1,000 characters are partially ignored by the embedding; English-centric; weaker than newer bge/e5/gte models on BEIR.
- **Revisit:** first upgrade to try is `BAAI/bge-small-en-v1.5` (same dimension, better retrieval) — the persisted index records the model name and refuses to load with a different one, forcing a rebuild.

## FAISS (`faiss-cpu`)
- **What:** Meta's C++ library for similarity search over dense vectors.
- **How it works here:** `IndexFlatIP` stores raw float32 vectors and computes exact inner products (SIMD); wrapped in `IndexIDMap2` so we control 64-bit IDs (stable across deletes) and can `remove_ids`. Document filtering uses `SearchParameters(sel=IDSelectorBatch(ids))` so the filter is applied inside the search, not after it. `IndexHNSWFlat` is available (`QUERYDOC_INDEX_TYPE=hnsw`) — a navigable small-world graph giving sub-linear approximate search; it cannot remove IDs, so deletion rebuilds from stored vectors.
- **Where:** `src/querydoc/vectorstore/faiss_store.py`.
- **Persistence:** `faiss.write_index` (FAISS's own binary format — not pickle) + `chunks.jsonl` + `manifest.json` with model name, dimension, counts and SHA-256 of both files. Saves are atomic (temp dir + `os.replace`); loads verify checksums, model and dimension (`IndexCompatibilityError`).
- **Why not…**

| Option | Strength | Why not here |
|---|---|---|
| Chroma | Batteries-included local DB with metadata filters | Extra service/SQLite layer; less control over index type; not needed at a few thousand vectors |
| Pinecone | Managed, scalable, filters | Paid, network dependency — violates "local-first, no mandatory API key" |
| pgvector | Vectors next to relational data, SQL filters, ACID | Requires PostgreSQL; ideal once there are users/ACLs, overkill for a single-user local app |
| Qdrant/Milvus/Weaviate | Distributed, filtering, replication | Operational overhead with no benefit at this scale |

- **Exact vs approximate:** at ≤ 10 k vectors × 384-d, a flat scan costs ~4 MB of memory traffic per query and measured < 1 ms (`results/retrieval_latency → stage_mean_ms.vector_search`); HNSW adds ~`M·2·4` bytes/vector of graph and recall < 100%. Flat is the right default until ~10⁵–10⁶ vectors.
- **Limitations:** no native metadata store (we keep metadata in Python dicts + JSONL), single-process, filtering builds an ID array per query (O(#chunks)).
- **Revisit:** > 1 M vectors, many concurrent writers, or per-user ACL filtering → pgvector or Qdrant.

## rank-bm25
- **What:** a pure-Python Okapi BM25 implementation.
- **Why:** exact-term matching complements dense retrieval for identifiers, numbers and domain terms ("AAL3", "FIPS 140", "task C-3"). Fused with dense results by Reciprocal Rank Fusion (`score = Σ 1/(60 + rank)`), which needs no score calibration.
- **Where:** `retrieval/retriever.py::BM25Index` — rebuilt lazily when the store's `version` changes.
- **Limitations:** scores every document per query (O(N)); fine for thousands of chunks, not for millions.

## Hugging Face Transformers + Qwen2.5-0.5B-Instruct
- **What:** Transformers loads and runs open-weight models; Qwen2.5-0.5B-Instruct is a 494 M-parameter instruction-tuned decoder with a 32 k context window, Apache-2.0 license, ungated download.
- **Where:** `src/querydoc/generation/llm.py::LocalLLM` — loaded **once** (cached by the service and by `st.cache_resource`), `float16` on MPS/CUDA and `float32` on CPU, greedy decoding by default, `TextIteratorStreamer` for time-to-first-token, a lock serialising `generate()` (one model instance is not safe for concurrent generation), out-of-memory errors mapped to `GenerationError`, load failures mapped to `GenerationUnavailableError` → retrieval-only mode.
- **Model choice:** 0.5B and 1.5B were both evaluated (`results/generation`). See `docs/PERFORMANCE_REPORT.md` for the measured quality/latency trade-off that decided the default.
- **Alternatives:** Llama-3.2-1B/3B (gated, Llama community license), Phi-3.5-mini (3.8 B, slower), llama.cpp/Ollama with GGUF int4 (faster CPU inference, separate runtime), vLLM (GPU servers only).
- **Revisit:** for production answer quality use ≥ 3 B parameters with 4-bit quantisation (llama.cpp/MLX) or a GPU server.

## PyTorch
- **What:** tensor runtime used by both model libraries.
- **Device policy:** embeddings and reranker default to CPU (deterministic, thread-safe, and fast enough at 22 M params); the LLM defaults to `auto` → CUDA, then Apple MPS, then CPU (`config.resolve_device`).
- **macOS caveat:** PyTorch and FAISS wheels each bundle `libomp`. Loading both with multi-threaded OpenMP segfaults (FAISS first) or deadlocks (torch first). `querydoc/__init__.py` sets `OMP_NUM_THREADS=1` before either loads; `Embedder` then raises torch's intra-op pool with `torch.set_num_threads(4)`; `faiss_store.py` imports torch before faiss. Measured effect: 52 → 102 chunks/s versus leaving torch single-threaded.

## Streamlit
- **What:** Python-only reactive web UI framework; the script re-runs top-to-bottom on every interaction.
- **Key pattern:** `@st.cache_resource` holds one `QueryDocService` (embedding model, reranker, FAISS index, LLM) per server process, so reruns never reload models. Per-user state (chat history, selected citation) lives in `st.session_state`.
- **Where:** `app/main.py`, `app/components/viewer.py`.
- **Alternatives:** FastAPI + React (production-grade, more work), Gradio (similar speed, less layout control), Chainlit (chat-only).
- **Limitations:** no authentication, all sessions share one process and one index, long generations block that session's script run.

## NumPy / Pandas
- NumPy: float32 embedding matrices, MMR maths, cache files (`np.savez` / `np.load(allow_pickle=False)`).
- Pandas: tabular display in the Streamlit Source Explorer and Performance tabs.

## pytest / Ruff / mypy / GitHub Actions
- pytest with markers `slow` and `llm`; the LLM end-to-end tests skip automatically if the model is not cached (CI sets `QUERYDOC_SKIP_LLM=1`).
- Ruff for lint + import order, mypy over `src/querydoc`.
- `.github/workflows/ci.yml` installs the CPU PyTorch wheel, caches HF models and runs `pytest -m "not llm"`.

## psutil
- Process RSS for memory measurements (benchmarks and the Performance tab). RSS includes native allocations from PyTorch/FAISS, which `tracemalloc` cannot see. Sampling at 5 ms is a lower bound on the true peak.
