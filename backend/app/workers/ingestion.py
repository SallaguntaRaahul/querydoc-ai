"""Background ingestion: PDF extraction, chunking, embedding and indexing run in
a bounded thread pool so API requests and the event loop stay responsive.
Progress is written to the ``documents`` table and polled by the UI."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from app.db.session import session_scope
from app.models.entities import Document
from app.rag.engine import EngineManager
from querydoc.exceptions import DocumentNotFoundError, DuplicateDocumentError, QueryDocError

log = logging.getLogger("querydoc.api.ingestion")

# Overall progress = stage offset + stage fraction * stage weight
_STAGE_WEIGHTS = {"extract": (0.0, 0.35), "embed": (0.35, 0.6), "done": (1.0, 0.0)}


class IngestionWorker:
    def __init__(self, manager: EngineManager, uploads_dir: Path, workers: int = 1) -> None:
        self.manager = manager
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ingest")
        self._pending: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    @property
    def queue_size(self) -> int:
        with self._lock:
            return sum(1 for f in self._pending.values() if not f.done())

    def upload_path(self, doc_id: str) -> Path:
        return self.uploads_dir / f"{doc_id}.pdf"

    def submit_ingest(self, doc_id: str, filename: str) -> None:
        self._submit(doc_id, lambda: self._ingest(doc_id, filename, reindex=False))

    def submit_reindex(self, doc_id: str, filename: str) -> None:
        self._submit(doc_id, lambda: self._ingest(doc_id, filename, reindex=True))

    def _submit(self, doc_id: str, fn: Callable[[], None]) -> None:
        with self._lock:
            current = self._pending.get(doc_id)
            if current is not None and not current.done():
                raise QueryDocError("This document is already being processed.")
            self._pending[doc_id] = self._pool.submit(fn)

    def wait_idle(self, timeout: float = 120.0) -> bool:
        """Test helper: block until queued jobs finish."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.queue_size == 0:
                return True
            time.sleep(0.05)
        return False

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ jobs
    def _update(self, doc_id: str, **fields: object) -> None:
        with session_scope() as s:
            doc = s.get(Document, doc_id)
            if doc is None:
                return
            for k, v in fields.items():
                setattr(doc, k, v)

    def _ingest(self, doc_id: str, filename: str, *, reindex: bool) -> None:
        svc = self.manager.service
        path = self.upload_path(doc_id)
        started = time.perf_counter()
        try:
            if reindex:
                # Keep a copy of the stored PDF until the new index entry exists.
                stored = svc.document_path(doc_id)
                if not path.exists():
                    if not stored.exists():
                        raise DocumentNotFoundError("The original PDF is missing; upload it again.")
                    path.write_bytes(stored.read_bytes())
            data = path.read_bytes()
            self._update(doc_id, status="processing", stage="starting", progress=0.0, error=None)
            if reindex:
                with contextlib.suppress(DocumentNotFoundError):
                    svc.delete_document(doc_id)

            last = [0.0]

            def progress(stage: str, frac: float) -> None:
                now = time.monotonic()
                if stage != "done" and now - last[0] < 0.4:
                    return
                last[0] = now
                offset, weight = _STAGE_WEIGHTS.get(stage, (0.95, 0.0))
                self._update(doc_id, stage=stage, progress=round(min(offset + frac * weight, 0.99), 3))

            report = svc.ingest(data, filename, chunking=svc.chunking_config(), progress=progress, doc_id=doc_id)
            rec = report.record
            self._update(
                doc_id,
                status="ready", stage="ready", progress=1.0, error=None,
                title=rec.title, page_count=rec.page_count, chunk_count=rec.chunk_count,
                chunking=rec.chunking, timings_ms=report.timings_ms, embedding_stats=report.embedding,
                scanned_pages=rec.scanned_pages,
            )
            path.unlink(missing_ok=True)
            log.info("document indexed", extra={"fields": {
                "doc_id": doc_id, "pages": rec.page_count, "chunks": rec.chunk_count,
                "seconds": round(time.perf_counter() - started, 2), "reindex": reindex}})
        except DuplicateDocumentError as exc:
            self._update(doc_id, status="failed", stage="failed", error=str(exc))
            path.unlink(missing_ok=True)
        except QueryDocError as exc:
            self._update(doc_id, status="failed", stage="failed", error=str(exc))
            path.unlink(missing_ok=True)
        except Exception as exc:  # unexpected: keep the upload so a retry is possible
            log.exception("ingestion failed")
            self._update(doc_id, status="failed", stage="failed", error=f"Unexpected error: {exc}")
