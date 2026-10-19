"""Structured (key=value) logging setup."""

from __future__ import annotations

import logging
import os
from typing import Any

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=(level or os.environ.get("QUERYDOC_LOG_LEVEL", "INFO")).upper(),
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )
    for noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "faiss.loader"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def kv(event: str, **fields: Any) -> str:
    """Render an event with key=value fields, e.g. ``kv('ingest', pages=10)``."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        if isinstance(value, float):
            value = f"{value:.4f}"
        parts.append(f"{key}={value}")
    return " ".join(parts)
