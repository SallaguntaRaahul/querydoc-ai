"""Pydantic request/response schemas for the v1 REST API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DOC_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ----------------------------------------------------------------- documents
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    title: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: Literal["queued", "processing", "ready", "failed"]
    stage: str
    progress: float
    error: str | None
    chunking: dict[str, Any]
    timings_ms: dict[str, float]
    embedding_stats: dict[str, float]
    scanned_pages: list[int]
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int


class DocumentStatus(BaseModel):
    id: str
    status: str
    stage: str
    progress: float
    error: str | None


class UploadError(BaseModel):
    filename: str
    code: str
    message: str


class UploadResult(BaseModel):
    documents: list[DocumentOut]
    errors: list[UploadError]


# ---------------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=32)
    document_ids: list[str] | None = Field(default=None, description="Scope; omit or [] for all ready documents")
    regenerate_of: str | None = Field(default=None, description="Assistant message id to regenerate")
    top_k: int | None = Field(default=None, ge=1, le=10)
    use_rerank: bool | None = None
    use_hybrid: bool | None = None
    max_new_tokens: int | None = Field(default=None, ge=16, le=1024)
    temperature: float | None = Field(default=None, ge=0.0, le=1.5)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v

    @field_validator("document_ids")
    @classmethod
    def _ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if len(v) > 200:
            raise ValueError("too many documents in scope")
        for d in v:
            if not DOC_ID_RE.match(d):
                raise ValueError(f"invalid document id: {d!r}")
        return list(dict.fromkeys(v))


class CitationOut(BaseModel):
    tag: str
    chunk_id: str
    doc_id: str
    source: str
    page_start: int
    page_end: int
    excerpt: str
    retrieval_score: float
    support: float
    method: str


class SourceOut(BaseModel):
    rank: int
    chunk_id: str
    doc_id: str
    source: str
    page_start: int
    page_end: int
    score: float
    scores: dict[str, float]
    text: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: Literal["user", "assistant"]
    content: str
    status: str | None
    mode: str | None
    document_ids: list[str]
    citations: list[CitationOut]
    sources: list[SourceOut]
    notes: list[str]
    timings_ms: dict[str, float]
    feedback: int | None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    user_message: MessageOut
    message: MessageOut


class ConversationSummary(BaseModel):
    id: str
    title: str
    document_ids: list[str]
    message_count: int
    last_message: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    document_ids: list[str]
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class FeedbackRequest(BaseModel):
    value: Literal[-1, 1] | None


# ------------------------------------------------------------------ settings
Device = Literal["auto", "cpu", "mps", "cuda"]


class SettingsModel(BaseModel):
    embedding_model: str
    llm_model: str
    llm_device: Device
    reranker_device: Device
    chunk_size: int = Field(ge=200, le=2000)
    chunk_overlap: int = Field(ge=0, le=1000)
    top_k: int = Field(ge=1, le=10)
    fetch_k: int = Field(ge=5, le=100)
    use_hybrid: bool
    use_rerank: bool
    rerank_k: int = Field(ge=1, le=100)
    max_new_tokens: int = Field(ge=16, le=1024)
    temperature: float = Field(ge=0.0, le=1.5)
    theme: Literal["dark", "light", "system"]
    performance_mode: Literal["quality", "balanced", "speed"]
    enable_ocr: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> SettingsModel:
        if self.chunk_overlap > self.chunk_size // 2:
            raise ValueError("chunk_overlap must be at most half of chunk_size")
        if self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be >= top_k")
        if self.rerank_k < self.top_k:
            raise ValueError("rerank_k must be >= top_k")
        return self


class SettingsUpdate(BaseModel):
    """Partial update; unspecified fields keep their current values."""

    model_config = ConfigDict(extra="forbid")

    embedding_model: str | None = None
    llm_model: str | None = None
    llm_device: Device | None = None
    reranker_device: Device | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    top_k: int | None = None
    fetch_k: int | None = None
    use_hybrid: bool | None = None
    use_rerank: bool | None = None
    rerank_k: int | None = None
    max_new_tokens: int | None = None
    temperature: float | None = None
    theme: Literal["dark", "light", "system"] | None = None
    performance_mode: Literal["quality", "balanced", "speed"] | None = None
    enable_ocr: bool | None = None


class SettingsOptions(BaseModel):
    embedding_models: list[str]
    llm_models: list[dict[str, Any]]
    devices: list[str]
    embedding_model_locked: bool
    embedding_model_locked_reason: str | None
    ocr_available: bool = False


class SettingsResponse(BaseModel):
    settings: SettingsModel
    options: SettingsOptions
    restart_required: list[str] = []


# -------------------------------------------------------------------- health
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    models: dict[str, Any]
    documents: int
    index_vectors: int
    ingestion_queue: int
