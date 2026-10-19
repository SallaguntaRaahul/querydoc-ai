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
| Generation | HF Transformers + `Qwen/Qwen2.5-1.5B-Instruct` (Apache-2.0; 0.5B as low-memory option) | Qwen2.5-3B, Llama-3.2-1B/3B (gated license), Phi-3.5-mini, llama.cpp/GGUF, Ollama, vLLM | Ungated, permissive license, measured 84% vs 48% answer accuracy over 0.5B at p50 1.9 s on MPS | Answer quality matters more than latency, or a GPU server is available (vLLM) |
| Tensor runtime | PyTorch 2.x (CPU + Apple MPS) | ONNX Runtime, MLX, llama.cpp | Required by Transformers and SentenceTransformers; MPS gives free GPU on Apple silicon | Need int4/int8 quantized CPU inference (llama.cpp / ONNX) |
| UI | React 19 + TypeScript + Vite + Tailwind v4 + shadcn/ui (Radix) | Streamlit (phase 1), Next.js, Vue/Svelte, Gradio | Full control of a three-panel streaming chat, PDF viewer and dashboard; typed API contract; accessible primitives | Server rendering or SEO become requirements (Next.js) |
| API | FastAPI + Pydantic + Uvicorn, SSE | Flask, Django REST, Litestar, WebSockets | Async I/O for streaming, Pydantic validation shared with OpenAPI, same language as the engine | Many concurrent users or multi-node deployment (add a gateway/queue) |
| App database | SQLite + SQLAlchemy 2 + Alembic | PostgreSQL, TinyDB/JSON files | Zero-ops, transactional, migratable; WAL handles one writer + many readers | Multiple users or processes → PostgreSQL |
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

## Hugging Face Transformers + Qwen2.5-1.5B-Instruct
- **What:** Transformers loads and runs open-weight models; Qwen2.5-1.5B-Instruct is a 1.5 B-parameter instruction-tuned decoder (32 k context), Apache-2.0, ungated; ~3 GB in fp16. Qwen2.5-0.5B-Instruct (494 M, ~1 GB) is supported as a low-memory option via `QUERYDOC_LLM_MODEL`.
- **Where:** `src/querydoc/generation/llm.py::LocalLLM` — loaded **once** (cached by the service and by `st.cache_resource`), `float16` on MPS/CUDA and `float32` on CPU, greedy decoding by default, `TextIteratorStreamer` for time-to-first-token, a lock serialising `generate()` (one model instance is not safe for concurrent generation), out-of-memory errors mapped to `GenerationError`, load failures mapped to `GenerationUnavailableError` → retrieval-only mode.
- **Model choice (measured, `results/generation`):** on 31 held-out questions 1.5B reached 84% keyword accuracy vs 48% for 0.5B and tagged its own citations 65% vs 6% of the time, at p50 1.9 s vs 0.5 s end to end. 0.5B often answered with a bare `[S2]`. Quality won; 0.5B remains available.
- **Loading:** local-first (`config.load_local_first`): `local_files_only=True` first, network only if the model is not cached.
- **Alternatives:** Llama-3.2-1B/3B (gated, Llama community license), Phi-3.5-mini (3.8 B, slower), llama.cpp/Ollama with GGUF int4 (faster CPU inference, separate runtime), vLLM (GPU servers only).
- **Revisit:** for production answer quality use ≥ 3 B parameters with 4-bit quantisation (llama.cpp/MLX) or a GPU server.

## PyTorch
- **What:** tensor runtime used by both model libraries.
- **Device policy:** embeddings and reranker default to CPU (deterministic, thread-safe, and fast enough at 22 M params); the LLM defaults to `auto` → CUDA, then Apple MPS, then CPU (`config.resolve_device`).
- **macOS caveat:** PyTorch and FAISS wheels each bundle `libomp`. Loading both with multi-threaded OpenMP segfaults (FAISS first) or deadlocks (torch first). `querydoc/__init__.py` sets `OMP_NUM_THREADS=1` before either loads; `Embedder` then raises torch's intra-op pool with `torch.set_num_threads(4)`; `faiss_store.py` imports torch before faiss. Measured effect: 52 → 102 chunks/s versus leaving torch single-threaded.

## Streamlit (phase 1 — replaced)
- **Status:** used for the first version; replaced by React + FastAPI in the full-stack upgrade. Kept here as a documented decision.
- **Why it was replaced:** a script-rerun model makes token streaming, a persistent three-panel layout, a real PDF viewer, background ingestion with progress and a documented REST contract awkward; all sessions shared one process; styling options were limited.
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


---

# Full-stack upgrade: frontend and API decisions

