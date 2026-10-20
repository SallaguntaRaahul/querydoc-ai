"""Validated, persisted runtime settings."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models.entities import Document, SettingKV
from app.rag.engine import (
    EMBEDDING_OPTIONS,
    LLM_OPTIONS,
    PERFORMANCE_PRESETS,
    EngineManager,
    available_devices,
)
from app.schemas.api import SettingsModel, SettingsOptions, SettingsResponse, SettingsUpdate
from querydoc.ingestion.pdf_loader import ocr_available


def _documents_exist(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Document)))


def response(db: Session, manager: EngineManager, notes: list[str] | None = None, *, can_edit: bool = True) -> SettingsResponse:
    locked = _documents_exist(db) or manager.service.store.size > 0
    return SettingsResponse(
        settings=SettingsModel(**manager.current()),
        options=SettingsOptions(
            embedding_models=EMBEDDING_OPTIONS,
            llm_models=LLM_OPTIONS,
            devices=available_devices(),
            embedding_model_locked=locked,
            ocr_available=ocr_available(),
            can_edit=can_edit,
            embedding_model_locked_reason=(
                "Delete all documents to change the embedding model (existing vectors would be incompatible)."
                if locked else None
            ),
        ),
        restart_required=notes or [],
    )


def update(db: Session, manager: EngineManager, patch: SettingsUpdate) -> SettingsResponse:
    changes: dict[str, Any] = patch.model_dump(exclude_none=True)
    if "performance_mode" in changes:
        for k, v in PERFORMANCE_PRESETS[changes["performance_mode"]].items():
            changes.setdefault(k, v)
    merged = {**manager.current(), **changes}
    try:
        validated = SettingsModel(**merged)
    except ValidationError as exc:
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise APIError(422, "invalid_settings", "Settings are invalid or inconsistent.", details) from exc
    try:
        notes = manager.apply(validated.model_dump(), documents_exist=_documents_exist(db))
    except ValueError as exc:
        raise APIError(409, "incompatible_settings", str(exc)) from exc
    for key, value in validated.model_dump().items():
        row = db.get(SettingKV, key)
        if row is None:
            db.add(SettingKV(key=key, value=value))
        else:
            row.value = value
    return response(db, manager, notes)


def load_persisted(db: Session, manager: EngineManager) -> None:
    """Apply settings saved by a previous run (invalid/stale values are skipped)."""
    stored = {r.key: r.value for r in db.scalars(select(SettingKV))}
    if not stored:
        return
    merged = {**manager.current(), **{k: v for k, v in stored.items() if k in manager.current()}}
    try:
        validated = SettingsModel(**merged)
        manager.apply(validated.model_dump(), documents_exist=_documents_exist(db))
    except (ValidationError, ValueError):
        pass
