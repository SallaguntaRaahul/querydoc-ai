"""Bridge between the HTTP application and the QueryDoc RAG engine.

``EngineManager`` owns the single ``QueryDocService`` (embedding model, reranker,
FAISS index, local LLM) and applies validated runtime settings to it.
"""

from __future__ import annotations

import logging
import shutil
import threading
from typing import Any

from querydoc.config import Settings
from querydoc.ingestion.pdf_loader import ocr_available
from querydoc.services.rag_service import QueryDocService

log = logging.getLogger("querydoc.api.engine")

LLM_OPTIONS: list[dict[str, Any]] = [
    {"id": "Qwen/Qwen2.5-1.5B-Instruct", "label": "Qwen2.5 1.5B Instruct", "params": "1.5B",
     "approx_memory_gb": 3.1, "license": "Apache-2.0", "note": "Default: best measured answer accuracy"},
    {"id": "Qwen/Qwen2.5-0.5B-Instruct", "label": "Qwen2.5 0.5B Instruct", "params": "0.5B",
     "approx_memory_gb": 1.0, "license": "Apache-2.0", "note": "Low memory, faster, less accurate"},
]
EMBEDDING_OPTIONS = ["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"]

# Fields of SettingsModel that map 1:1 onto engine Settings.
ENGINE_FIELDS = (
    "embedding_model", "llm_model", "llm_device", "reranker_device", "chunk_size", "chunk_overlap",
    "top_k", "fetch_k", "use_hybrid", "use_rerank", "rerank_k", "max_new_tokens", "temperature", "enable_ocr",
)
UI_DEFAULTS = {"theme": "dark", "performance_mode": "balanced"}
PERFORMANCE_PRESETS: dict[str, dict[str, Any]] = {
    "quality": {"use_rerank": True, "use_hybrid": True, "rerank_k": 30},
    "balanced": {"use_rerank": True, "use_hybrid": True, "rerank_k": 20},
    "speed": {"use_rerank": False, "use_hybrid": True},
}


def available_devices() -> list[str]:
    import torch

    devices = ["auto", "cpu"]
    if torch.backends.mps.is_available():
        devices.append("mps")
    if torch.cuda.is_available():
        devices.append("cuda")
    return devices


class EngineManager:
    def __init__(self, settings: Settings | None = None, service: QueryDocService | None = None) -> None:
        self.service = service or QueryDocService(settings or Settings())
        self.ui: dict[str, Any] = dict(UI_DEFAULTS)
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- settings
    def current(self) -> dict[str, Any]:
        s = self.service.settings
        return {**{f: getattr(s, f) for f in ENGINE_FIELDS}, **self.ui}

    def apply(self, values: dict[str, Any], *, documents_exist: bool) -> list[str]:
        """Apply already-validated settings. Returns human-readable notes about
        side effects (model reloads). Raises ValueError on incompatible changes."""
        with self._lock:
            svc = self.service
            old = svc.settings
            engine_updates = {k: v for k, v in values.items() if k in ENGINE_FIELDS and getattr(old, k) != v}
            notes: list[str] = []
            if "llm_device" in engine_updates or "reranker_device" in engine_updates:
                devices = available_devices()
                for key in ("llm_device", "reranker_device"):
                    if key in engine_updates and engine_updates[key] not in devices:
                        raise ValueError(f"{key} '{engine_updates[key]}' is not available on this machine")
            if engine_updates.get("enable_ocr") and not ocr_available():
                raise ValueError("OCR needs Tesseract, which was not found on this machine (brew install tesseract).")
            if "llm_model" in engine_updates and engine_updates["llm_model"] not in {o["id"] for o in LLM_OPTIONS}:
                raise ValueError(f"unsupported LLM: {engine_updates['llm_model']}")
            if "embedding_model" in engine_updates:
                if engine_updates["embedding_model"] not in EMBEDDING_OPTIONS:
                    raise ValueError(f"unsupported embedding model: {engine_updates['embedding_model']}")
                if documents_exist or svc.store.size:
                    raise ValueError(
                        "The embedding model cannot change while documents are indexed: vectors from different "
                        "models are not comparable. Delete all documents first."
                    )
            new = old.model_copy(update=engine_updates)
            if "embedding_model" in engine_updates:
                index_dir = old.index_dir
                if index_dir.exists():
                    shutil.rmtree(index_dir)
                self.service = QueryDocService(new)
                notes.append("Embedding model changed; a new empty index was created.")
            else:
                svc.settings = new
                if {"llm_model", "llm_device"} & engine_updates.keys():
                    svc.reset_llm()
                    notes.append("The language model will reload on the next answer.")
                if "reranker_device" in engine_updates:
                    svc.reset_reranker()
                    notes.append("The reranker will reload on the next query.")
                if {"chunk_size", "chunk_overlap"} & engine_updates.keys():
                    notes.append("Chunking changes apply to new uploads; re-index existing documents to use them.")
            for k in UI_DEFAULTS:
                if k in values:
                    self.ui[k] = values[k]
            if engine_updates:
                log.info("settings applied", extra={"fields": {"changed": sorted(engine_updates)}})
            return notes

    # ------------------------------------------------------------------ status
    def model_status(self) -> dict[str, Any]:
        svc = self.service
        return {
            "embedder": {"model": svc.embedder.model_name, "device": svc.embedder.device, "loaded": True,
                         "dim": svc.embedder.dim},
            "reranker": {"model": svc.settings.reranker_model, "loaded": svc.reranker_loaded,
                         "device": svc.settings.reranker_device},
            "llm": {"model": svc.settings.llm_model, "device": svc.settings.llm_device,
                    "loaded": svc.llm_loaded, "error": svc.llm_error},
        }

    def warm_up(self) -> None:
        """Load the reranker and LLM in the background so the first question is fast."""
        try:
            self.service.reranker()
            self.service.llm()
        except Exception as exc:  # reported through model_status / retrieval-only mode
            log.warning("model warm-up failed", extra={"fields": {"error": str(exc)}})
