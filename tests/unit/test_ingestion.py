import pymupdf
import pytest

from querydoc.evaluation.synthetic import make_encrypted_pdf, make_synthetic_pdf
from querydoc.exceptions import PasswordProtectedPDFError, PDFValidationError
from querydoc.ingestion.pdf_loader import doc_id_from_hash, extract_pdf, sanitize_filename
from querydoc.ingestion.text_cleaning import clean_text


def test_clean_text_normalizes_unicode_and_whitespace():
    raw = "Re­silient   sys-\ntems’ “quoted”\x07\n\n\n\nnext para"
    assert clean_text(raw) == "Resilient systems' \"quoted\"\n\nnext para"


def test_clean_text_reflows_soft_wraps_but_keeps_structure():
    raw = "The tracking code for the programme in\nsection 20 is QD-1.\nNext Sentence starts here.\n- bullet item\n\nNew para"
    assert clean_text(raw) == (
        "The tracking code for the programme in section 20 is QD-1.\nNext Sentence starts here.\n- bullet item\n\nNew para"
    )


def test_clean_text_empty():
    assert clean_text("") == ""


@pytest.mark.parametrize(
    "name,expected",
    [
        ("../../etc/passwd", "passwd.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("report<script>.pdf", "report_script_.pdf"),
        ("", "document.pdf"),
        (".hidden.pdf", "hidden.pdf"),
        ("a\x00b.pdf", "ab.pdf"),
    ],
)
def test_sanitize_filename_blocks_traversal_and_control_chars(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_filename_truncates():
    assert len(sanitize_filename("x" * 500 + ".pdf")) <= 120


def test_rejects_non_pdf_bytes():
    with pytest.raises(PDFValidationError, match="does not look like a PDF"):
        extract_pdf(b"hello world, not a pdf", "fake.pdf")


def test_rejects_empty_file():
    with pytest.raises(PDFValidationError, match="empty"):
        extract_pdf(b"", "empty.pdf")


def test_rejects_corrupt_pdf():
    with pytest.raises(PDFValidationError):
        extract_pdf(b"%PDF-1.7\n" + b"\x00garbage" * 50, "corrupt.pdf")


def test_rejects_oversized_upload():
    data, _ = make_synthetic_pdf(3)
    with pytest.raises(PDFValidationError, match="limit"):
        extract_pdf(data, "big.pdf", max_upload_mb=len(data) / (1024 * 1024) / 2)


def test_rejects_too_many_pages():
    data, _ = make_synthetic_pdf(12)
    with pytest.raises(PDFValidationError, match="pages"):
        extract_pdf(data, "long.pdf", max_pages=10)


def test_password_protected_pdf_gives_clear_error():
    with pytest.raises(PasswordProtectedPDFError, match="password"):
        extract_pdf(make_encrypted_pdf(), "locked.pdf")


def test_blank_and_image_only_pages_are_flagged():
    data, _ = make_synthetic_pdf(6, blank_pages=(2,), image_only_pages=(4,))
    doc = extract_pdf(data, "mixed.pdf")
    assert doc.page_count == 6
    assert doc.empty_pages == [2]
    assert doc.scanned_pages == [4]
    assert doc.pages[0].text and not doc.pages[0].is_empty


def test_large_document_preserves_page_numbers(synthetic_120):
    data, facts = synthetic_120
    calls = []
    doc = extract_pdf(data, "manual.pdf", progress=lambda i, n: calls.append((i, n)))
    assert doc.page_count == 120
    assert calls[-1] == (120, 120)
    fact = facts[5]
    assert fact.answer in doc.pages[fact.page - 1].text


def test_doc_id_is_stable_content_hash():
    data, _ = make_synthetic_pdf(2)
    a = extract_pdf(data, "a.pdf")
    b = extract_pdf(data, "renamed.pdf")
    assert a.doc_id == b.doc_id == doc_id_from_hash(a.sha256)


def test_rotated_margin_text_is_excluded():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Body sentence about controls.", fontsize=11)
    page.insert_text((20, 700), "WATERMARK SIDEBAR", fontsize=9, rotate=90)
    data = doc.tobytes()
    extracted = extract_pdf(data, "rot.pdf")
    assert "Body sentence" in extracted.pages[0].text
    assert "WATERMARK" not in extracted.pages[0].text
