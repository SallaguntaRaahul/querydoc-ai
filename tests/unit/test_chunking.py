import pytest

from querydoc.chunking.chunkers import ChunkingConfig, chunk_document, chunk_statistics, joined_text
from querydoc.ingestion.pdf_loader import ExtractedDocument, PageText


def make_doc(pages: list[str]) -> ExtractedDocument:
    return ExtractedDocument(
        doc_id="abcdef0123456789",
        filename="t.pdf",
        title="t",
        sha256="0" * 64,
        page_count=len(pages),
        pages=[PageText(i + 1, t, not t, False) for i, t in enumerate(pages)],
    )


SENT = "Access reviews happen every quarter for privileged accounts. "


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "sentence"])
def test_chunks_respect_size_and_offsets(strategy):
    doc = make_doc([SENT * 30, SENT * 30, "", SENT * 30])
    cfg = ChunkingConfig(strategy=strategy, chunk_size=300, chunk_overlap=60, min_chunk_chars=10)
    chunks = chunk_document(doc, cfg)
    text = joined_text(doc)
    assert chunks
    for c in chunks:
        assert len(c.text) <= 300
        # char_start points at the chunk text inside the joined document
        assert text[c.char_start : c.char_start + len(c.text)].strip() == c.text.strip()
        assert 1 <= c.page_start <= c.page_end <= 4


def test_page_ranges_and_cross_page_chunks():
    doc = make_doc(["alpha " * 40, "bravo " * 40, "charlie " * 40])
    chunks = chunk_document(doc, ChunkingConfig(strategy="fixed", chunk_size=300, chunk_overlap=0))
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3
    crossing = [c for c in chunks if c.page_start != c.page_end]
    assert crossing, "a fixed window must straddle a page boundary"
    for c in crossing:
        assert "alpha" in c.text or "bravo" in c.text or "charlie" in c.text
    assert chunk_statistics(chunks)["cross_page"] == len(crossing)


def test_empty_pages_skipped_but_numbering_preserved():
    doc = make_doc(["", "", "only text here " * 10])
    chunks = chunk_document(doc, ChunkingConfig(chunk_size=500, chunk_overlap=0, min_chunk_chars=5))
    assert chunks and all(c.page_start == 3 for c in chunks)


def test_chunk_ids_stable_and_unique():
    doc = make_doc([SENT * 50])
    a = chunk_document(doc, ChunkingConfig(chunk_size=200, chunk_overlap=40))
    b = chunk_document(doc, ChunkingConfig(chunk_size=200, chunk_overlap=40))
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)
    assert a[0].chunk_id.startswith(doc.doc_id)


def test_overlap_repeats_text():
    doc = make_doc(["".join(f"w{i:04d} " for i in range(400))])
    chunks = chunk_document(doc, ChunkingConfig(strategy="fixed", chunk_size=200, chunk_overlap=50))
    assert chunks[0].text[-50:] == chunks[1].text[:50]


def test_min_chunk_chars_drops_fragments():
    doc = make_doc([SENT * 10, "ok"])
    chunks = chunk_document(doc, ChunkingConfig(chunk_size=200, chunk_overlap=0, min_chunk_chars=40))
    assert all(len(c.text) >= 40 for c in chunks)


def test_invalid_config():
    with pytest.raises(ValueError):
        ChunkingConfig(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        ChunkingConfig(strategy="semantic")


def test_langchain_document_roundtrip():
    doc = make_doc([SENT * 5])
    c = chunk_document(doc, ChunkingConfig(chunk_size=500, chunk_overlap=0, min_chunk_chars=5))[0]
    lc = c.to_document()
    assert lc.page_content == c.text
    assert lc.metadata["page_start"] == 1 and lc.metadata["chunk_id"] == c.chunk_id
