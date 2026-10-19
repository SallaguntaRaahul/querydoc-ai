from __future__ import annotations

import os
from pathlib import Path

import pytest

import querydoc  # noqa: F401  (macOS OpenMP guard must run before torch/faiss)
from querydoc.config import Settings
from querydoc.evaluation.synthetic import make_synthetic_pdf

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def make_settings(tmp: Path, **overrides: object) -> Settings:
    base: dict[str, object] = dict(
        data_dir=tmp / "workspace",
        use_rerank=False,
        use_hybrid=True,
        chunk_size=500,
        chunk_overlap=100,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def embedder():
    from querydoc.embeddings.embedder import Embedder

    return Embedder(EMBED_MODEL, device="cpu", batch_size=32)


@pytest.fixture(scope="session")
def synthetic_120():
    return make_synthetic_pdf(120, seed=11)


@pytest.fixture()
def service(tmp_path, embedder):
    from querydoc.services.rag_service import QueryDocService

    return QueryDocService(make_settings(tmp_path), embedder=embedder)


def llm_available() -> bool:
    if os.environ.get("QUERYDOC_SKIP_LLM") == "1":
        return False
    from huggingface_hub import try_to_load_from_cache

    path = try_to_load_from_cache("Qwen/Qwen2.5-0.5B-Instruct", "config.json")
    return isinstance(path, str)
