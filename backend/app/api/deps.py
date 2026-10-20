"""Shared FastAPI dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import AppSettings
from app.core.errors import APIError
from app.core.ratelimit import RateLimiter
from app.db.session import get_db
from app.models.entities import User
from app.rag.engine import EngineManager
from app.services import auth as auth_service
from app.workers.ingestion import IngestionWorker

T = TypeVar("T")


@dataclass
class AppContext:
    settings: AppSettings
    manager: EngineManager
    worker: IngestionWorker
    limiter: RateLimiter


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def get_user(request: Request, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> User:
    """The signed-in user, or the built-in local user when accounts are disabled."""
    if not ctx.settings.auth_enabled:
        return auth_service.local_user(db)
    user = auth_service.user_for_token(db, request.cookies.get(auth_service.COOKIE_NAME))
    if user is None:
        raise APIError(401, "not_authenticated", "Sign in to continue.")
    return user


def get_admin(user: User = Depends(get_user), ctx: AppContext = Depends(get_ctx)) -> User:
    if not auth_service.is_admin(user, ctx.settings):
        raise APIError(403, "forbidden", "Only an administrator can change these settings.")
    return user


def client_ip(request: Request) -> str:
    """Visitor IP for rate limits: the proxy's header (first entry), else the socket peer."""
    ctx: AppContext = request.app.state.ctx
    fwd = request.headers.get(ctx.settings.client_ip_header)
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


async def run_blocking(ctx: AppContext, fn: Callable[[], T]) -> T:
    """Run CPU/IO-bound work off the event loop with the configured request timeout."""
    try:
        return await asyncio.wait_for(run_in_threadpool(fn), timeout=ctx.settings.request_timeout_s)
    except asyncio.TimeoutError as exc:
        raise APIError(504, "timeout", f"The request took longer than {ctx.settings.request_timeout_s:.0f}s.") from exc
