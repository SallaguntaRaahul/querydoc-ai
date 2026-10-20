"""Application (HTTP layer) configuration. RAG-engine settings live in
``querydoc.config.Settings``; both read ``QUERYDOC_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    # Accounts. Off = local single-user mode (everything belongs to the built-in local user).
    auth_enabled: bool = False
    signup_enabled: bool = True
    admin_emails: list[str] = []  # these accounts may change engine settings
    session_days: int = 14
    cookie_secure: bool = False  # True behind HTTPS (required for SameSite=None)
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"  # "none" when served inside an iframe
    # Per-user limits (only enforced when auth is enabled)
    max_documents_per_user: int = 20
    max_storage_mb_per_user: float = 200.0
    chat_per_minute: int = 10
    signups_per_hour_per_ip: int = 5
    logins_per_minute_per_ip: int = 10

    # Mirror the workspace to a private Hugging Face dataset (hosts with an ephemeral disk).
    # Needs HF_TOKEN with write access in the environment.
    hf_backup_repo: str | None = None
    hf_backup_interval_s: float = 120.0

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'querydoc.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
