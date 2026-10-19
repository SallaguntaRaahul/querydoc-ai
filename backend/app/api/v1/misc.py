"""/api/v1 conversations, analytics, settings and health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AppContext, get_ctx
from app.core.errors import APIError
from app.db.session import get_db
from app.models.entities import Conversation, Document, Message
from app.schemas.api import (
    ConversationDetail,
    ConversationSummary,
    ErrorResponse,
    FeedbackRequest,
    HealthResponse,
    MessageOut,
    SettingsResponse,
    SettingsUpdate,
)
from app.services import analytics as analytics_service
from app.services import chat as chat_service
from app.services import settings as settings_service

VERSION = "1.0.0"

conversations = APIRouter(prefix="/conversations", tags=["conversations"])
analytics = APIRouter(prefix="/analytics", tags=["analytics"])
settings = APIRouter(prefix="/settings", tags=["settings"])
health = APIRouter(tags=["health"])


def _conversation_or_404(db: Session, cid: str) -> Conversation:
    conv = db.get(Conversation, cid) if len(cid) <= 32 else None
    if conv is None:
        raise APIError(404, "conversation_not_found", "Conversation not found.")
    return conv


@conversations.get("", response_model=list[ConversationSummary])
def list_conversations(db: Session = Depends(get_db)) -> list[ConversationSummary]:
    return [ConversationSummary(**c) for c in chat_service.list_conversations(db)]


@conversations.get("/{conversation_id}", response_model=ConversationDetail, responses={404: {"model": ErrorResponse}})
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> ConversationDetail:
    c = _conversation_or_404(db, conversation_id)
    return ConversationDetail(
        id=c.id, title=c.title, document_ids=c.document_ids, created_at=c.created_at, updated_at=c.updated_at,
        messages=[MessageOut.model_validate(m) for m in c.messages],
    )


@conversations.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> None:
    db.delete(_conversation_or_404(db, conversation_id))


@conversations.put("/{conversation_id}/messages/{message_id}/feedback", response_model=MessageOut)
def message_feedback(conversation_id: str, message_id: str, body: FeedbackRequest,
                     db: Session = Depends(get_db)) -> MessageOut:
    msg = db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id or msg.role != "assistant":
        raise APIError(404, "message_not_found", "Message not found.")
    msg.feedback = body.value
    return MessageOut.model_validate(msg)


@analytics.get("/overview", summary="Runtime telemetry recorded by this installation")
def analytics_overview(ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> dict:
    return analytics_service.overview(db, ctx.manager)


@analytics.get("/benchmarks", summary="Benchmark evidence from results/ (not live telemetry)")
def analytics_benchmarks(ctx: AppContext = Depends(get_ctx)) -> dict:
    return analytics_service.benchmarks(ctx.settings.results_dir)


@settings.get("", response_model=SettingsResponse)
def get_settings(ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> SettingsResponse:
    return settings_service.response(db, ctx.manager)


@settings.put("", response_model=SettingsResponse, responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def put_settings(patch: SettingsUpdate, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> SettingsResponse:
    return settings_service.update(db, ctx.manager, patch)


@health.get("/health", response_model=HealthResponse)
def get_health(ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> HealthResponse:
    models = ctx.manager.model_status()
    degraded = bool(models["llm"]["error"])
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=VERSION,
        models=models,
        documents=db.scalar(select(func.count()).select_from(Document)) or 0,
        index_vectors=ctx.manager.service.store.size,
        ingestion_queue=ctx.worker.queue_size,
    )
