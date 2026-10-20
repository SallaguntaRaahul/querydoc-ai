"""Retrieval pipeline: dense FAISS search with optional BM25 hybrid fusion,
duplicate-context removal, MMR diversification and cross-encoder reranking."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from querydoc.chunking.chunkers import Chunk
from querydoc.config import load_local_first, resolve_device
from querydoc.devices import device_lock
from querydoc.embeddings.embedder import Embedder
from querydoc.ingestion.text_cleaning import clean_text
from querydoc.logging_utils import get_logger, kv
from querydoc.vectorstore.faiss_store import FaissVectorStore

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has", "have", "how", "i", "in", "is", "it", "its", "of", "on", "or", "should", "that", "the", "this", "to", "was", "what", "when", "where", "which", "who", "why", "will", "with"]
)
RRF_K = 60


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 5
    fetch_k: int = 30
    use_hybrid: bool = False
    use_mmr: bool = False
    mmr_lambda: float = 0.7
    use_rerank: bool = False
    rerank_k: int | None = None  # rerank only the best N candidates (None = all)
    dedup: bool = True
    preprocess_query: bool = True
    doc_ids: tuple[str, ...] | None = None


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float  # score used for the final ordering
    rank: int
    vector_id: int = -1
    dense_score: float | None = None
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    query: str
    chunks: list[RetrievedChunk]
    timings_ms: dict[str, float]
    max_dense_score: float

    @property
    def latency_ms(self) -> float:
        return self.timings_ms.get("total", 0.0)


class BM25Index:
    """Lazily (re)built Okapi BM25 over all chunks in a vector store."""

    def __init__(self, store: FaissVectorStore) -> None:
        self.store = store
        self._version = -1
        self._ids: list[int] = []
        self._bm25 = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._version == self.store.version:
            return
        with self._lock:
            if self._version == self.store.version:
                return
            from rank_bm25 import BM25Okapi

            items = self.store.all_chunks()
            self._ids = [vid for vid, _ in items]
            corpus = [tokenize(c.text) or ["_"] for _, c in items]
            self._bm25 = BM25Okapi(corpus) if corpus else None
            self._version = self.store.version

    def search(self, query: str, k: int, doc_ids: set[str] | None = None) -> list[tuple[int, float]]:
        self._ensure()
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            vid = self._ids[i]
            chunk = self.store.chunks.get(vid)
            if chunk is None or (doc_ids is not None and chunk.doc_id not in doc_ids):
                continue
            out.append((vid, float(scores[i])))
            if len(out) >= k:
                break
        return out


class Reranker:
    def __init__(self, model_name: str, device: str = "cpu", max_length: int | None = None) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.device = resolve_device(device)
        self.model = load_local_first(lambda **kw: CrossEncoder(model_name, device=self.device, **kw), model_name)
        if max_length is not None:
            self.model.max_length = max_length
        self._lock = threading.Lock()

    def score(self, query: str, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros(0, dtype=np.float32)
        with self._lock, device_lock(self.device):
            out = self.model.predict([(query, t) for t in texts], batch_size=32, show_progress_bar=False)
        return np.asarray(out, dtype=np.float32)


def _overlap_ratio(a: Chunk, b: Chunk) -> float:
    if a.doc_id != b.doc_id:
        return 0.0
    a_end, b_end = a.char_start + len(a.text), b.char_start + len(b.text)
    inter = min(a_end, b_end) - max(a.char_start, b.char_start)
    if inter <= 0:
        return 0.0
    return inter / min(len(a.text), len(b.text))


def _jaccard(sa: set[str], sb: set[str]) -> float:
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def deduplicate(cands: list[RetrievedChunk], threshold: float = 0.6) -> list[RetrievedChunk]:
    """Drop lower-ranked candidates that mostly repeat an already-kept one (same
    character range via chunk overlap, or near-identical wording elsewhere)."""
    kept: list[tuple[RetrievedChunk, set[str]]] = []
    for cand in cands:
        toks = set(tokenize(cand.chunk.text))
        if any(
            _overlap_ratio(cand.chunk, k.chunk) >= threshold or _jaccard(toks, kt) >= 0.9 for k, kt in kept
        ):
            continue
        kept.append((cand, toks))
    return [k for k, _ in kept]


def mmr_select(query_vec: np.ndarray, vectors: np.ndarray, k: int, lam: float) -> list[int]:
    """Maximal Marginal Relevance over normalised vectors; returns row indices."""
    if len(vectors) == 0:
        return []
    rel = vectors @ query_vec
    selected: list[int] = [int(np.argmax(rel))]
    remaining = set(range(len(vectors))) - set(selected)
    while remaining and len(selected) < k:
        rem = np.array(sorted(remaining))
        redundancy = (vectors[rem] @ vectors[selected].T).max(axis=1)
        mmr = lam * rel[rem] - (1 - lam) * redundancy
        best = int(rem[int(np.argmax(mmr))])
        selected.append(best)
        remaining.discard(best)
    return selected


class Retriever:
    def __init__(
        self,
        store: FaissVectorStore,
        embedder: Embedder,
        reranker: Reranker | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.reranker = reranker
        self.bm25 = BM25Index(store)

    def retrieve(self, query: str, cfg: RetrievalConfig | None = None) -> RetrievalResult:
        cfg = cfg or RetrievalConfig()
        t0 = time.perf_counter()
        timings: dict[str, float] = {}
        q = clean_text(query) if cfg.preprocess_query else query
        allowed = set(cfg.doc_ids) if cfg.doc_ids is not None else None
        fetch_k = max(cfg.fetch_k, cfg.top_k)

        t = time.perf_counter()
        qvec = self.embedder.embed_query(q)
        timings["embed_query"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        dense_k = fetch_k if (cfg.use_hybrid or cfg.use_rerank or cfg.use_mmr or cfg.dedup) else cfg.top_k
        hits = self.store.search(qvec, dense_k, doc_ids=allowed)
        timings["vector_search"] = (time.perf_counter() - t) * 1000
        max_dense = max((h.score for h in hits), default=0.0)

        cands: dict[int, RetrievedChunk] = {
            h.vector_id: RetrievedChunk(h.chunk, h.score, 0, h.vector_id, dense_score=h.score, scores={"dense": h.score})
            for h in hits
        }
        order = [h.vector_id for h in hits]

        if cfg.use_hybrid:
            t = time.perf_counter()
            lexical = self.bm25.search(q, fetch_k, allowed)
            fused: dict[int, float] = {}
            for rank, vid in enumerate(order):
                fused[vid] = fused.get(vid, 0.0) + 1.0 / (RRF_K + rank + 1)
            for rank, (vid, s) in enumerate(lexical):
                fused[vid] = fused.get(vid, 0.0) + 1.0 / (RRF_K + rank + 1)
                if vid not in cands:
                    chunk = self.store.chunks.get(vid)
                    if chunk is None:
                        continue
                    cands[vid] = RetrievedChunk(chunk, 0.0, 0, vid)
                cands[vid].scores["bm25"] = s
            for vid, s in fused.items():
                if vid in cands:
                    cands[vid].scores["rrf"] = s
                    cands[vid].score = s
            order = sorted((v for v in fused if v in cands), key=lambda v: -fused[v])
            timings["bm25_fusion"] = (time.perf_counter() - t) * 1000

        ranked = [cands[v] for v in order]

        if cfg.dedup:
            t = time.perf_counter()
            ranked = deduplicate(ranked)
            timings["dedup"] = (time.perf_counter() - t) * 1000

        if cfg.use_mmr and ranked:
            t = time.perf_counter()
            vids = [r.vector_id for r in ranked]
            vecs = self.store.get_vectors(vids)
            keep = max(cfg.top_k * 2, cfg.top_k) if cfg.use_rerank else cfg.top_k
            picked = mmr_select(qvec, vecs, keep, cfg.mmr_lambda)
            ranked = [ranked[i] for i in picked]
            timings["mmr"] = (time.perf_counter() - t) * 1000

        if cfg.use_rerank and self.reranker is not None and ranked:
            t = time.perf_counter()
            if cfg.rerank_k is not None:
                ranked = ranked[: max(cfg.rerank_k, cfg.top_k)]
            scores = self.reranker.score(q, [r.chunk.text for r in ranked])
            for r, s in zip(ranked, scores.tolist(), strict=True):
                r.scores["rerank"] = s
                r.score = s
            ranked.sort(key=lambda r: -r.score)
            timings["rerank"] = (time.perf_counter() - t) * 1000

        final = ranked[: cfg.top_k]
        for i, r in enumerate(final):
            r.rank = i + 1
        timings["total"] = (time.perf_counter() - t0) * 1000
        log.debug(kv("retrieve", k=cfg.top_k, results=len(final), ms=timings["total"]))
        return RetrievalResult(query=q, chunks=final, timings_ms=timings, max_dense_score=max_dense)
