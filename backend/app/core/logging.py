"""Structured JSON logging for the API process."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_querydoc_json", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("QUERYDOC_LOG_LEVEL", "INFO").upper())
    for noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "faiss.loader", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._querydoc_json = True  # type: ignore[attr-defined]


def log_event(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"fields": fields})
