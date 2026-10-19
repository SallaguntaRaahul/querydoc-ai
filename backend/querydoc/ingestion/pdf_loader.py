"""PDF validation and page-level text extraction with PyMuPDF."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from querydoc.exceptions import PasswordProtectedPDFError, PDFValidationError
from querydoc.ingestion.text_cleaning import clean_text
from querydoc.logging_utils import get_logger, kv

log = get_logger(__name__)

PDF_MAGIC = b"%PDF-"
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based, as shown to users
    text: str
    is_empty: bool
    likely_scanned: bool


@dataclass
class ExtractedDocument:
    doc_id: str
    filename: str
    title: str
    sha256: str
    page_count: int
    pages: list[PageText]
    diagnostics: dict[str, object] = field(default_factory=dict)

    @property
    def scanned_pages(self) -> list[int]:
        return [p.page_number for p in self.pages if p.likely_scanned]

    @property
    def empty_pages(self) -> list[int]:
        return [p.page_number for p in self.pages if p.is_empty and not p.likely_scanned]


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Return a display/storage-safe basename: no directories, no traversal,
    no control characters. The result is never used to build a path directly
    (documents are stored by doc_id) but it is shown in the UI and citations."""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\- ()]+", "_", name).strip(" .")
    name = name.lstrip(".")
    if not name:
        name = "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    if len(name) > max_len:
        name = name[: max_len - 4] + ".pdf"
    return name


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doc_id_from_hash(sha256: str) -> str:
    """Stable identifier: identical bytes always yield the same id."""
    return sha256[:16]


def validate_pdf_bytes(data: bytes, *, max_upload_mb: float) -> None:
    if not data:
        raise PDFValidationError("The file is empty.")
    size_mb = len(data) / (1024 * 1024)
    if size_mb > max_upload_mb:
        raise PDFValidationError(f"File is {size_mb:.1f} MB; the limit is {max_upload_mb:.0f} MB.")
    # The header may be preceded by a few junk bytes in real-world files.
    if PDF_MAGIC not in data[:1024]:
        raise PDFValidationError("The file does not look like a PDF (missing %PDF header).")


def _horizontal_text(page: pymupdf.Page) -> str:
    """Page text from horizontal lines only, in reading order.

    Rotated text (vertical margin watermarks, sideways labels) otherwise gets
    interleaved into body sentences by plain extraction."""
    info = page.get_text("dict", sort=True, flags=pymupdf.TEXTFLAGS_TEXT)
    blocks: list[str] = []
    for block in info.get("blocks", []):
        lines = []
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            if abs(dy) > 0.1 or dx <= 0:
                continue
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _open(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several exception types for corrupt input
        raise PDFValidationError(f"The PDF is corrupt or unreadable: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise PasswordProtectedPDFError(
            "The PDF is password-protected. Remove the password and upload it again."
        )
    if doc.page_count == 0:
        doc.close()
        raise PDFValidationError("The PDF has no pages.")
    return doc


def extract_pdf(
    data: bytes,
    filename: str,
    *,
    max_upload_mb: float = 50.0,
    max_pages: int = 1000,
    min_chars_per_page: int = 20,
    enable_ocr: bool = False,
    progress: ProgressCallback | None = None,
) -> ExtractedDocument:
    """Validate ``data`` and extract cleaned text for every page.

    Pages are processed one at a time; only the cleaned text is retained.
    """
    validate_pdf_bytes(data, max_upload_mb=max_upload_mb)
    safe_name = sanitize_filename(filename)
    sha = content_hash(data)
    doc = _open(data)
    try:
        if doc.page_count > max_pages:
            raise PDFValidationError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")
        title = (doc.metadata or {}).get("title") or Path(safe_name).stem
        pages: list[PageText] = []
        ocr_used = 0
        for index in range(doc.page_count):
            page = doc.load_page(index)
            try:
                raw = _horizontal_text(page)
            except Exception as exc:
                log.warning(kv("page_extract_failed", file=safe_name, page=index + 1, error=exc))
                raw = ""
            text = clean_text(raw)
            has_images = bool(page.get_images(full=False))
            likely_scanned = len(text) < min_chars_per_page and has_images
            if likely_scanned and enable_ocr:
                ocr_text = _ocr_page(page)
                if ocr_text:
                    text, likely_scanned = ocr_text, False
                    ocr_used += 1
            pages.append(
                PageText(
                    page_number=index + 1,
                    text=text,
                    is_empty=not text,
                    likely_scanned=likely_scanned,
                )
            )
            if progress:
                progress(index + 1, doc.page_count)
        extracted = ExtractedDocument(
            doc_id=doc_id_from_hash(sha),
            filename=safe_name,
            title=str(title).strip() or Path(safe_name).stem,
            sha256=sha,
            page_count=doc.page_count,
            pages=pages,
        )
        extracted.diagnostics = {
            "chars": sum(len(p.text) for p in pages),
            "empty_pages": extracted.empty_pages,
            "scanned_pages": extracted.scanned_pages,
            "ocr_pages": ocr_used,
            "ocr_enabled": enable_ocr,
        }
        log.info(
            kv(
                "pdf_extracted",
                file=safe_name,
                pages=doc.page_count,
                scanned=len(extracted.scanned_pages),
                empty=len(extracted.empty_pages),
            )
        )
        return extracted
    finally:
        doc.close()


def _ocr_page(page: pymupdf.Page) -> str:
    """Optional OCR through PyMuPDF's Tesseract bridge. Returns '' when unavailable."""
    try:
        textpage = page.get_textpage_ocr(full=True)
        return clean_text(page.get_text("text", textpage=textpage))
    except Exception as exc:  # Tesseract not installed or language data missing
        log.warning(kv("ocr_unavailable", error=exc))
        return ""
