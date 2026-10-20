"""Durable state for hosts with an ephemeral disk (e.g. free Hugging Face Spaces).

On start-up the workspace is restored from a private Hugging Face dataset; while
running, a consistent snapshot (SQLite online backup + FAISS index + document
registry + stored PDFs) is mirrored to that dataset whenever something changed.
Unchanged files are not re-uploaded (the Hub de-duplicates by content hash).

If the restore fails, backups are disabled for that run so an empty workspace
can never overwrite good remote data.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from pathlib import Path

from app.rag.engine import EngineManager

log = logging.getLogger("querydoc.api.backup")
DB_NAME = "querydoc.db"
# Rebuildable or transient: never backed up.
SKIP = {"uploads", "embedding_cache", ".backup-staging", ".cache"}


class HubBackup:
    def __init__(self, repo_id: str, data_dir: Path, interval_s: float = 120.0, token: str | None = None) -> None:
        self.repo_id = repo_id
        self.data_dir = data_dir
        self.interval_s = interval_s
        self.token = token
        self.enabled = False
        self._manager: EngineManager | None = None
        self._last_signature: tuple | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- restore
    def restore(self) -> None:
        """Download the latest snapshot into an empty workspace. Must run before migrations."""
        from huggingface_hub import HfApi, snapshot_download

        try:
            api = HfApi(token=self.token)
            api.create_repo(self.repo_id, repo_type="dataset", private=True, exist_ok=True)
            if not (self.data_dir / DB_NAME).exists():
                snapshot_download(self.repo_id, repo_type="dataset", local_dir=self.data_dir, token=self.token)
                log.info("workspace restored", extra={"fields": {"repo": self.repo_id}})
            self.enabled = True
        except Exception:
            log.exception("restore failed; backups disabled for this run to protect remote data")
            self.enabled = False

    # -------------------------------------------------------------- backup
    def start(self, manager: EngineManager) -> None:
        if not self.enabled:
            return
        self._manager = manager
        self._last_signature = self._signature()  # just restored: nothing new to upload
        self._thread = threading.Thread(target=self._loop, name="hub-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.enabled:
            self.backup_now()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.backup_now()

    def _signature(self) -> tuple:
        out = []
        for p in sorted(self.data_dir.rglob("*")):
            rel = p.relative_to(self.data_dir)
            if rel.parts[0] in SKIP or not p.is_file():
                continue
            st = p.stat()
            out.append((str(rel), st.st_size, st.st_mtime_ns))
        return tuple(out)

    def backup_now(self) -> bool:
        """Upload a snapshot if anything changed. Returns True when an upload happened."""
        if not self.enabled or self._manager is None:
            return False
        with self._lock:
            signature = self._signature()
            if signature == self._last_signature:
                return False
            staging = self.data_dir / ".backup-staging"
            try:
                self._snapshot(staging)
                from huggingface_hub import HfApi

                HfApi(token=self.token).upload_folder(
                    repo_id=self.repo_id, repo_type="dataset", folder_path=staging,
                    commit_message="QueryDoc AI workspace snapshot", delete_patterns="*",
                )
                self._last_signature = signature
                log.info("workspace backed up", extra={"fields": {"repo": self.repo_id, "files": len(signature)}})
                return True
            except Exception:
                log.exception("backup failed; will retry")
                return False
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _snapshot(self, staging: Path) -> None:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        assert self._manager is not None
        svc = self._manager.service
        # The engine lock keeps the FAISS index, registry and PDFs mutually consistent.
        with svc._ingest_lock:
            for p in self.data_dir.iterdir():
                if p.name in SKIP or p.name.startswith(DB_NAME):
                    continue
                if p.is_dir():
                    shutil.copytree(p, staging / p.name)
                else:
                    shutil.copy2(p, staging / p.name)
        # SQLite's online backup API gives a consistent copy even while the app writes.
        src = sqlite3.connect(self.data_dir / DB_NAME)
        dst = sqlite3.connect(staging / DB_NAME)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
