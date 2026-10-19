"""Batched SentenceTransformer embeddings with a content-addressed cache."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from querydoc.config import resolve_device
from querydoc.logging_utils import get_logger, kv

log = get_logger(__name__)

ProgressCallback = Callable[[int, int], None]


def configure_torch_threads(n: int) -> None:
    """Set torch's intra-op thread count (see the OpenMP note in querydoc/__init__.py)."""
    import torch

    if n > 0 and torch.get_num_threads() != n:
        torch.set_num_threads(n)


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Maps sha256(text) -> normalised float32 vector for one embedding model.

    Persisted as a ``.npz`` of a fixed-width byte-string key array and a float32
    matrix, loaded with ``allow_pickle=False`` so no code can be executed on load.
    """

    def __init__(self, path: Path | None, model_name: str, dim: int) -> None:
        self.path = path
        self.model_name = model_name
        self.dim = dim
        self._store: dict[str, np.ndarray] = {}
        self._dirty = False
        self._lock = threading.Lock()
        if path and path.exists():
            self._load(path)

    def _load(self, path: Path) -> None:
        try:
            with np.load(path, allow_pickle=False) as data:
                model = str(data["model"])
                keys = data["keys"]
                vectors = data["vectors"]
            if model != self.model_name or vectors.ndim != 2 or vectors.shape[1] != self.dim:
                log.warning(kv("embedding_cache_incompatible", path=path))
                return
            for k, v in zip(keys, vectors, strict=True):
                self._store[k.decode("ascii")] = v
        except Exception as exc:  # corrupt cache is not fatal; it is rebuilt
            log.warning(kv("embedding_cache_unreadable", path=path, error=exc))

    def get(self, key: str) -> np.ndarray | None:
        return self._store.get(key)

    def put_many(self, keys: Sequence[str], vectors: np.ndarray) -> None:
        with self._lock:
            for k, v in zip(keys, vectors, strict=True):
                self._store[k] = v
            self._dirty = True

    def __len__(self) -> int:
        return len(self._store)

    def save(self) -> None:
        if not self.path or not self._dirty:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            keys = np.array([k.encode("ascii") for k in self._store], dtype="S64")
            vectors = (
                np.stack(list(self._store.values())).astype(np.float32)
                if self._store
                else np.zeros((0, self.dim), dtype=np.float32)
            )
            tmp = self.path.with_suffix(".tmp.npz")
            np.savez(tmp, model=np.array(self.model_name), keys=keys, vectors=vectors)
            tmp.replace(self.path)
            self._dirty = False


@dataclass
class EmbeddingStats:
    texts: int = 0
    unique_texts: int = 0
    cache_hits: int = 0
    encoded: int = 0
    seconds: float = 0.0
    batch_size: int = 0
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.unique_texts if self.unique_texts else 0.0

    @property
    def chunks_per_second(self) -> float:
        return self.encoded / self.seconds if self.seconds > 0 else 0.0


class Embedder:
    """Thin, thread-safe wrapper around a SentenceTransformer model."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        batch_size: int = 32,
        cache_dir: Path | None = None,
        torch_threads: int = 4,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        configure_torch_threads(torch_threads)
        self.model_name = model_name
        self.device = resolve_device(device)
        self.batch_size = batch_size
        started = time.perf_counter()
        self.model = SentenceTransformer(model_name, device=self.device)
        self.dim = int(self.model.get_embedding_dimension())
        self.max_seq_length = int(self.model.max_seq_length)
        self.load_seconds = time.perf_counter() - started
        # HF fast tokenizers are not safe to call from several threads at once.
        self._lock = threading.Lock()
        cache_path = None
        if cache_dir is not None:
            safe = model_name.replace("/", "__")
            cache_path = cache_dir / f"{safe}.npz"
        self.cache = EmbeddingCache(cache_path, model_name, self.dim)
        log.info(kv("embedder_loaded", model=model_name, device=self.device, dim=self.dim))

    def _encode(self, texts: Sequence[str], batch_size: int) -> np.ndarray:
        with self._lock:
            out = self.model.encode(
                list(texts),
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return np.asarray(out, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([text], 1)[0]

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        use_cache: bool = True,
        progress: ProgressCallback | None = None,
        stats: EmbeddingStats | None = None,
    ) -> np.ndarray:
        """Embed ``texts`` into a preallocated ``(n, dim)`` float32 matrix.

        Identical texts are encoded once; cached vectors are reused. Each batch
        is written straight into the output matrix so no per-batch arrays or
        tensors are retained.
        """
        bs = batch_size or self.batch_size
        started = time.perf_counter()
        n = len(texts)
        out = np.empty((n, self.dim), dtype=np.float32)
        keys = [text_key(t) for t in texts]

        first_index: dict[str, int] = {}
        todo: list[int] = []  # indices of unique texts that need encoding
        hits = 0
        for i, k in enumerate(keys):
            if k in first_index:
                continue
            first_index[k] = i
            cached = self.cache.get(k) if use_cache else None
            if cached is not None:
                out[i] = cached
                hits += 1
            else:
                todo.append(i)

        for b in range(0, len(todo), bs):
            batch_idx = todo[b : b + bs]
            vecs = self._encode([texts[i] for i in batch_idx], bs)
            out[batch_idx] = vecs
            if use_cache:
                self.cache.put_many([keys[i] for i in batch_idx], vecs)
            if progress:
                progress(min(b + bs, len(todo)), len(todo))

        for i, k in enumerate(keys):  # fill duplicates from their first occurrence
            j = first_index[k]
            if j != i:
                out[i] = out[j]

        if stats is not None:
            stats.texts += n
            stats.unique_texts += len(first_index)
            stats.cache_hits += hits
            stats.encoded += len(todo)
            stats.seconds += time.perf_counter() - started
            stats.batch_size = bs
        return out
