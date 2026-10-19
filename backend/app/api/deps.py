"""Shared FastAPI dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.core.config import AppSettings
from app.core.errors import APIError
from app.rag.engine import EngineManager
from app.workers.ingestion import IngestionWorker

T = TypeVar("T")


@dataclass
class AppContext:
    settings: AppSettings
    manager: EngineManager
    worker: IngestionWorker


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


async def run_blocking(ctx: AppContext, fn: Callable[[], T]) -> T:
    """Run CPU/IO-bound work off the event loop with the configured request timeout."""
    try:
        return await asyncio.wait_for(run_in_threadpool(fn), timeout=ctx.settings.request_timeout_s)
    except asyncio.TimeoutError as exc:
        raise APIError(504, "timeout", f"The request took longer than {ctx.settings.request_timeout_s:.0f}s.") from exc
