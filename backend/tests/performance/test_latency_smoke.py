"""Performance smoke test: warm retrieval on a 120-page document stays under the
300 ms target. This is a regression guard; the authoritative numbers come from
benchmarks/benchmark_retrieval.py (more queries, repeated trials).

The 300 ms target is for the development machine (Apple M3 Pro). Shared CI runners are
slower; CI sets QUERYDOC_LATENCY_BUDGET_MS to keep this a regression guard there."""

import os
import time

import pytest

from tests.conftest import make_settings

pytestmark = pytest.mark.slow


def test_warm_retrieval_p95_under_300ms(tmp_path, embedder, synthetic_120):
    from querydoc.services.rag_service import QueryDocService

    svc = QueryDocService(make_settings(tmp_path, use_rerank=True, use_hybrid=True), embedder=embedder)
    data, facts = synthetic_120
    svc.ingest(data, "manual.pdf")
    cfg = svc.retrieval_config(rerank_k=20)
    questions = [f.question for f in facts]
    for q in questions[:5]:
        svc.retrieve(q, cfg)
    ms = []
    for i in range(60):
        t = time.perf_counter()
        svc.retrieve(questions[i % len(questions)], cfg)
        ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    p95 = ms[int(0.95 * len(ms)) - 1]
    budget = float(os.environ.get("QUERYDOC_LATENCY_BUDGET_MS", "300"))
    assert p95 < budget, f"p95 {p95:.1f} ms (budget {budget:.0f} ms)"
