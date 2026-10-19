"""QueryDocService: the single entry point used by the UI, tests and benchmarks.

It owns the long-lived resources (embedding model, reranker, FAISS store, local
LLM) and composes ingestion, retrieval, generation and citation verification.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psutil

from querydoc.chunking.chunkers import ChunkingConfig, chunk_document
from querydoc.citations.citations import (
    STATUS_INSUFFICIENT,
    CitationReport,
    verify_answer,
)
from querydoc.config import Settings, get_settings
from querydoc.embeddings.embedder import Embedder, EmbeddingStats
from querydoc.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    GenerationUnavailableError,
    IndexCompatibilityError,
    QueryDocError,
)
from querydoc.generation.llm import GenerationParams, GenerationResult, LocalLLM
from querydoc.generation.prompts import INSUFFICIENT_MESSAGE, build_prompt
from querydoc.ingestion.pdf_loader import content_hash, doc_id_from_hash, extract_pdf
from querydoc.logging_utils import get_logger, kv
from querydoc.retrieval.retriever import Reranker, RetrievalConfig, RetrievalResult, Retriever
from querydoc.services.concurrency import GenerationGate
from querydoc.services.registry import DocumentRecord, DocumentRegistry
from querydoc.vectorstore.faiss_store import FaissVectorStore

log = get_logger(__name__)
ProgressCallback = Callable[[str, float], None]


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


@dataclass
class IngestReport:
    record: DocumentRecord
    timings_ms: dict[str, float]
    embedding: dict[str, float]
    rss_mb_after: float


@dataclass
class RAGResponse:
    question: str
    answer: str
    status: str
    mode: str  # "generated" | "retrieval_only" | "insufficient_evidence"
    citations: CitationReport | None
    retrieval: RetrievalResult
    generation: GenerationResult | None
    timings_ms: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class QueryDocService:
    def __init__(self, settings: Settings | None = None, *, embedder: Embedder | None = None) -> None:
        self.settings = settings or get_settings()
        s = self.settings
        s.data_dir.mkdir(parents=True, exist_ok=True)
        s.documents_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or Embedder(
            s.embedding_model,
            device=s.embedding_device,
            batch_size=s.embedding_batch_size,
            cache_dir=s.embedding_cache_dir,
            torch_threads=s.torch_threads,
        )
        self.registry = DocumentRegistry(s.data_dir / "documents.json")
        self.store = self._load_or_create_store()
        self._reranker: Reranker | None = None
        self._reranker_lock = threading.Lock()
        self._llm: LocalLLM | None = None
        self._llm_error: str | None = None
        self._llm_lock = threading.Lock()
        self._ingest_lock = threading.Lock()
        self.gate = GenerationGate(s.max_active_generations, s.max_generation_queue, s.generation_timeout_s)
        self.retriever = Retriever(self.store, self.embedder, None)

    # ------------------------------------------------------------ resources
    def _load_or_create_store(self) -> FaissVectorStore:
        s = self.settings
        if (s.index_dir / "manifest.json").exists():
            try:
                store = FaissVectorStore.load(
                    s.index_dir,
                    model_name=s.embedding_model,
                    dim=self.embedder.dim,
                    hnsw_ef_search=s.hnsw_ef_search,
                )
                missing = {d.doc_id for d in self.registry.all()} - store.doc_ids()
                if missing:
                    log.warning(kv("registry_index_mismatch", missing=len(missing)))
                return store
            except IndexCompatibilityError as exc:
                log.error(kv("index_rejected", reason=exc))
                raise
        return FaissVectorStore(
            self.embedder.dim,
            s.embedding_model,
            index_type=s.index_type,
            hnsw_m=s.hnsw_m,
            hnsw_ef_search=s.hnsw_ef_search,
        )

    def reranker(self) -> Reranker:
        with self._reranker_lock:
            if self._reranker is None:
                self._reranker = Reranker(self.settings.reranker_model, device="cpu")
                self.retriever.reranker = self._reranker
        return self._reranker

    def llm(self) -> LocalLLM:
        """Load the generation model once. Failures are remembered and surface
        as GenerationUnavailableError so callers can fall back to retrieval."""
        with self._llm_lock:
            if self._llm is None and self._llm_error is None:
                try:
                    self._llm = LocalLLM(self.settings.llm_model, device=self.settings.llm_device)
                except GenerationUnavailableError as exc:
                    self._llm_error = str(exc)
            if self._llm is None:
                raise GenerationUnavailableError(self._llm_error or "LLM unavailable")
            return self._llm

    @property
    def llm_loaded(self) -> bool:
        return self._llm is not None

    @property
    def llm_error(self) -> str | None:
        return self._llm_error

    # ------------------------------------------------------------ documents
    def chunking_config(self, **overrides: object) -> ChunkingConfig:
        s = self.settings
        base = dict(
            strategy=s.chunk_strategy,
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            min_chunk_chars=s.min_chunk_chars,
        )
        base.update({k: v for k, v in overrides.items() if v is not None})
        return ChunkingConfig(**base)  # type: ignore[arg-type]

    def ingest(
        self,
        data: bytes,
        filename: str,
        *,
        chunking: ChunkingConfig | None = None,
        batch_size: int | None = None,
        progress: ProgressCallback | None = None,
        persist: bool = True,
    ) -> IngestReport:
        s = self.settings
        sha = content_hash(data)
        existing = self.registry.find_by_hash(sha)
        if existing:
            raise DuplicateDocumentError(existing.doc_id, existing.filename)
        cfg = chunking or self.chunking_config()
        timings: dict[str, float] = {}

        t = time.perf_counter()
        doc = extract_pdf(
            data,
            filename,
            max_upload_mb=s.max_upload_mb,
            max_pages=s.max_pages,
            min_chars_per_page=s.min_chars_per_page,
            enable_ocr=s.enable_ocr,
            progress=(lambda i, n: progress("extract", i / n)) if progress else None,
        )
        timings["extract"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        chunks = chunk_document(doc, cfg)
        timings["chunk"] = (time.perf_counter() - t) * 1000
        if not chunks:
            raise QueryDocError(
                f"No extractable text found in '{doc.filename}'"
                + (f" ({len(doc.scanned_pages)} pages look scanned; OCR is disabled)." if doc.scanned_pages else ".")
            )

        stats = EmbeddingStats()
        t = time.perf_counter()
        vectors = self.embedder.embed_texts(
            [c.text for c in chunks],
            batch_size=batch_size,
            stats=stats,
            progress=(lambda i, n: progress("embed", i / max(n, 1))) if progress else None,
        )
        timings["embed"] = (time.perf_counter() - t) * 1000

        with self._ingest_lock:
            if self.registry.find_by_hash(sha):  # lost a race with an identical upload
                raise DuplicateDocumentError(doc.doc_id, doc.filename)
            t = time.perf_counter()
            self.store.add(chunks, vectors)
            timings["index"] = (time.perf_counter() - t) * 1000
            del vectors
            record = DocumentRecord(
                doc_id=doc.doc_id,
                filename=doc.filename,
                title=doc.title,
                sha256=sha,
                page_count=doc.page_count,
                chunk_count=len(chunks),
                size_bytes=len(data),
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                chunking=asdict(cfg) | {"separators": None},
                scanned_pages=doc.scanned_pages,
                empty_pages=doc.empty_pages,
                timings_ms=timings,
            )
            if persist:
                t = time.perf_counter()
                (s.documents_dir / f"{doc.doc_id}.pdf").write_bytes(data)
                self.store.save(s.index_dir)
                self.embedder.cache.save()
                timings["persist"] = (time.perf_counter() - t) * 1000
            self.registry.add(record)
        if progress:
            progress("done", 1.0)
        log.info(kv("ingested", doc=doc.doc_id, pages=doc.page_count, chunks=len(chunks), **timings))
        return IngestReport(
            record=record,
            timings_ms=timings,
            embedding={
                "chunks": stats.texts,
                "encoded": stats.encoded,
                "cache_hit_rate": stats.cache_hit_rate,
                "chunks_per_second": stats.chunks_per_second,
                "batch_size": stats.batch_size,
            },
            rss_mb_after=rss_mb(),
        )

    def delete_document(self, doc_id: str) -> None:
        with self._ingest_lock:
            if self.registry.get(doc_id) is None:
                raise DocumentNotFoundError(f"Unknown document id {doc_id}")
            self.store.delete_document(doc_id)
            self.store.save(self.settings.index_dir)
            self.registry.remove(doc_id)
            pdf = self.document_path(doc_id)
            if pdf.exists():
                pdf.unlink()
        log.info(kv("document_deleted", doc=doc_id))

    def documents(self) -> list[DocumentRecord]:
        return self.registry.all()

    def document_path(self, doc_id: str) -> Path:
        # doc_id is always a hex digest prefix; validate before touching the filesystem.
        if not (len(doc_id) == 16 and all(ch in "0123456789abcdef" for ch in doc_id)):
            raise DocumentNotFoundError(f"Invalid document id {doc_id!r}")
        return self.settings.documents_dir / f"{doc_id}.pdf"

    # --------------------------------------------------------------- query
    def retrieval_config(self, **overrides: object) -> RetrievalConfig:
        s = self.settings
        base: dict[str, object] = dict(
            top_k=s.top_k,
            fetch_k=s.fetch_k,
            use_hybrid=s.use_hybrid,
            use_mmr=s.use_mmr,
            mmr_lambda=s.mmr_lambda,
            use_rerank=s.use_rerank,
        )
        base.update({k: v for k, v in overrides.items() if v is not None})
        if "doc_ids" in base and base["doc_ids"] is not None:
            base["doc_ids"] = tuple(base["doc_ids"])  # type: ignore[arg-type]
        return RetrievalConfig(**base)  # type: ignore[arg-type]

    def retrieve(self, question: str, cfg: RetrievalConfig | None = None) -> RetrievalResult:
        cfg = cfg or self.retrieval_config()
        if cfg.use_rerank:
            self.reranker()
        return self.retriever.retrieve(question, cfg)

    def answer(
        self,
        question: str,
        cfg: RetrievalConfig | None = None,
        params: GenerationParams | None = None,
        *,
        generate: bool = True,
    ) -> RAGResponse:
        s = self.settings
        started = time.perf_counter()
        question = question.strip()
        if not question:
            raise QueryDocError("Please enter a question.")
        if self.store.size == 0:
            raise QueryDocError("No documents are indexed yet. Upload a PDF first.")
        cfg = cfg or self.retrieval_config()
        retrieval = self.retrieve(question, cfg)
        allowed = set(cfg.doc_ids) if cfg.doc_ids is not None else self.store.doc_ids()
        timings = {"retrieval": retrieval.latency_ms}

        def done(resp: RAGResponse) -> RAGResponse:
            resp.timings_ms["total"] = (time.perf_counter() - started) * 1000
            return resp

        if not retrieval.chunks or retrieval.max_dense_score < s.min_relevance_score:
            return done(
                RAGResponse(
                    question,
                    INSUFFICIENT_MESSAGE,
                    STATUS_INSUFFICIENT,
                    "insufficient_evidence",
                    None,
                    retrieval,
                    None,
                    timings,
                    [f"Best passage similarity {retrieval.max_dense_score:.2f} is below the "
                     f"threshold {s.min_relevance_score:.2f}."],
                )
            )

        if not generate:
            return done(RAGResponse(question, "", "retrieval_only", "retrieval_only", None, retrieval, None, timings))
        try:
            llm = self.llm()
        except GenerationUnavailableError as exc:
            return done(
                RAGResponse(
                    question,
                    "",
                    "retrieval_only",
                    "retrieval_only",
                    None,
                    retrieval,
                    None,
                    timings,
                    [f"Generation model unavailable, showing retrieved passages only. ({exc})"],
                )
            )

        params = params or GenerationParams(
            max_new_tokens=s.max_new_tokens, temperature=s.temperature, top_p=s.top_p
        )
        with self.gate.slot() as wait_ms:
            timings["queue_wait"] = wait_ms
            t = time.perf_counter()
            prompt = build_prompt(
                question,
                retrieval.chunks,
                max_context_tokens=s.max_context_tokens,
                count_tokens=llm.count_tokens,
            )
            timings["prompt"] = (time.perf_counter() - t) * 1000
            gen = llm.generate(prompt.messages, params)
        timings["generation"] = gen.latency_ms

        t = time.perf_counter()
        report = verify_answer(
            gen.text, prompt.sources, allowed_doc_ids=allowed, chunk_lookup=self.store.get_chunk
        )
        timings["citation_check"] = (time.perf_counter() - t) * 1000
        if report.status == STATUS_INSUFFICIENT:
            return done(
                RAGResponse(question, INSUFFICIENT_MESSAGE, STATUS_INSUFFICIENT, "insufficient_evidence",
                            report, retrieval, gen, timings, ["The model reported insufficient evidence."])
            )
        return done(
            RAGResponse(question, report.answer, report.status, "generated", report, retrieval, gen, timings,
                        list(report.notes))
        )