## React 19 + TypeScript
- **Why:** the product is interaction-heavy (streaming tokens, resizable panels, PDF canvas, charts, forms). React's component model and ecosystem (Radix, TanStack, react-pdf, Recharts) cover all of it; TypeScript catches contract drift between `backend/app/schemas/api.py` and `frontend/src/types/api.ts` at build time.
- **Where:** `frontend/src/**` (pages, components, features, hooks).
- **Alternatives:** Vue/Svelte (equally capable, smaller ecosystem for PDF/a11y primitives), Next.js (server rendering not needed for a local app and would add a Node server at runtime).
- **Trade-off:** more code than Streamlit; requires Node for builds (not at runtime in production mode).

## Vite
- Dev server with HMR and an `/api` proxy (no CORS in development), Rollup-based production build with code splitting (PDF.js and Recharts load only on their pages). Chosen over webpack/CRA for speed and simplicity.

## Tailwind CSS v4 + shadcn/ui + Radix UI
- **Tailwind:** utility classes over design tokens defined once as CSS variables (`src/index.css`): OKLCH graphite neutrals, an indigo-violet accent, status and chart colours, dark/light pairs. Keeps spacing/typography consistent without a bespoke CSS architecture.
- **shadcn/ui:** components are copied into the repo (`src/components/ui`) rather than installed, so they can be adjusted (e.g. clearer selected-toggle state, ScrollArea replaced where it broke text wrapping).
- **Radix:** accessible primitives (focus management, keyboard support, ARIA) for dialogs, menus, popovers, selects, tabs, tooltips.
- **Alternatives:** MUI/Chakra (heavier, harder to give a distinctive look), plain CSS modules (more work for the same consistency).

## TanStack Query
- Server-state cache: request de-duplication, background refetch, **conditional polling** (documents poll every 0.8 s only while something is processing), optimistic delete, cache writes from the SSE `done` event. Avoids a hand-written global store. Alternative: Redux Toolkit Query / SWR — similar; TanStack's polling and mutation APIs fit best.

## React Router
- URL-addressable state (`/chat/:conversationId`, `/documents/:id?page=12`) so conversations and cited pages can be reopened, bookmarked and reloaded.

## react-pdf (PDF.js)
- Renders pages to canvas with a selectable text layer, in a Web Worker. The text layer is what makes honest citation highlighting possible: only spans whose text is part of the verified passage are marked. Alternative: native browser viewer in an `<iframe>` (no control over navigation/highlighting), PDF.js directly (more boilerplate).
- Requires Node ≥ 22.13 for tooling (pinned in `frontend/.nvmrc`).

## Recharts
- Declarative SVG charts for latency, quality, memory and concurrency. Colours come from the validated palette tokens; one y-axis per chart; animation disabled so every frame shows exact data.

## Zod + React Hook Form
- One schema (`features/settings/schema.ts`) mirrors the backend's validation (`SettingsModel`), giving instant client-side errors; the server re-validates and its field errors are mapped back onto the form.

## Motion for React
- Small entrance transitions only; wrapped in `MotionConfig reducedMotion="user"` and overridden by a global `prefers-reduced-motion` rule.

## FastAPI + Pydantic + Uvicorn
- **Why:** async request handling for long-lived SSE streams; Pydantic models are both validators and the OpenAPI schema (`/api/docs`); Python, so the RAG engine is imported directly with no RPC layer.
- **Where:** `backend/app/main.py` (factory, lifespan, middleware, SPA serving), `app/api/v1/*`, `app/schemas/api.py`.
- **Alternatives:** Flask (sync by default; streaming possible but clunkier), Django REST (heavier ORM/admin not needed), Node backend (would need a Python sidecar for models).

## Server-Sent Events (vs WebSockets / polling)
- Answers stream one way (server → client) over plain HTTP; SSE gives event types, works through the Vite proxy, and needs no extra protocol. The browser `EventSource` cannot POST, so the client reads the `fetch` body stream directly (`lib/sse.ts`). Disconnect is the cancellation signal. WebSockets would add bidirectional framing the product does not need.

## SQLite + SQLAlchemy 2 + Alembic
- Application state (documents' lifecycle, conversations, messages with citations, settings, telemetry) is relational and transactional; SQLite needs no server, WAL mode lets the ingestion thread write while requests read, Alembic versions the schema and runs on startup. The FAISS index and chunk metadata stay in the engine's checksummed files.

## Background processing: thread pool (vs Celery/RQ)
- A bounded `ThreadPoolExecutor` inside the API process is enough for one user and avoids running Redis/Celery. Progress is persisted, interrupted jobs are re-queued on restart. Revisit for multi-user/multi-node deployments.

## Testing stack
- **pytest + HTTPX TestClient** — API contract, SSE event order, cancellation, concurrency limits, security boundaries (real ingestion/FAISS/DB; deterministic stub LLM).
- **Vitest + React Testing Library + vitest-axe** — components, form validation, API interactions with mocked `fetch`, theme, accessibility.
- **Playwright** — real browser against a freshly started real stack (real models), plus visual QA screenshots at three viewports in both themes.
