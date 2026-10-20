"""Conversation management around the RAG engine: document scoping, follow-up
history, persistence of messages/citations, and runtime telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models.entities import Conversation, Document, Message, QueryLog, User
from app.rag.engine import EngineManager
from app.schemas.api import ChatRequest, MessageOut
from querydoc.generation.llm import GenerationParams
from querydoc.retrieval.retriever import RetrievalConfig, RetrievalResult
from querydoc.services.rag_service import RAGResponse

SOURCE_TEXT_CHARS = 1500


@dataclass
class PreparedChat:
    conversation_id: str
    owner_id: str
    user_message_id: str
    question: str
    scope: list[str]
    history: list[tuple[str, str]]
    retrieval: RetrievalConfig
    params: GenerationParams


def sources_payload(result: RetrievalResult) -> list[dict[str, Any]]:
    return [
        {
            "rank": r.rank, "chunk_id": r.chunk.chunk_id, "doc_id": r.chunk.doc_id, "source": r.chunk.source,
            "page_start": r.chunk.page_start, "page_end": r.chunk.page_end, "score": float(r.score),
            "scores": {k: float(v) for k, v in r.scores.items()}, "text": r.chunk.text[:SOURCE_TEXT_CHARS],
        }
        for r in result.chunks
    ]


def citations_payload(resp: RAGResponse) -> list[dict[str, Any]]:
    if not resp.citations:
        return []
    return [
        {
            "tag": c.tag, "chunk_id": c.chunk_id, "doc_id": c.doc_id, "source": c.source,
            "page_start": c.page_start, "page_end": c.page_end, "excerpt": c.excerpt,
            "retrieval_score": float(c.retrieval_score), "support": float(c.support), "method": c.method,
        }
        for c in resp.citations.citations
    ]


def message_out(m: Message) -> MessageOut:
    return MessageOut.model_validate(m)


def get_conversation_or_404(db: Session, conversation_id: str, user: User) -> Conversation:
    conv = db.get(Conversation, conversation_id) if len(conversation_id) <= 32 else None
    if conv is None or conv.owner_id != user.id:
        raise APIError(404, "conversation_not_found", "Conversation not found.")
    return conv


def _resolve_scope(db: Session, user: User, requested: list[str] | None, conversation: Conversation | None) -> list[str]:
    ids = requested if requested else (conversation.document_ids if conversation and requested is None else [])
    owned = {d.id: d for d in db.scalars(select(Document).where(Document.owner_id == user.id))}
    ready = {i for i, d in owned.items() if d.status == "ready"}
    if not ready:
        raise APIError(400, "no_documents", "No indexed documents yet. Upload a PDF and wait for it to finish processing.")
    if not ids:
        return sorted(ready)
    missing = [d for d in ids if d not in owned]
    if missing:
        raise APIError(404, "document_not_found", "Some selected documents do not exist.", {"document_ids": missing})
    not_ready = [d for d in ids if d not in ready]
    if not_ready:
        raise APIError(409, "document_not_ready", "Some selected documents are not ready yet.", {"document_ids": not_ready})
    return list(ids)


def prepare(db: Session, manager: EngineManager, req: ChatRequest, user: User) -> PreparedChat:
    conversation = None
    prior_user: Message | None = None
    if req.conversation_id:
        conversation = get_conversation_or_404(db, req.conversation_id, user)
    question = req.message
    if req.regenerate_of:
        if conversation is None:
            raise APIError(400, "bad_request", "regenerate_of requires conversation_id.")
        target = db.get(Message, req.regenerate_of)
        if target is None or target.conversation_id != conversation.id or target.role != "assistant":
            raise APIError(404, "message_not_found", "Message to regenerate not found.")
        msgs = conversation.messages
        idx = msgs.index(target)
        prior_user = next((m for m in reversed(msgs[:idx]) if m.role == "user"), None)
        if prior_user is None:
            raise APIError(400, "bad_request", "Nothing to regenerate.")
        question = prior_user.content
        db.delete(target)
        db.flush()
        db.refresh(conversation)
    scope = _resolve_scope(db, user, req.document_ids, conversation)
    if conversation is None:
        conversation = Conversation(owner_id=user.id, title=question[:80], document_ids=req.document_ids or [])
        db.add(conversation)
        db.flush()
    elif req.document_ids is not None:
        conversation.document_ids = req.document_ids

    # (question, answer) pairs of earlier generated turns, for follow-up questions.
    history: list[tuple[str, str]] = []
    pending_q: str | None = None
    for m in conversation.messages:
        if m.role == "user":
            pending_q = m.content
        elif m.role == "assistant" and pending_q and m.mode == "generated":
            history.append((pending_q, m.content))
            pending_q = None

    if req.regenerate_of:
        assert prior_user is not None
        user_msg = prior_user
        if history and history[-1][0] == question:
            history = history[:-1]
    else:
        user_msg = Message(conversation_id=conversation.id, role="user", content=question, document_ids=scope)
        db.add(user_msg)
    db.commit()

    svc = manager.service
    s = svc.settings
    cfg = svc.retrieval_config(
        top_k=req.top_k, use_rerank=req.use_rerank, use_hybrid=req.use_hybrid, doc_ids=scope,
    )
    params = GenerationParams(
        max_new_tokens=req.max_new_tokens or s.max_new_tokens,
        temperature=s.temperature if req.temperature is None else req.temperature,
        top_p=s.top_p,
    )
    return PreparedChat(conversation.id, user.id, user_msg.id, question, scope, history[-2:], cfg, params)


def finalize(db: Session, manager: EngineManager, prep: PreparedChat, resp: RAGResponse, *, streamed: bool) -> Message:
    msg = Message(
        conversation_id=prep.conversation_id, role="assistant",
        content=resp.answer or ("Retrieved passages are shown in the evidence panel." if resp.mode == "retrieval_only" else ""),
        status=resp.status, mode=resp.mode, document_ids=prep.scope,
        citations=citations_payload(resp), sources=sources_payload(resp.retrieval), notes=list(resp.notes),
        timings_ms={k: round(float(v), 2) for k, v in resp.timings_ms.items()},
    )
    db.add(msg)
    conv = db.get(Conversation, prep.conversation_id)
    if conv is not None:
        conv.updated_at = msg.created_at
    g = resp.generation
    db.add(QueryLog(
        owner_id=prep.owner_id, mode=resp.mode, status=resp.status, streamed=int(streamed), documents_in_scope=len(prep.scope),
        retrieval_ms=resp.timings_ms.get("retrieval"), generation_ms=resp.timings_ms.get("generation"),
        ttft_ms=resp.timings_ms.get("time_to_first_token"), total_ms=resp.timings_ms.get("total"),
        completion_tokens=g.completion_tokens if g else None, llm_model=manager.service.settings.llm_model if g else None,
    ))
    db.commit()
    return msg


def finalize_error(db: Session, prep: PreparedChat, code: str, message: str) -> Message:
    msg = Message(
        conversation_id=prep.conversation_id, role="assistant", content=message, status="error", mode=code,
        document_ids=prep.scope,
    )
    db.add(msg)
    db.commit()
    return msg


def list_conversations(db: Session, user: User, limit: int = 100) -> list[dict[str, Any]]:
    counts = dict(db.execute(
        select(Message.conversation_id, func.count()).join(Conversation)
        .where(Conversation.owner_id == user.id).group_by(Message.conversation_id)
    ).all())
    convs = db.scalars(
        select(Conversation).where(Conversation.owner_id == user.id).order_by(Conversation.updated_at.desc()).limit(limit)
    ).all()
    out = []
    for c in convs:
        last = c.messages[-1].content[:160] if c.messages else None
        out.append({
            "id": c.id, "title": c.title, "document_ids": c.document_ids, "message_count": counts.get(c.id, 0),
            "last_message": last, "created_at": c.created_at, "updated_at": c.updated_at,
        })
    return out
