"""Deterministic retrieval-quality evaluation.

Relevance judgement
-------------------
Each question carries one or more *evidence spans* copied verbatim from the
source document. A span is located in the document's joined text (the same
string chunk offsets refer to) with a whitespace-tolerant match. A retrieved
chunk is **relevant** when it belongs to the question's document and its
character range covers at least ``MIN_SPAN_COVERAGE`` (50%) of an evidence
span. This is independent of chunk size, so different chunking strategies are
judged against identical ground truth.

Metrics (all computed on the top-k list, k=5 unless noted)
-----------------------------------------------------------
* Hit@k        - 1 if any relevant chunk is in the top k.
* Precision@k  - relevant chunks in top k / k.
* Recall@k     - distinct evidence spans covered by the top k / number of spans.
* MRR          - 1 / rank of the first relevant chunk (0 if none in top k).
* nDCG@k       - binary-gain DCG / ideal DCG, where the ideal assumes
                 min(k, #relevant chunks that exist in the index) relevant hits.

**Context Relevance** (the project's headline metric, fixed before any
experiment was run) is defined as mean nDCG@5 over the question set: it
rewards placing evidence-bearing passages in the context window and placing
them early.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from querydoc.chunking.chunkers import Chunk

MIN_SPAN_COVERAGE = 0.5
PRIMARY_METRIC = "ndcg@5"


@dataclass(frozen=True)
class EvalQuestion:
    id: int
    doc: str
    question: str
    evidence: tuple[str, ...]
    answer_keywords: tuple[str, ...] = ()

    @property
    def split(self) -> str:
        return "dev" if self.id % 2 == 1 else "test"


@dataclass
class EvalSet:
    questions: list[EvalQuestion]
    unanswerable: list[str] = field(default_factory=list)

    def split(self, name: str | None) -> list[EvalQuestion]:
        if name in (None, "all"):
            return list(self.questions)
        return [q for q in self.questions if q.split == name]


def load_eval_set(path: Path) -> EvalSet:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    qs = [
        EvalQuestion(
            id=int(q["id"]),
            doc=q["doc"],
            question=q["question"],
            evidence=tuple(q["evidence"]),
            answer_keywords=tuple(q.get("answer_keywords", [])),
        )
        for q in raw["questions"]
    ]
    return EvalSet(qs, [u["question"] for u in raw.get("unanswerable", [])])


def locate_spans(text: str, evidence: str) -> list[tuple[int, int]]:
    """All occurrences of ``evidence`` in ``text``, allowing any whitespace between words."""
    words = evidence.split()
    if not words:
        return []
    pattern = r"\s+".join(re.escape(w) for w in words)
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def chunk_covers(chunk: Chunk, span: tuple[int, int]) -> bool:
    c_start, c_end = chunk.char_start, chunk.char_start + len(chunk.text)
    inter = min(c_end, span[1]) - max(c_start, span[0])
    return inter >= MIN_SPAN_COVERAGE * (span[1] - span[0])


@dataclass
class GroundTruth:
    """Located evidence spans per question, for one indexed corpus. ``spans[qid][i]``
    lists every occurrence of evidence string ``i`` (a few phrases recur, e.g. in a glossary)."""

    spans: dict[int, list[list[tuple[int, int]]]]
    doc_ids: dict[int, str]
    missing: list[tuple[int, str]]

    @classmethod
    def build(
        cls, questions: Iterable[EvalQuestion], doc_texts: dict[str, str], filename_to_doc_id: dict[str, str]
    ) -> GroundTruth:
        spans: dict[int, list[list[tuple[int, int]]]] = {}
        doc_ids: dict[int, str] = {}
        missing: list[tuple[int, str]] = []
        for q in questions:
            doc_id = filename_to_doc_id[q.doc]
            doc_ids[q.id] = doc_id
            located = []
            for ev in q.evidence:
                found = locate_spans(doc_texts[doc_id], ev)
                if not found:
                    missing.append((q.id, ev))
                else:
                    located.append(found)
            spans[q.id] = located
        return cls(spans, doc_ids, missing)

    def judge(self, qid: int, chunk: Chunk) -> set[int]:
        """Indices of the evidence spans this chunk covers (empty = not relevant)."""
        if chunk.doc_id != self.doc_ids[qid]:
            return set()
        return {
            i for i, occurrences in enumerate(self.spans[qid]) if any(chunk_covers(chunk, sp) for sp in occurrences)
        }


def score_ranking(
    covered: Sequence[set[int]], n_spans: int, n_relevant_in_index: int, k: int = 5
) -> dict[str, float]:
    top = list(covered[:k])
    rel = [1 if c else 0 for c in top]
    hit = 1.0 if any(rel) else 0.0
    first = next((i for i, r in enumerate(rel) if r), None)
    spans_hit = set().union(*top) if top else set()
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
    ideal_n = min(k, max(n_relevant_in_index, 1))
    idcg = sum(1 / math.log2(i + 2) for i in range(ideal_n))
    return {
        f"hit@{k}": hit,
        f"precision@{k}": sum(rel) / k,
        f"recall@{k}": len(spans_hit) / n_spans if n_spans else 0.0,
        "mrr": 1.0 / (first + 1) if first is not None else 0.0,
        f"ndcg@{k}": dcg / idcg if idcg else 0.0,
    }


def aggregate(rows: Sequence[dict[str, float]], keys: Sequence[str]) -> dict[str, float]:
    if not rows:
        return {k: 0.0 for k in keys}
    return {k: sum(r[k] for r in rows) / len(rows) for k in keys}


def relative_improvement(baseline: float, optimized: float) -> float:
    """((optimized - baseline) / baseline) * 100; inf when the baseline is 0."""
    if baseline == 0:
        return math.inf if optimized > 0 else 0.0
    return (optimized - baseline) / baseline * 100.0


def bootstrap_ci(
    baseline: Sequence[float], optimized: Sequence[float], *, iters: int = 5000, seed: int = 13
) -> tuple[float, float]:
    """95% paired-bootstrap CI for the relative improvement of the mean."""
    import random

    rng = random.Random(seed)
    n = len(baseline)
    stats = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        b = sum(baseline[i] for i in idx) / n
        o = sum(optimized[i] for i in idx) / n
        if b > 0:
            stats.append((o - b) / b * 100)
    stats.sort()
    if not stats:
        return (math.nan, math.nan)
    return (stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1])
