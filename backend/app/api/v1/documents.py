"""/api/v1/documents — upload, list, inspect, download, delete, re-index."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppContext, get_ctx, get_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.entities import Document, User
from app.schemas.api import (
    DocumentList,
    DocumentOut,
    DocumentStatus,
    ErrorResponse,
    UploadError,
    UploadResult,
)
from app.services import documents as svc

router = APIRouter(prefix="/documents", tags=["documents"])
MAX_FILES_PER_UPLOAD = 20
_CHUNK = 1024 * 1024


async def _read_limited(file: UploadFile, limit_bytes: int) -> bytes:
    """Read an upload without ever holding more than limit + 1 MB in memory."""
    buf = bytearray()
    while chunk := await file.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > limit_bytes:
            raise APIError(413, "file_too_large", f"'{file.filename}' exceeds the {limit_bytes // (1024 * 1024)} MB limit.")
    return bytes(buf)


@router.post(
    "/upload", response_model=UploadResult, status_code=status.HTTP_202_ACCEPTED,
    responses={413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Upload one or more PDFs; indexing continues in the background",
)
async def upload(
    files: list[UploadFile] = File(...),
    ctx: AppContext = Depends(get_ctx),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
) -> UploadResult:
    if not files:
        raise APIError(422, "no_files", "No files were uploaded.")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise APIError(422, "too_many_files", f"Upload at most {MAX_FILES_PER_UPLOAD} files at once.")
    limit = int(ctx.settings.max_upload_mb * 1024 * 1024)
    accepted: list[DocumentOut] = []
    errors: list[UploadError] = []
    for f in files:
        name = f.filename or "upload.pdf"
        try:
            data = await _read_limited(f, limit)
            if ctx.settings.auth_enabled:
                svc.check_quota(db, user, len(data), max_documents=ctx.settings.max_documents_per_user,
                                max_storage_mb=ctx.settings.max_storage_mb_per_user)
            doc = svc.accept_upload(db, ctx.worker, data, name, user, max_upload_mb=ctx.settings.max_upload_mb)
            accepted.append(DocumentOut.model_validate(doc))
        except APIError as exc:
            if len(files) == 1:
                raise
            errors.append(UploadError(filename=name, code=exc.code, message=exc.message))
        finally:
            await f.close()
    return UploadResult(documents=accepted, errors=errors)


@router.get("", response_model=DocumentList, summary="List documents")
def list_documents(
    q: str | None = Query(default=None, max_length=200, description="Filter by filename/title"),
    status_: str | None = Query(default=None, alias="status", pattern="^(queued|processing|ready|failed)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
) -> DocumentList:
    stmt = select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc())
    if status_:
        stmt = stmt.where(Document.status == status_)
    items = list(db.scalars(stmt))
    if q:
        needle = q.lower()
        items = [d for d in items if needle in d.filename.lower() or needle in (d.title or "").lower()]
    return DocumentList(items=[DocumentOut.model_validate(d) for d in items], total=len(items))


@router.get("/{document_id}", response_model=DocumentOut, responses={404: {"model": ErrorResponse}})
def get_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)) -> DocumentOut:
    return DocumentOut.model_validate(svc.get_document_or_404(db, document_id, user))


@router.get("/{document_id}/status", response_model=DocumentStatus)
def document_status(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)) -> DocumentStatus:
    d = svc.get_document_or_404(db, document_id, user)
    return DocumentStatus(id=d.id, status=d.status, stage=d.stage, progress=d.progress, error=d.error)


@router.get("/{document_id}/file", response_class=FileResponse, summary="Download the stored PDF")
def document_file(document_id: str, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db),
                  user: User = Depends(get_user)) -> FileResponse:
    d = svc.get_document_or_404(db, document_id, user)
    path = ctx.manager.service.document_path(d.id)  # path built from a validated hex id only
    if not path.exists():
        path = ctx.worker.upload_path(d.id)
    if not path.exists():
        raise APIError(404, "file_missing", "The PDF file is not available.")
    return FileResponse(path, media_type="application/pdf", filename=d.filename,
                        content_disposition_type="inline", headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, responses={409: {"model": ErrorResponse}})
def delete_document(document_id: str, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db),
                    user: User = Depends(get_user)) -> None:
    d = svc.get_document_or_404(db, document_id, user)
    svc.delete_document(db, ctx.manager, ctx.worker, d)


@router.post("/{document_id}/reindex", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reindex(document_id: str, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db),
            user: User = Depends(get_user)) -> DocumentOut:
    d = svc.get_document_or_404(db, document_id, user)
    return DocumentOut.model_validate(svc.reindex_document(db, ctx.worker, ctx.manager, d))
