import json

import numpy as np
import pytest

from querydoc.chunking.chunkers import Chunk
from querydoc.embeddings.embedder import EmbeddingCache, EmbeddingStats
from querydoc.exceptions import IndexCompatibilityError
from querydoc.vectorstore.faiss_store import FaissVectorStore

DIM = 8


def chunk(i: int, doc: str = "aaaaaaaaaaaaaaaa") -> Chunk:
    return Chunk(f"{doc}-{i:05d}", doc, f"{doc}.pdf", f"text {i}", 1, 1, i, i * 10)


def unit(rows: int, seed: int = 0) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=(rows, DIM)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# ---------------------------------------------------------------- embeddings
def test_embedder_normalized_batched_and_cached(embedder):
    texts = ["alpha beta", "gamma delta", "alpha beta", "epsilon"]
    stats = EmbeddingStats()
    v = embedder.embed_texts(texts, batch_size=2, use_cache=False, stats=stats)
    assert v.shape == (4, embedder.dim) and v.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4)
    np.testing.assert_array_equal(v[0], v[2])  # duplicate encoded once
    assert stats.unique_texts == 3 and stats.encoded == 3


def test_embedding_matches_unbatched(embedder):
    texts = [f"sentence number {i}" for i in range(10)]
    a = embedder.embed_texts(texts, batch_size=4, use_cache=False)
    b = embedder.embed_texts(texts, batch_size=1, use_cache=False)
    np.testing.assert_allclose(a, b, atol=1e-4)


def test_embedding_cache_hit_rate(embedder):
    texts = ["cache me once", "cache me twice"]
    embedder.embed_texts(texts)
    stats = EmbeddingStats()
    embedder.embed_texts(texts, stats=stats)
    assert stats.cache_hit_rate == 1.0 and stats.encoded == 0


def test_cache_persistence_and_incompatible_model(tmp_path):
    path = tmp_path / "c.npz"
    cache = EmbeddingCache(path, "m1", DIM)
    cache.put_many(["k" * 64], unit(1))
    cache.save()
    assert len(EmbeddingCache(path, "m1", DIM)) == 1
    assert len(EmbeddingCache(path, "other-model", DIM)) == 0


def test_corrupt_cache_is_ignored(tmp_path):
    path = tmp_path / "c.npz"
    path.write_bytes(b"not a zip file")
    assert len(EmbeddingCache(path, "m1", DIM)) == 0


# --------------------------------------------------------------------- store
@pytest.mark.parametrize("index_type", ["flat", "hnsw"])
def test_store_add_search_filter_delete(index_type):
    store = FaissVectorStore(DIM, "m", index_type=index_type)
    vecs = unit(20)
    store.add([chunk(i, "a" * 16) for i in range(10)], vecs[:10])
    store.add([chunk(i, "b" * 16) for i in range(10)], vecs[10:])
    hits = store.search(vecs[3], 3)
    assert hits[0].chunk.chunk_id == f"{'a' * 16}-00003"
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)
    only_b = store.search(vecs[3], 5, doc_ids=["b" * 16])
    assert only_b and all(h.chunk.doc_id == "b" * 16 for h in only_b)
    assert store.delete_document("a" * 16) == 10
    assert store.size == 10
    assert all(h.chunk.doc_id == "b" * 16 for h in store.search(vecs[3], 5))
    assert store.get_chunk(f"{'a' * 16}-00003") is None


def test_store_rejects_wrong_dimension():
    store = FaissVectorStore(DIM, "m")
    with pytest.raises(IndexCompatibilityError):
        store.add([chunk(0)], np.zeros((1, DIM + 1), np.float32))


def test_store_persistence_roundtrip(tmp_path):
    store = FaissVectorStore(DIM, "m")
    vecs = unit(5)
    store.add([chunk(i) for i in range(5)], vecs)
    store.save(tmp_path / "idx")
    loaded = FaissVectorStore.load(tmp_path / "idx", model_name="m", dim=DIM)
    assert loaded.size == 5
    assert loaded.search(vecs[2], 1)[0].chunk == store.search(vecs[2], 1)[0].chunk
    # ids keep increasing after reload
    loaded.add([chunk(9)], unit(1, seed=3))
    assert loaded.size == 6


def test_load_rejects_model_mismatch(tmp_path):
    store = FaissVectorStore(DIM, "m")
    store.add([chunk(0)], unit(1))
    store.save(tmp_path / "idx")
    with pytest.raises(IndexCompatibilityError, match="rebuild"):
        FaissVectorStore.load(tmp_path / "idx", model_name="other", dim=DIM)


def test_load_rejects_tampered_files(tmp_path):
    store = FaissVectorStore(DIM, "m")
    store.add([chunk(0)], unit(1))
    store.save(tmp_path / "idx")
    with (tmp_path / "idx" / "chunks.jsonl").open("a") as fh:
        fh.write(json.dumps({"id": 99}) + "\n")
    with pytest.raises(IndexCompatibilityError, match="checksum"):
        FaissVectorStore.load(tmp_path / "idx", model_name="m", dim=DIM)


def test_load_rejects_garbage_index(tmp_path):
    (tmp_path / "idx").mkdir()
    (tmp_path / "idx" / "manifest.json").write_text("{not json")
    with pytest.raises(IndexCompatibilityError):
        FaissVectorStore.load(tmp_path / "idx", model_name="m", dim=DIM)
