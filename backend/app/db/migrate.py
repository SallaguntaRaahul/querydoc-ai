"""Run Alembic migrations programmatically at application start-up."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def upgrade_to_head(database_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["skip_logging_config"] = True  # keep the app's JSON logging
    command.upgrade(cfg, "head")
