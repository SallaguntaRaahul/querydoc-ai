"""QueryDoc AI — FastAPI application factory.

Run (development):  uvicorn app.main:app --reload --port 8000   (from backend/)
Author: Raahul Sallagunta
"""

from __future__ import annotations

# isort: off
import querydoc  # noqa: F401  (macOS OpenMP guard must run before torch/faiss load)
# isort: on
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import AppContext
from app.api.v1 import auth, chat, documents, misc
from app.core.config import AppSettings, get_app_settings
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.ratelimit import RateLimiter
from app.db.migrate import upgrade_to_head
from app.db.session import init_engine, session_scope
from app.rag.engine import EngineManager
from app.services import documents as documents_service
from app.services import settings as settings_service
from app.services.backup import HubBackup
from app.workers.ingestion import IngestionWorker
from querydoc.config import Settings

log = logging.getLogger("querydoc.api")
API_PREFIX = "/api/v1"


def create_app(app_settings: AppSettings | None = None, manager: EngineManager | None = None) -> FastAPI:
    configure_logging()
    cfg = app_settings or get_app_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        backup = HubBackup(cfg.hf_backup_repo, cfg.data_dir, cfg.hf_backup_interval_s) if cfg.hf_backup_repo else None
        if backup:
            backup.restore()  # before migrations, so a restored database is upgraded too
        upgrade_to_head(cfg.sqlalchemy_url)
        init_engine(cfg.sqlalchemy_url)
        mgr = manager or EngineManager(Settings(data_dir=cfg.data_dir, max_upload_mb=cfg.max_upload_mb))
        worker = IngestionWorker(mgr, cfg.uploads_dir, cfg.ingestion_workers)
        with session_scope() as db:
            settings_service.load_persisted(db, mgr)
            stats = documents_service.reconcile(db, mgr, worker)
        app.state.ctx = AppContext(settings=cfg, manager=mgr, worker=worker, limiter=RateLimiter())
        log.info("startup complete", extra={"fields": {"reconcile": stats, "vectors": mgr.service.store.size}})
        if cfg.load_models_on_startup:
            threading.Thread(target=mgr.warm_up, name="warm-up", daemon=True).start()
        if backup:
            backup.start(mgr)
        app.state.backup = backup
        yield
        worker.shutdown()
        if backup:
            backup.stop()  # final snapshot on shutdown

    app = FastAPI(
        title="QueryDoc AI API",
        version=misc.VERSION,
        description="Local PDF retrieval-augmented generation with verified page-level citations. "
                    "Author: Raahul Sallagunta. Accounts with cookie sessions when QUERYDOC_AUTH_ENABLED=true; "
                    "otherwise local single-user mode without authentication.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """CSRF defence for cookie sessions: browsers always send Origin on cross-site
        POST/PUT/DELETE, so a write whose Origin is neither this host nor an allowed
        origin is refused."""
        if cfg.auth_enabled and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != "null":
                host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
                if urlsplit(origin).netloc != host and origin not in cfg.cors_origins:
                    return JSONResponse(error_body("forbidden_origin", "Cross-site request refused."), status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover - handled by exception handlers
            log.exception("request failed")
            response = JSONResponse(error_body("internal_error", "An unexpected error occurred."), status_code=500)
        response.headers["X-Request-ID"] = rid
        if request.url.path.startswith(API_PREFIX):
            log.info("request", extra={"fields": {
                "method": request.method, "path": request.url.path, "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1)}})
        request_id_var.reset(token)
        return response

    install_error_handlers(app)
    for router in (auth.router, documents.router, chat.router, misc.conversations, misc.analytics, misc.settings, misc.health):
        app.include_router(router, prefix=API_PREFIX)

    # Production-style local build: serve the compiled React app from the same origin.
    dist = cfg.frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
