"""Central configuration for QueryDoc AI.

All values can be overridden with environment variables prefixed ``QUERYDOC_``
(for example ``QUERYDOC_CHUNK_SIZE=600``) or through a ``.env`` file.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

T = TypeVar("T")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ChunkStrategy = Literal["fixed", "recursive", "sentence"]
IndexType = Literal["flat", "hnsw"]
DeviceName = Literal["auto", "cpu", "mps", "cuda"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUERYDOC_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Field(default=PROJECT_ROOT / "data" / "workspace")

    # Ingestion limits
    max_upload_mb: float = 50.0
    max_pages: int = 1000
    min_chars_per_page: int = 20  # below this a page with images is flagged as likely scanned
    enable_ocr: bool = False

    # Chunking
    chunk_strategy: ChunkStrategy = "recursive"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_chunk_chars: int = 40

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = 32
    embedding_device: DeviceName = "cpu"
    torch_threads: int = 4

    # Vector index
    index_type: IndexType = "flat"
    hnsw_m: int = 32
    hnsw_ef_search: int = 64

    # Retrieval
    top_k: int = 5
    fetch_k: int = 30
    use_hybrid: bool = True
    use_mmr: bool = False
    mmr_lambda: float = 0.7
    use_rerank: bool = True
    rerank_k: int | None = 20  # candidates passed to the cross-encoder
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_device: DeviceName = "auto"  # MPS/CUDA when available: ~3x faster than CPU on an M3 Pro
    # Below this best dense cosine score the system declines to answer.
    min_relevance_score: float = 0.25

    # Generation
    # 1.5B chosen over 0.5B on measured answer accuracy (results/generation); 0.5B is the low-memory option.
    llm_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    llm_device: DeviceName = "auto"
    max_new_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 0.9
    max_context_tokens: int = 2048

    # Concurrency
    max_active_generations: int = 1
    max_generation_queue: int = 8
    generation_timeout_s: float = 120.0

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def embedding_cache_dir(self) -> Path:
        return self.data_dir / "embedding_cache"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_local_first(loader: Callable[..., T], name: str) -> T:
    """Call ``loader(local_files_only=True)`` and fall back to a network download only
    when the model is not in the local Hugging Face cache. Cached models therefore
    load without any network round trip (a stalled Hub request once blocked app startup)."""
    try:
        return loader(local_files_only=True)
    except Exception as exc:  # not cached (or incomplete cache): download once
        from querydoc.logging_utils import get_logger, kv

        get_logger(__name__).info(kv("model_not_cached_downloading", model=name, reason=type(exc).__name__))
        return loader(local_files_only=False)


def resolve_device(name: str) -> str:
    """Map ``auto`` to the best available torch device."""
    if name != "auto":
        return name
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
