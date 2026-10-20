"""Workspace backup to a (fake) Hugging Face dataset: a fresh container with an
empty disk restores accounts, documents and the vector index."""

from __future__ import annotations

import shutil
from pathlib import Path

import huggingface_hub
import pytest

from app.services.backup import HubBackup
from querydoc.evaluation.synthetic import make_synthetic_pdf
from tests.api.conftest import build_client, upload

API = "/api/v1"
PW = "correct horse battery"


class FakeHub:
    """Stands in for HfApi/snapshot_download: the 'dataset' is a local folder."""

    def __init__(self, remote: Path, fail_download: bool = False) -> None:
        self.remote = remote
        self.fail_download = fail_download
        self.uploads = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hub = self

        class Api:
            def __init__(self, token: str | None = None) -> None:
                pass

            def create_repo(self, repo_id: str, **_: object) -> None:
                hub.remote.mkdir(parents=True, exist_ok=True)

            def upload_folder(self, *, folder_path: Path, delete_patterns: str, **_: object) -> None:
                assert delete_patterns == "*"  # mirror: files deleted locally disappear remotely
                shutil.rmtree(hub.remote, ignore_errors=True)
                shutil.copytree(folder_path, hub.remote)
                hub.uploads += 1

        def snapshot_download(repo_id: str, *, local_dir: Path, **_: object) -> str:
            if hub.fail_download:
                raise OSError("network down")
            shutil.copytree(hub.remote, local_dir, dirs_exist_ok=True)
            return str(local_dir)

        monkeypatch.setattr(huggingface_hub, "HfApi", Api)
        monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)


def _client(path: Path, embedder):  # type: ignore[no-untyped-def]
    return build_client(path, embedder, app_overrides={
        "auth_enabled": True, "hf_backup_repo": "someone/querydoc-data", "hf_backup_interval_s": 3600})


def test_fresh_disk_restores_accounts_documents_and_index(tmp_path, embedder, monkeypatch):
    hub = FakeHub(tmp_path / "remote")
    hub.install(monkeypatch)
    pdf, facts = make_synthetic_pdf(12, seed=61)

    gen = _client(tmp_path / "disk1", embedder)
    c = next(gen)
    c.post(f"{API}/auth/signup", json={"email": "keep@example.com", "password": PW})
    doc = upload(c, "keep.pdf", pdf)
    backup = c.app.state.backup  # type: ignore[attr-defined]
    assert backup.backup_now() is True
    assert backup.backup_now() is False  # nothing changed: no upload
    gen.close()  # shutdown also attempts a final snapshot
    assert (hub.remote / "querydoc.db").exists() and not (hub.remote / "uploads").exists()

    # New container, empty disk. In production the app restores before it builds the engine;
    # the test harness builds its engine eagerly, so restore first to keep that order.
    HubBackup("someone/querydoc-data", tmp_path / "disk2").restore()
    gen = _client(tmp_path / "disk2", embedder)
    c = next(gen)
    try:
        assert c.post(f"{API}/auth/login", json={"email": "keep@example.com", "password": PW}).status_code == 200
        assert [d["id"] for d in c.get(f"{API}/documents").json()["items"]] == [doc["id"]]
        answer = c.post(f"{API}/chat", json={"message": facts[0].question}).json()["message"]
        assert answer["sources"] and answer["sources"][0]["doc_id"] == doc["id"]
        assert c.get(f"{API}/documents/{doc['id']}/file").status_code == 200
    finally:
        gen.close()


def test_failed_restore_never_overwrites_remote_data(tmp_path, embedder, monkeypatch):
    hub = FakeHub(tmp_path / "remote", fail_download=True)
    hub.install(monkeypatch)
    (hub.remote).mkdir()
    (hub.remote / "querydoc.db").write_bytes(b"precious")
    gen = _client(tmp_path / "disk", embedder)
    c = next(gen)
    try:
        c.post(f"{API}/auth/signup", json={"email": "x@example.com", "password": PW})
        backup = c.app.state.backup  # type: ignore[attr-defined]
        assert backup.enabled is False and backup.backup_now() is False
    finally:
        gen.close()
    assert (hub.remote / "querydoc.db").read_bytes() == b"precious" and hub.uploads == 0
