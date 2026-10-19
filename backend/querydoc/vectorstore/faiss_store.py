"""FAISS vector store with JSON metadata, checksummed persistence and a
readers-writer lock so searches can run concurrently with each other but never
against a half-applied write."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# isort: off
# torch must load before faiss on macOS (two bundled libomp copies; see querydoc/__init__.py).
import torch  # noqa: F401
import faiss as _faiss
# isort: on

from querydoc.chunking.chunkers import Chunk
from querydoc.exceptions import IndexCompatibilityError
from querydoc.logging_utils import get_logger, kv

log = get_logger(__name__)
faiss: Any = _faiss  # faiss's generated stubs are inaccurate (e.g. remove_ids, SearchParameters)

MANIFEST_VERSION = 1
INDEX_FILE = "index.faiss"
CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "manifest.json"


class RWLock:
    """Writer-preferring readers-writer lock."""

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._cond:
            while self._writer or self._waiting_writers:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._cond:
            self._waiting_writers += 1
            while self._writer or self._readers:
                self._cond.wait()
            self._waiting_writers -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float  # inner product of normalised vectors == cosine similarity
    vector_id: int


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class FaissVectorStore:
    def __init__(
        self,
        dim: int,
        model_name: str,
        *,
        index_type: str = "flat",
        hnsw_m: int = 32,
        hnsw_ef_search: int = 64,
    ) -> None:
        self.dim = dim
        self.model_name = model_name
        self.index_type = index_type
        self.hnsw_m = hnsw_m
        self.hnsw_ef_search = hnsw_ef_search
        self.index = self._new_index()
        self.chunks: dict[int, Chunk] = {}
        self._by_chunk_id: dict[str, Chunk] = {}
        self._next_id = 0
        self.version = 0  # bumped on every mutation; lets dependants rebuild caches
        self.lock = RWLock()

    # ------------------------------------------------------------------ build
    def _new_index(self) -> faiss.Index:
        if self.index_type == "flat":
            base = faiss.IndexFlatIP(self.dim)
        elif self.index_type == "hnsw":
            base = faiss.IndexHNSWFlat(self.dim, self.hnsw_m, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efSearch = self.hnsw_ef_search
        else:
            raise ValueError(f"unknown index type {self.index_type}")
        return faiss.IndexIDMap2(base)

    def add(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> list[int]:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if len(chunks) == 0:
            return []
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise IndexCompatibilityError(f"expected vectors of dim {self.dim}, got {vectors.shape}")
        with self.lock.write():
            ids = np.arange(self._next_id, self._next_id + len(chunks), dtype=np.int64)
            self.index.add_with_ids(vectors, ids)
            for vid, chunk in zip(ids.tolist(), chunks, strict=True):
                self.chunks[vid] = chunk
                self._by_chunk_id[chunk.chunk_id] = chunk
            self._next_id += len(chunks)
            self.version += 1
        return ids.tolist()

    def delete_document(self, doc_id: str) -> int:
        with self.lock.write():
            ids = [vid for vid, c in self.chunks.items() if c.doc_id == doc_id]
            if not ids:
                return 0
            if self.index_type == "flat":
                self.index.remove_ids(np.array(ids, dtype=np.int64))
                for vid in ids:
                    self._by_chunk_id.pop(self.chunks.pop(vid).chunk_id, None)
            else:
                # HNSW graphs do not support removal: rebuild from the stored vectors.
                drop = set(ids)
                keep = [vid for vid in self.chunks if vid not in drop]
                vecs = (
                    np.stack([self.index.reconstruct(v) for v in keep])
                    if keep
                    else np.zeros((0, self.dim), np.float32)
                )
                for vid in ids:
                    self._by_chunk_id.pop(self.chunks.pop(vid).chunk_id, None)
                self.index = self._new_index()
                if keep:
                    self.index.add_with_ids(vecs, np.array(keep, dtype=np.int64))
            self.version += 1
            return len(ids)

    # ----------------------------------------------------------------- query
    @property
    def size(self) -> int:
        return int(self.index.ntotal)

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self.chunks.values()}

    def search(
        self, query: np.ndarray, k: int, *, doc_ids: Iterable[str] | None = None
    ) -> list[SearchHit]:
        q = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
        if q.shape[1] != self.dim:
            raise IndexCompatibilityError(f"query dim {q.shape[1]} != index dim {self.dim}")
        allowed = set(doc_ids) if doc_ids is not None else None
        with self.lock.read():
            if self.size == 0 or k <= 0:
                return []
            params = None
            if allowed is not None:
                sel_ids = np.array(
                    [vid for vid, c in self.chunks.items() if c.doc_id in allowed], dtype=np.int64
                )
                if len(sel_ids) == 0:
                    return []
                params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(sel_ids))
                k = min(k, len(sel_ids))
            scores, ids = self.index.search(q, min(k, self.size), params=params)
            hits = []
            for score, vid in zip(scores[0].tolist(), ids[0].tolist(), strict=True):
                if vid < 0:
                    continue
                chunk = self.chunks.get(vid)
                if chunk is None or (allowed is not None and chunk.doc_id not in allowed):
                    continue
                hits.append(SearchHit(chunk=chunk, score=float(score), vector_id=vid))
            return hits

    def get_vectors(self, vector_ids: Sequence[int]) -> np.ndarray:
        with self.lock.read():
            return np.stack([self.index.reconstruct(int(v)) for v in vector_ids])

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_chunk_id.get(chunk_id)

    def all_chunks(self) -> list[tuple[int, Chunk]]:
        with self.lock.read():
            return sorted(self.chunks.items())

    def memory_bytes(self) -> int:
        """Approximate index memory: raw vectors (+ HNSW graph links)."""
        vec = self.size * self.dim * 4
        if self.index_type == "hnsw":
            vec += self.size * self.hnsw_m * 2 * 4
        return vec

    # ----------------------------------------------------------- persistence
    def save(self, directory: Path) -> None:
        """Atomically write index + metadata: build in a temp dir, then swap."""
        directory = Path(directory)
        directory.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.read():
            tmp = Path(tempfile.mkdtemp(prefix=".index-", dir=directory.parent))
            try:
                faiss.write_index(self.index, str(tmp / INDEX_FILE))
                with (tmp / CHUNKS_FILE).open("w", encoding="utf-8") as fh:
                    for vid, chunk in sorted(self.chunks.items()):
                        fh.write(json.dumps({"id": vid, **chunk.to_dict()}, ensure_ascii=False) + "\n")
                manifest = {
                    "version": MANIFEST_VERSION,
                    "model_name": self.model_name,
                    "dim": self.dim,
                    "index_type": self.index_type,
                    "hnsw_m": self.hnsw_m,
                    "ntotal": self.size,
                    "next_id": self._next_id,
                    "index_sha256": _sha256_file(tmp / INDEX_FILE),
                    "chunks_sha256": _sha256_file(tmp / CHUNKS_FILE),
                }
                (tmp / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2))
                backup = directory.with_name(directory.name + ".old")
                if directory.exists():
                    if backup.exists():
                        shutil.rmtree(backup)
                    os.replace(directory, backup)
                os.replace(tmp, directory)
                if backup.exists():
                    shutil.rmtree(backup)
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
        log.info(kv("index_saved", path=directory, vectors=self.size))

    @classmethod
    def load(cls, directory: Path, *, model_name: str, dim: int, hnsw_ef_search: int = 64) -> FaissVectorStore:
        """Load and validate a persisted index. Raises IndexCompatibilityError on
        checksum mismatch, wrong model/dimension or inconsistent metadata."""
        directory = Path(directory)
        manifest_path = directory / MANIFEST_FILE
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexCompatibilityError(f"index manifest unreadable: {exc}") from exc
        if manifest.get("version") != MANIFEST_VERSION:
            raise IndexCompatibilityError("unsupported index manifest version")
        if manifest.get("model_name") != model_name or manifest.get("dim") != dim:
            raise IndexCompatibilityError(
                f"index was built with {manifest.get('model_name')} (dim {manifest.get('dim')}), "
                f"but the configured model is {model_name} (dim {dim}); rebuild required"
            )
        for fname, key in ((INDEX_FILE, "index_sha256"), (CHUNKS_FILE, "chunks_sha256")):
            path = directory / fname
            if not path.exists() or _sha256_file(path) != manifest.get(key):
                raise IndexCompatibilityError(f"{fname} is missing or fails its checksum")
        try:
            index = faiss.read_index(str(directory / INDEX_FILE))
        except Exception as exc:
            raise IndexCompatibilityError(f"FAISS index unreadable: {exc}") from exc
        store = cls(
            dim,
            model_name,
            index_type=manifest["index_type"],
            hnsw_m=manifest.get("hnsw_m", 32),
            hnsw_ef_search=hnsw_ef_search,
        )
        if index.d != dim or index.ntotal != manifest["ntotal"]:
            raise IndexCompatibilityError("index dimension or size disagrees with manifest")
        store.index = index
        if store.index_type == "hnsw":
            faiss.downcast_index(index.index).hnsw.efSearch = hnsw_ef_search
        with (directory / CHUNKS_FILE).open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                vid = int(row.pop("id"))
                chunk = Chunk.from_dict(row)
                store.chunks[vid] = chunk
                store._by_chunk_id[chunk.chunk_id] = chunk
        if len(store.chunks) != index.ntotal:
            raise IndexCompatibilityError("chunk metadata count disagrees with index size")
        store._next_id = int(manifest["next_id"])
        log.info(kv("index_loaded", path=directory, vectors=store.size))
        return store
