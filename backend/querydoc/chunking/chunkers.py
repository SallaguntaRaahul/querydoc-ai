"""Metadata-preserving chunking strategies.

Pages are concatenated into a single string with an offset table, so a chunk can
span a page boundary while still reporting the exact page range it came from.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from querydoc.ingestion.pdf_loader import ExtractedDocument

PAGE_JOINER = "\n\n"
DEFAULT_SEPARATORS: list[str] = ["\n\n", ". ", "? ", "! ", "\n", "; ", ", ", " ", ""]
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "recursive"  # fixed | recursive | sentence
    chunk_size: int = 500
    chunk_overlap: int = 100
    min_chunk_chars: int = 40
    separators: tuple[str, ...] = tuple(DEFAULT_SEPARATORS)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        if self.strategy not in {"fixed", "recursive", "sentence"}:
            raise ValueError(f"unknown chunking strategy: {self.strategy}")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    text: str
    page_start: int
    page_end: int
    chunk_index: int
    char_start: int

    @property
    def pages_label(self) -> str:
        if self.page_start == self.page_end:
            return f"p. {self.page_start}"
        return f"pp. {self.page_start}-{self.page_end}"

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Chunk:
        return cls(**data)

    def to_document(self) -> Document:
        meta = self.to_dict()
        text = meta.pop("text")
        return Document(page_content=text, metadata=meta)


class _PageOffsets:
    """Maps character offsets in the joined text back to 1-based page numbers."""

    def __init__(self, doc: ExtractedDocument) -> None:
        self.starts: list[int] = []
        self.page_numbers: list[int] = []
        parts: list[str] = []
        cursor = 0
        for page in doc.pages:
            if not page.text:
                continue
            if parts:
                parts.append(PAGE_JOINER)
                cursor += len(PAGE_JOINER)
            self.starts.append(cursor)
            self.page_numbers.append(page.page_number)
            parts.append(page.text)
            cursor += len(page.text)
        self.text = "".join(parts)

    def page_at(self, offset: int) -> int:
        idx = bisect.bisect_right(self.starts, offset) - 1
        return self.page_numbers[max(idx, 0)]


def joined_text(doc: ExtractedDocument) -> str:
    """The exact string chunk ``char_start`` offsets refer to."""
    return _PageOffsets(doc).text


def _fixed_spans(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    step = size - overlap
    spans = []
    for start in range(0, len(text), step):
        piece = text[start : start + size]
        spans.append((start, piece))
        if start + size >= len(text):
            break
    return spans


def _recursive_spans(text: str, cfg: ChunkingConfig) -> list[tuple[int, str]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
        separators=list(cfg.separators),
        keep_separator="end",
        add_start_index=True,
        strip_whitespace=True,
    )
    docs = splitter.create_documents([text])
    return [(int(d.metadata["start_index"]), d.page_content) for d in docs]


def _sentence_spans(text: str, cfg: ChunkingConfig) -> list[tuple[int, str]]:
    """Pack whole sentences up to ``chunk_size``; overlap is whole trailing sentences."""
    sentences: list[tuple[int, int]] = []
    pos = 0
    for match in _SENTENCE_RE.finditer(text):
        if match.start() > pos:
            sentences.append((pos, match.start()))
        pos = match.end()
    if pos < len(text):
        sentences.append((pos, len(text)))

    # Hard-split sentences longer than the chunk size.
    units: list[tuple[int, int]] = []
    for s, e in sentences:
        while e - s > cfg.chunk_size:
            units.append((s, s + cfg.chunk_size))
            s += cfg.chunk_size
        if e > s:
            units.append((s, e))

    spans: list[tuple[int, str]] = []
    i = 0
    while i < len(units):
        start = units[i][0]
        j = i
        while j + 1 < len(units) and units[j + 1][1] - start <= cfg.chunk_size:
            j += 1
        end = units[j][1]
        spans.append((start, text[start:end].strip()))
        if j + 1 >= len(units):
            break
        # Step back over trailing sentences that fit inside the overlap budget.
        k = j + 1
        while k - 1 > i and end - units[k - 1][0] <= cfg.chunk_overlap:
            k -= 1
        i = k
    return spans


def chunk_document(doc: ExtractedDocument, cfg: ChunkingConfig | None = None) -> list[Chunk]:
    cfg = cfg or ChunkingConfig()
    offsets = _PageOffsets(doc)
    text = offsets.text
    if not text:
        return []
    if cfg.strategy == "fixed":
        spans = _fixed_spans(text, cfg.chunk_size, cfg.chunk_overlap)
    elif cfg.strategy == "sentence":
        spans = _sentence_spans(text, cfg)
    else:
        spans = _recursive_spans(text, cfg)

    kept = [(s, t) for s, t in spans if len(t.strip()) >= cfg.min_chunk_chars]
    if not kept and spans:  # very short document: keep what exists
        kept = [(s, t) for s, t in spans if t.strip()]

    chunks: list[Chunk] = []
    for index, (start, piece) in enumerate(kept):
        end = start + max(len(piece) - 1, 0)
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}-{index:05d}",
                doc_id=doc.doc_id,
                source=doc.filename,
                text=piece,
                page_start=offsets.page_at(start),
                page_end=offsets.page_at(end),
                chunk_index=index,
                char_start=start,
            )
        )
    return chunks


def chunk_statistics(chunks: Sequence[Chunk]) -> dict[str, float]:
    if not chunks:
        return {"count": 0, "mean_chars": 0.0, "max_chars": 0, "cross_page": 0}
    lengths = [len(c.text) for c in chunks]
    return {
        "count": len(chunks),
        "mean_chars": sum(lengths) / len(lengths),
        "max_chars": max(lengths),
        "cross_page": sum(1 for c in chunks if c.page_end != c.page_start),
    }
