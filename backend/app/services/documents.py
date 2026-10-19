"""Document lifecycle: upload validation, storage, background indexing,
deletion, re-indexing and start-up reconciliation with the engine index."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models.entities import Document
from app.rag.engine import EngineManager
from app.workers.ingestion import IngestionWorker
from querydoc.exceptions import DocumentNotFoundError, PDFValidationError
from querydoc.ingestion.pdf_loader import (
    content_hash,
    doc_id_from_hash,
    sanitize_filename,
    validate_pdf_bytes,
)

log = logging.getLogger("querydoc.api.documents")


def get_document_or_404(db: Session, doc_id: str) -> Document:
    if len(doc_id) != 16 or any(c not in "0123456789abcdef" for c in doc_id):
        raise APIError(404, "document_not_found", "Document not found.")
    doc = db.get(Document, doc_id)
    if doc is None:
        raise APIError(404, "document_not_found", "Document not found.")
    return doc


def accept_upload(
    db: Session, worker: IngestionWorker, data: bytes, filename: str, *, max_upload_mb: float
) -> Document:
    """Validate bytes synchronously (cheap checks), persist to the upload area and
    queue background indexing. Raises APIError for invalid or duplicate files."""
    safe_name = sanitize_filename(filename)
    if not (filename or "").lower().endswith(".pdf"):
        raise APIError(415, "unsupported_type", f"'{safe_name}' is not a .pdf file.")
    try:
        validate_pdf_bytes(data, max_upload_mb=max_upload_mb)
    except PDFValidationError as exc:
        status = 413 if "limit" in str(exc) else 422
        raise APIError(status, "invalid_pdf", str(exc)) from exc
    sha = content_hash(data)
    doc_id = doc_id_from_hash(sha)
    existing = db.scalar(select(Document).where(Document.sha256 == sha))
    if existing is not None:
        if existing.status == "failed":
            db.delete(existing)
            db.flush()
        else:
            raise APIError(409, "duplicate_document", f"'{safe_name}' is already in the library as '{existing.filename}'.",
                           {"document_id": existing.id})
    worker.upload_path(doc_id).write_bytes(data)
    doc = Document(
        id=doc_id, filename=safe_name, title=Path(safe_name).stem, sha256=sha, size_bytes=len(data),
        status="queued", stage="queued", progress=0.0,
    )
    db.add(doc)
    db.commit()  # the worker thread must see the row before it starts
    worker.submit_ingest(doc_id, safe_name)
    return doc


def delete_document(db: Session, manager: EngineManager, worker: IngestionWorker, doc: Document) -> None:
    if doc.status in {"queued", "processing"}:
        raise APIError(409, "document_busy", "The document is still being processed; try again when it finishes.")
    with contextlib.suppress(DocumentNotFoundError):  # failed documents never reached the index
        manager.service.delete_document(doc.id)
    worker.upload_path(doc.id).unlink(missing_ok=True)
    db.delete(doc)
    log.info("document deleted", extra={"fields": {"doc_id": doc.id}})


def reindex_document(db: Session, worker: IngestionWorker, manager: EngineManager, doc: Document) -> Document:
    if doc.status in {"queued", "processing"}:
        raise APIError(409, "document_busy", "The document is already being processed.")
    if not manager.service.document_path(doc.id).exists() and not worker.upload_path(doc.id).exists():
        raise APIError(410, "file_missing", "The original PDF is no longer available; upload it again.")
    doc.status, doc.stage, doc.progress, doc.error = "queued", "queued", 0.0, None
    db.commit()
    worker.submit_reindex(doc.id, doc.filename)
    return doc


def reconcile(db: Session, manager: EngineManager, worker: IngestionWorker) -> dict[str, int]:
    """Make the database agree with the engine index after a restart."""
    svc = manager.service
    engine_docs = {r.doc_id: r for r in svc.documents()}
    db_docs = {d.id: d for d in db.scalars(select(Document))}
    stats = {"imported": 0, "requeued": 0, "marked_failed": 0}
    for doc_id, rec in engine_docs.items():
        if doc_id not in db_docs:
            db.add(Document(
                id=doc_id, filename=rec.filename, title=rec.title, sha256=rec.sha256, size_bytes=rec.size_bytes,
                page_count=rec.page_count, chunk_count=rec.chunk_count, status="ready", stage="ready",
                progress=1.0, chunking=rec.chunking, timings_ms=rec.timings_ms, scanned_pages=rec.scanned_pages,
            ))
            stats["imported"] += 1
    for doc_id, doc in db_docs.items():
        if doc.status == "ready" and doc_id not in engine_docs:
            doc.status, doc.stage, doc.error = "failed", "failed", "Index entry missing; re-upload or re-index."
            stats["marked_failed"] += 1
        elif doc.status in {"queued", "processing"}:
            if worker.upload_path(doc_id).exists():
                doc.status, doc.stage, doc.progress = "queued", "queued", 0.0
                db.commit()
                worker.submit_ingest(doc_id, doc.filename)
                stats["requeued"] += 1
            else:
                doc.status, doc.stage, doc.error = "failed", "failed", "Processing was interrupted; upload again."
                stats["marked_failed"] += 1
    return stats
