"""Persistent JSON registry of ingested documents."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class DocumentRecord:
    doc_id: str
    filename: str
    title: str
    sha256: str
    page_count: int
    chunk_count: int
    size_bytes: int
    created_at: str
    chunking: dict[str, object]
    scanned_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


class DocumentRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._docs: dict[str, DocumentRecord] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._docs = {d["doc_id"]: DocumentRecord(**d) for d in raw.get("documents", [])}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"documents": [asdict(d) for d in self._docs.values()]}, indent=2))
        os.replace(tmp, self.path)

    def add(self, record: DocumentRecord) -> None:
        with self._lock:
            self._docs[record.doc_id] = record
            self._save()

    def remove(self, doc_id: str) -> DocumentRecord | None:
        with self._lock:
            record = self._docs.pop(doc_id, None)
            self._save()
            return record

    def get(self, doc_id: str) -> DocumentRecord | None:
        return self._docs.get(doc_id)

    def find_by_hash(self, sha256: str) -> DocumentRecord | None:
        return next((d for d in self._docs.values() if d.sha256 == sha256), None)

    def all(self) -> list[DocumentRecord]:
        return sorted(self._docs.values(), key=lambda d: d.created_at)
