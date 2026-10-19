"""Citation parsing and verification.

The LLM cites sources as ``[S1]``-style tags. This module maps tags back to the
retrieved chunks, discards tags that do not correspond to a retrieved chunk of
an allowed document, picks a supporting excerpt for each citation and scores
lexical support so unsupported claims are flagged rather than silently shown.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from querydoc.chunking.chunkers import Chunk
from querydoc.generation.prompts import INSUFFICIENT_TOKEN
from querydoc.retrieval.retriever import RetrievedChunk, tokenize

# Accepts [S1], [S1, S3], [S2][S4] and the "[Source S2]" / "[Sources S1, S2]" variants small
# models produce. Bare numbers such as "[26]" are not accepted: they are not our tags.
_TAG_GROUP_RE = re.compile(
    r"\[\s*(?:sources?\s*:?\s*)?(S\s*\d+(?:\s*(?:[,;]|and)\s*S?\s*\d+)*)\s*\]", re.IGNORECASE
)
_NUM_RE = re.compile(r"\d+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
SUPPORT_THRESHOLD = 0.5

STATUS_VERIFIED = "verified"
STATUS_PARTIAL = "partially_verified"
STATUS_UNVERIFIED = "unverified"
STATUS_INSUFFICIENT = "insufficient_evidence"


@dataclass
class Citation:
    tag: str
    chunk_id: str
    doc_id: str
    source: str
    page_start: int
    page_end: int
    excerpt: str
    retrieval_score: float
    support: float  # fraction of the claim's content words found in the chunk
    method: str = "model"  # "model": tag written by the LLM; "attributed": added by post-hoc alignment

    @property
    def pages_label(self) -> str:
        return f"p. {self.page_start}" if self.page_start == self.page_end else f"pp. {self.page_start}-{self.page_end}"


@dataclass
class ClaimCheck:
    sentence: str
    tags: list[str]
    support: float
    supported: bool


@dataclass
class CitationReport:
    answer: str  # answer text with invalid tags removed
    citations: list[Citation]
    claims: list[ClaimCheck]
    invalid_tags: list[str]
    status: str
    notes: list[str] = field(default_factory=list)


def _tags_in(text: str) -> list[str]:
    tags: list[str] = []
    for group in _TAG_GROUP_RE.findall(text):
        for num in _NUM_RE.findall(group):
            tag = f"S{int(num)}"
            if tag not in tags:
                tags.append(tag)
    return tags


def _support(claim: str, chunk_text: str) -> float:
    claim_tokens = set(tokenize(_TAG_GROUP_RE.sub(" ", claim)))
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & set(tokenize(chunk_text))) / len(claim_tokens)


def best_excerpt(chunk_text: str, claim: str, max_chars: int = 320) -> str:
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(chunk_text.replace("\n", " ")) if s.strip()]
    if not sentences:
        return chunk_text[:max_chars]
    claim_tokens = set(tokenize(claim))
    best = max(sentences, key=lambda s: len(claim_tokens & set(tokenize(s))))
    return best if len(best) <= max_chars else best[: max_chars - 1] + "…"


def verify_answer(
    answer: str,
    sources: Sequence[RetrievedChunk],
    *,
    allowed_doc_ids: set[str] | None = None,
    chunk_lookup: Callable[[str], Chunk | None] | None = None,
    attribute_untagged: bool = True,
) -> CitationReport:
    text = answer.strip()
    if not text or INSUFFICIENT_TOKEN in text.upper().replace(" ", "_"):
        return CitationReport("", [], [], [], STATUS_INSUFFICIENT)

    tag_to_source: dict[str, RetrievedChunk] = {}
    for i, item in enumerate(sources):
        c = item.chunk
        if allowed_doc_ids is not None and c.doc_id not in allowed_doc_ids:
            continue
        if chunk_lookup is not None:
            stored = chunk_lookup(c.chunk_id)
            if stored is None or stored.doc_id != c.doc_id or stored.text != c.text:
                continue
        tag_to_source[f"S{i + 1}"] = item

    invalid = [t for t in _tags_in(text) if t not in tag_to_source]

    def _strip_invalid(match: re.Match[str]) -> str:
        valid = [f"S{int(n)}" for n in _NUM_RE.findall(match.group(1))]
        valid = [t for t in valid if t in tag_to_source]
        return "".join(f"[{t}]" for t in valid)

    cleaned = _TAG_GROUP_RE.sub(_strip_invalid, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    # Split into sentences; a fragment that is only citation tags (e.g. "... is X. [S1]")
    # belongs to the preceding sentence.
    sentences: list[str] = []
    for frag in (f.strip() for f in _SENT_SPLIT_RE.split(cleaned)):
        if not frag:
            continue
        if sentences and not tokenize(_TAG_GROUP_RE.sub(" ", frag)):
            sentences[-1] = f"{sentences[-1]} {frag}"
        else:
            sentences.append(frag)

    claims: list[ClaimCheck] = []
    best_for_tag: dict[str, tuple[float, str]] = {}
    attributed: set[str] = set()
    for sentence in sentences:
        if not tokenize(_TAG_GROUP_RE.sub(" ", sentence)):
            continue  # nothing but tags/punctuation: not a claim
        tags = _tags_in(sentence)
        if not tags and attribute_untagged and tag_to_source:
            # Post-hoc alignment: cite the retrieved source that best supports the sentence,
            # but only when that support clears the same threshold used for verification.
            best_tag, best_support = max(
                ((t, _support(sentence, item.chunk.text)) for t, item in tag_to_source.items()),
                key=lambda x: x[1],
            )
            if best_support >= SUPPORT_THRESHOLD:
                tags = [best_tag]
                if best_tag not in best_for_tag:
                    attributed.add(best_tag)
        per_tag = {t: _support(sentence, tag_to_source[t].chunk.text) for t in tags}
        support = max(per_tag.values(), default=0.0)
        claims.append(ClaimCheck(sentence, tags, support, bool(tags) and support >= SUPPORT_THRESHOLD))
        for t, s in per_tag.items():
            if t not in best_for_tag or s > best_for_tag[t][0]:
                best_for_tag[t] = (s, sentence)

    if not claims:
        return CitationReport(
            cleaned, [], [], invalid, STATUS_UNVERIFIED,
            ["The model returned no substantive answer text, only citation markers."],
        )

    citations: list[Citation] = []
    for tag in sorted(best_for_tag, key=lambda t: int(t[1:])):
        item = tag_to_source[tag]
        s, sentence = best_for_tag[tag]
        c = item.chunk
        citations.append(
            Citation(
                tag=tag,
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                source=c.source,
                page_start=c.page_start,
                page_end=c.page_end,
                excerpt=best_excerpt(c.text, sentence),
                retrieval_score=item.score,
                support=s,
                method="attributed" if tag in attributed else "model",
            )
        )

    notes: list[str] = []
    if invalid:
        notes.append(f"Removed citations to non-existent sources: {', '.join(invalid)}.")
    if attributed:
        notes.append(
            f"Citation(s) {', '.join(sorted(attributed, key=lambda t: int(t[1:])))} were attached by "
            "post-hoc alignment (the model did not tag those sentences)."
        )
    supported = sum(1 for c in claims if c.supported)
    if not citations:
        status = STATUS_UNVERIFIED
        notes.append("The model did not cite any retrieved source, so this answer could not be verified.")
    elif supported == len(claims):
        status = STATUS_VERIFIED
    else:
        status = STATUS_PARTIAL
        notes.append(f"{len(claims) - supported} of {len(claims)} sentences lack a well-supported citation.")
    return CitationReport(cleaned, citations, claims, invalid, status, notes)
