"""API test fixtures: a real FastAPI app (real ingestion, embeddings, FAISS,
SQLite, background worker, SSE) with a deterministic stub LLM so tests are
fast and do not need the 3 GB generation model. The real model is exercised
by tests/e2e/test_generation.py."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app
from app.rag.engine import EngineManager
from querydoc.config import Settings
from querydoc.generation.llm import GenerationParams, GenerationResult
from querydoc.services.rag_service import QueryDocService

ROOT = Path(__file__).resolve().parents[3]


class StubLLM:
    """Answers by quoting the first sentence of source S1 and citing it."""

    device = "cpu"
    revision = "stub"

    def __init__(self, token_delay: float = 0.0) -> None:
        self.token_delay = token_delay
        self.calls = 0

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def iter_generate(
        self, messages: list[dict[str, str]], params: GenerationParams | None = None,
        stop_event: threading.Event | None = None,
    ) -> Generator[str, None, GenerationResult]:
        self.calls += 1
        user = messages[-1]["content"]
        m = re.search(r'<source id="S1"[^>]*>\n(.*?)\n</source>', user, re.S)
        body = " ".join((m.group(1) if m else "").split())
        sentence = re.split(r"(?<=[.!?])\s", body)[0][:300] if body else "INSUFFICIENT_EVIDENCE"
        text = f"{sentence} [S1]" if body else sentence
        started = time.perf_counter()
        out: list[str] = []
        for word in text.split(" "):
            if stop_event is not None and stop_event.is_set():
                break
            if self.token_delay:
                time.sleep(self.token_delay)
            out.append(word)
            yield word + " "
        joined = " ".join(out)
        return GenerationResult(joined, 10, len(out), (time.perf_counter() - started) * 1000, 1.0)

    def generate(self, messages, params=None, stop_event=None) -> GenerationResult:  # type: ignore[no-untyped-def]
        it = self.iter_generate(messages, params, stop_event)
        while True:
            try:
                next(it)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]


def build_client(tmp: Path, embedder, *, llm: StubLLM | None = None, app_overrides: dict | None = None,  # type: ignore[no-untyped-def]
                 **engine_overrides) -> Iterator[TestClient]:
    engine_settings = Settings(data_dir=tmp, use_rerank=False, **engine_overrides)
    service = QueryDocService(engine_settings, embedder=embedder)
    service._llm = llm or StubLLM()  # type: ignore[assignment]
    manager = EngineManager(service=service)
    app_settings = AppSettings(data_dir=tmp, load_models_on_startup=False, max_upload_mb=5,
                               results_dir=ROOT / "results", frontend_dist=tmp / "no-dist", **(app_overrides or {}))
    app = create_app(app_settings, manager)
    with TestClient(app) as client:
        client.manager = manager  # type: ignore[attr-defined]
        yield client


@pytest.fixture()
def client(tmp_path, embedder) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    yield from build_client(tmp_path, embedder)


def wait_ready(client: TestClient, doc_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/api/v1/documents/{doc_id}/status").json()
        if d["status"] in {"ready", "failed"}:
            return d
        time.sleep(0.1)
    raise AssertionError(f"document {doc_id} not processed in time")


def upload(client: TestClient, name: str, data: bytes) -> dict:
    r = client.post("/api/v1/documents/upload", files=[("files", (name, data, "application/pdf"))])
    assert r.status_code == 202, r.text
    doc = r.json()["documents"][0]
    wait_ready(client, doc["id"])
    return client.get(f"/api/v1/documents/{doc['id']}").json()


def sse_events(response) -> list[tuple[str, dict]]:  # type: ignore[no-untyped-def]
    import json

    events, event = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event:
            events.append((event, json.loads(line[6:])))
            event = None
    return events
