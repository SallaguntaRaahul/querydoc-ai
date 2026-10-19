"""Consistent error responses: ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from querydoc.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    GenerationTimeoutError,
    GenerationUnavailableError,
    IndexCompatibilityError,
    PasswordProtectedPDFError,
    PDFValidationError,
    QueryDocError,
    QueueFullError,
)

log = logging.getLogger("querydoc.api")


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, details: object | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_body(code: str, message: str, details: object | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


# Engine exception -> (HTTP status, machine-readable code)
_ENGINE_ERRORS: list[tuple[type[Exception], int, str]] = [
    (DuplicateDocumentError, 409, "duplicate_document"),
    (PasswordProtectedPDFError, 422, "password_protected"),
    (PDFValidationError, 422, "invalid_pdf"),
    (DocumentNotFoundError, 404, "document_not_found"),
    (QueueFullError, 429, "generation_queue_full"),
    (GenerationTimeoutError, 503, "generation_timeout"),
    (GenerationUnavailableError, 503, "model_unavailable"),
    (IndexCompatibilityError, 500, "index_incompatible"),
    (QueryDocError, 400, "bad_request"),
]


def map_engine_error(exc: Exception) -> tuple[int, str]:
    for cls, status, code in _ENGINE_ERRORS:
        if isinstance(exc, cls):
            return status, code
    return 500, "internal_error"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(QueryDocError)
    async def _engine_error(_: Request, exc: QueryDocError) -> JSONResponse:
        status, code = map_engine_error(exc)
        return JSONResponse(error_body(code, str(exc)), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(error_body("validation_error", "Request validation failed.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(error_body("internal_error", "An unexpected error occurred."), status_code=500)
