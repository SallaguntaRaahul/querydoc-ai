"""Render a PDF page as an image with the cited excerpt highlighted."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def render_page(pdf_path: Path, page_number: int, highlight: str | None = None, zoom: float = 1.6) -> bytes:
    """Return PNG bytes of ``page_number`` (1-based). The highlight is applied to
    an in-memory copy; the stored PDF is never modified."""
    with pymupdf.open(pdf_path) as doc:
        page = doc.load_page(max(0, min(page_number - 1, doc.page_count - 1)))
        if highlight:
            needle = " ".join(highlight.replace("…", "").split()[:12])
            for quad in page.search_for(needle, quads=True)[:5] if needle else []:
                page.add_highlight_annot(quad)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        return pix.tobytes("png")
