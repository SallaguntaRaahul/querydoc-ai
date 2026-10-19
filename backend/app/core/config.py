"""Application (HTTP layer) configuration. RAG-engine settings live in
``querydoc.config.Settings``; both read ``QUERYDOC_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from querydoc.config import PROJECT_ROOT


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUERYDOC_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=PROJECT_ROOT / "data" / "workspace")
    database_url: str | None = None  # default: sqlite file inside data_dir
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    max_upload_mb: float = 50.0
    request_timeout_s: float = 60.0  # non-streaming endpoints
    stream_timeout_s: float = 300.0  # whole streamed answer
    ingestion_workers: int = 1
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    results_dir: Path = PROJECT_ROOT / "results"
    load_models_on_startup: bool = True

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'querydoc.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
