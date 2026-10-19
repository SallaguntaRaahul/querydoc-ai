"""/api/v1/chat — blocking and Server-Sent-Events streaming answers.

Streaming design
----------------
The engine's ``answer_stream`` is a synchronous generator (PyTorch generation
cannot run on the event loop). It runs in a dedicated worker thread that pushes
events into an ``asyncio.Queue`` via ``loop.call_soon_threadsafe``. The async
SSE generator drains that queue. If the client disconnects or the stream
exceeds ``stream_timeout_s``, a ``threading.Event`` is set and the LLM's
stopping criterion ends generation at the next token, releasing the GPU and the
admission slot. The final message is persisted by the worker thread itself, so
the database stays consistent even when nobody is listening anymore.

Event types: ``meta`` → ``retrieval`` → ``token``* → ``done`` (or ``error``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import AppContext, get_ctx, run_blocking
from app.core.errors import APIError, map_engine_error
from app.db.session import get_db, session_scope
from app.models.entities import Message
from app.schemas.api import ChatRequest, ChatResponse, ErrorResponse, MessageOut
from app.services import chat as chat_service
from querydoc.exceptions import QueryDocError
from querydoc.retrieval.retriever import RetrievalResult
from querydoc.services.rag_service import RAGResponse

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger("querydoc.api.chat")
KEEPALIVE_S = 10.0


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("", response_model=ChatResponse, responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
async def chat(req: ChatRequest, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> ChatResponse:
    prep = await run_in_threadpool(chat_service.prepare, db, ctx.manager, req)
    svc = ctx.manager.service

    def run() -> tuple[MessageOut, MessageOut]:
        try:
            resp = svc.answer(prep.question, prep.retrieval, prep.params, history=prep.history)
        except QueryDocError as exc:
            status, code = map_engine_error(exc)
            with session_scope() as s:
                chat_service.finalize_error(s, prep, code, str(exc))
            raise APIError(status, code, str(exc)) from exc
        with session_scope() as s:
            msg = chat_service.finalize(s, ctx.manager, prep, resp, streamed=False)
            user = s.get(Message, prep.user_message_id)
            return MessageOut.model_validate(user), MessageOut.model_validate(msg)

    timeout = ctx.settings.stream_timeout_s
    try:
        user, msg = await asyncio.wait_for(run_in_threadpool(run), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise APIError(504, "timeout", f"No answer within {timeout:.0f}s.") from exc
    return ChatResponse(conversation_id=prep.conversation_id, user_message=user, message=msg)


@router.post(
    "/stream",
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE: meta, retrieval, token*, done | error"},
               400: {"model": ErrorResponse}},
    summary="Stream an answer as Server-Sent Events",
)
async def chat_stream(req: ChatRequest, request: Request, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    def _prepare() -> chat_service.PreparedChat:
        with session_scope() as s:
            return chat_service.prepare(s, ctx.manager, req)

    prep = await run_blocking(ctx, _prepare)
    with session_scope() as s:
        user_out = MessageOut.model_validate(s.get(Message, prep.user_message_id))
    svc = ctx.manager.service
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    cancel = threading.Event()

    def push(kind: str, payload: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def worker() -> None:
        try:
            for kind, payload in svc.answer_stream(
                prep.question, prep.retrieval, prep.params, history=prep.history, cancel=cancel
            ):
                if kind == "retrieval":
                    assert isinstance(payload, RetrievalResult)
                    push("retrieval", {"sources": chat_service.sources_payload(payload),
                                       "latency_ms": round(payload.latency_ms, 1)})
                elif kind == "token":
                    push("token", {"text": payload})
                elif kind == "final":
                    assert isinstance(payload, RAGResponse)
                    with session_scope() as s:
                        msg = chat_service.finalize(s, ctx.manager, prep, payload, streamed=True)
                        push("done", {"conversation_id": prep.conversation_id,
                                      "message": MessageOut.model_validate(msg).model_dump(mode="json")})
        except QueryDocError as exc:
            status, code = map_engine_error(exc)
            with session_scope() as s:
                msg = chat_service.finalize_error(s, prep, code, str(exc))
                push("error", {"code": code, "status": status, "message": str(exc),
                               "message_id": msg.id})
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("stream worker failed")
            push("error", {"code": "internal_error", "status": 500, "message": f"Generation failed: {exc}"})
        finally:
            push("end", None)

    threading.Thread(target=worker, name="chat-stream", daemon=True).start()
    deadline = time.monotonic() + ctx.settings.stream_timeout_s

    async def events() -> AsyncIterator[str]:
        yield _sse("meta", {"conversation_id": prep.conversation_id, "user_message": user_out.model_dump(mode="json"),
                            "document_ids": prep.scope})
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        cancel.set()
                        return
                    if time.monotonic() > deadline:
                        cancel.set()
                        yield _sse("error", {"code": "timeout", "status": 504, "message": "The answer took too long."})
                        return
                    yield ": keep-alive\n\n"
                    continue
                if kind == "end":
                    return
                if time.monotonic() > deadline and kind == "token":
                    cancel.set()
                    yield _sse("error", {"code": "timeout", "status": 504, "message": "The answer took too long."})
                    return
                yield _sse(kind, payload)
                if kind in {"done", "error"}:
                    return
        except asyncio.CancelledError:  # client went away mid-stream
            cancel.set()
            raise
        finally:
            if not cancel.is_set() and await request.is_disconnected():
                cancel.set()

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
