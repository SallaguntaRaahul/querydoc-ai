"""Deterministic synthetic PDFs for smoke, scalability and security tests.

These documents are NOT used to make retrieval-quality claims; they exist so
tests and latency/scale benchmarks are reproducible without external data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pymupdf

_TOPICS = [
    "reactor cooling", "supply chain", "billing reconciliation", "network latency", "warehouse safety",
    "customer onboarding", "solar inverter", "payroll audit", "fleet maintenance", "clinical trial logistics",
    "data retention", "vendor risk", "incident escalation", "budget forecasting", "firmware rollout",
]
_WORDS = (
    "system process review policy team quarterly metric control report analysis threshold operator "
    "schedule baseline variance capacity module record approval workflow storage inventory compliance "
    "procedure monitoring estimate dependency allocation exception resource escalation summary"
).split()


@dataclass(frozen=True)
class PlantedFact:
    page: int
    question: str
    answer: str
    sentence: str


def _filler(rng: random.Random, topic: str, n_sentences: int) -> list[str]:
    out = []
    for _ in range(n_sentences):
        words = rng.sample(_WORDS, k=rng.randint(8, 14))
        out.append(f"The {topic} {' '.join(words)}.".capitalize())
    return out


def make_synthetic_pdf(
    pages: int,
    *,
    seed: int = 7,
    facts_every: int = 5,
    blank_pages: tuple[int, ...] = (),
    image_only_pages: tuple[int, ...] = (),
    extra_text: dict[int, str] | None = None,
    title: str = "Synthetic Operations Manual",
) -> tuple[bytes, list[PlantedFact]]:
    """Return (pdf_bytes, planted_facts). Each ``facts_every``-th page carries a
    unique, verifiable fact such as an identification code."""
    rng = random.Random(seed)
    doc = pymupdf.open()
    doc.set_metadata({"title": title, "author": "QueryDoc AI synthetic generator"})
    facts: list[PlantedFact] = []
    extra_text = extra_text or {}
    for p in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        if p in blank_pages:
            continue
        if p in image_only_pages:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), False)
            pix.set_rect(pix.irect, (rng.randrange(256), 120, 200))
            page.insert_image(pymupdf.Rect(50, 50, 545, 545), pixmap=pix)
            continue
        topic = _TOPICS[(p - 1) % len(_TOPICS)]
        lines = [f"Section {p}: {topic.title()}", ""]
        body = _filler(rng, topic, 14)
        if p % facts_every == 0:
            code = f"QD-{rng.randint(1000, 9999)}-{chr(65 + p % 26)}"
            sentence = f"The official tracking code for the {topic} programme in section {p} is {code}."
            body.insert(rng.randint(2, len(body) - 2), sentence)
            facts.append(
                PlantedFact(
                    page=p,
                    question=f"What is the official tracking code for the {topic} programme in section {p}?",
                    answer=code,
                    sentence=sentence,
                )
            )
        lines.append(" ".join(body))
        if p in extra_text:
            lines += ["", extra_text[p]]
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), "\n".join(lines), fontsize=10, fontname="helv")
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data, facts


def make_encrypted_pdf(password: str = "secret") -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Confidential content")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "!")
    doc.close()
    return data


def make_scanned_pdf(lines: list[str], *, pages: int = 1, dpi: int = 150) -> bytes:
    """A PDF whose pages are *images* of text (no text layer), like a scan."""
    src = pymupdf.open()
    for p in range(pages):
        page = src.new_page(width=595, height=842)
        body = "\n".join(lines if p == 0 else [f"{line} (page {p + 1})" for line in lines])
        page.insert_textbox(pymupdf.Rect(60, 60, 535, 780), body, fontsize=13, fontname="helv")
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        dst = out.new_page(width=page.rect.width, height=page.rect.height)
        dst.insert_image(dst.rect, pixmap=pix)
    data = out.tobytes(garbage=3, deflate=True)
    src.close()
    out.close()
    return data
