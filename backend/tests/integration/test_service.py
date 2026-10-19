import concurrent.futures as cf

import pytest

from querydoc.evaluation.synthetic import make_synthetic_pdf
from querydoc.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    PDFValidationError,
    QueryDocError,
)
from querydoc.services.rag_service import QueryDocService
from tests.conftest import make_settings


def test_ingest_retrieve_cited_page(service, synthetic_120):
    data, facts = synthetic_120
    rep = service.ingest(data, "manual.pdf")
    assert rep.record.page_count == 120 and rep.record.chunk_count > 100
    assert set(rep.timings_ms) >= {"extract", "chunk", "embed", "index", "persist"}
    # Default production pipeline (hybrid + cross-encoder rerank of 20 candidates).
    # Synthetic topics repeat every 15 pages, so questions differ mainly by section number.
    cfg = service.retrieval_config(use_rerank=True, rerank_k=20)
    top1 = 0
    for fact in facts:
        res = service.retrieve(fact.question, cfg)
        holding = [r for r in res.chunks if fact.answer in r.chunk.text]
        assert holding, f"fact for page {fact.page} not retrieved in top 5"
        assert holding[0].chunk.page_start <= fact.page <= holding[0].chunk.page_end
        top1 += holding[0].rank == 1
    assert top1 / len(facts) >= 0.9


def test_duplicate_upload_rejected(service):
    data, _ = make_synthetic_pdf(3, seed=1)
    service.ingest(data, "one.pdf")
    with pytest.raises(DuplicateDocumentError):
        service.ingest(data, "same-bytes-different-name.pdf")


def test_invalid_upload_does_not_touch_index(service):
    with pytest.raises(PDFValidationError):
        service.ingest(b"MZ\x90 not a pdf", "evil.exe.pdf")
    assert service.store.size == 0 and service.documents() == []


def test_scanned_only_pdf_reports_ocr_disabled(service):
    data, _ = make_synthetic_pdf(2, image_only_pages=(1, 2))
    with pytest.raises(QueryDocError, match="OCR is disabled"):
        service.ingest(data, "scan.pdf")


def test_multi_document_isolation_and_delete(service):
    a, facts_a = make_synthetic_pdf(10, seed=21)
    b, facts_b = make_synthetic_pdf(10, seed=22)
    doc_a = service.ingest(a, "a.pdf").record.doc_id
    doc_b = service.ingest(b, "b.pdf").record.doc_id
    cfg = service.retrieval_config(doc_ids=[doc_b], use_rerank=False)
    res = service.retrieve(facts_a[0].question, cfg)
    assert res.chunks and all(r.chunk.doc_id == doc_b for r in res.chunks)
    service.delete_document(doc_a)
    assert doc_a not in service.store.doc_ids()
    assert not service.document_path(doc_a).exists()
    with pytest.raises(DocumentNotFoundError):
        service.delete_document(doc_a)


def test_document_path_rejects_traversal(service):
    with pytest.raises(DocumentNotFoundError):
        service.document_path("../../etc/passwd")


def test_index_persists_across_restart(tmp_path, embedder):
    settings = make_settings(tmp_path)
    data, facts = make_synthetic_pdf(15, seed=5)
    QueryDocService(settings, embedder=embedder).ingest(data, "persist.pdf")
    reopened = QueryDocService(settings, embedder=embedder)
    assert len(reopened.documents()) == 1
    res = reopened.retrieve(facts[0].question, reopened.retrieval_config(use_rerank=False))
    assert facts[0].answer in res.chunks[0].chunk.text


def test_unsupported_question_declined_without_llm(service):
    data, _ = make_synthetic_pdf(10, seed=3)
    service.ingest(data, "x.pdf")
    resp = service.answer("What is the boiling point of mercury in Kelvin?")
    assert resp.mode == "insufficient_evidence" and resp.generation is None


def test_retrieval_only_fallback_when_llm_unavailable(tmp_path, embedder, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    settings = make_settings(tmp_path, llm_model="querydoc-test/does-not-exist", min_relevance_score=0.0)
    svc = QueryDocService(settings, embedder=embedder)
    data, facts = make_synthetic_pdf(5, seed=4)
    svc.ingest(data, "f.pdf")
    resp = svc.answer(facts[0].question)
    assert resp.mode == "retrieval_only" and resp.retrieval.chunks
    assert "unavailable" in resp.notes[0]


def test_concurrent_retrieval_during_ingest(service):
    base, facts = make_synthetic_pdf(30, seed=8)
    service.ingest(base, "base.pdf")
    extra = [make_synthetic_pdf(5, seed=100 + i)[0] for i in range(3)]
    cfg = service.retrieval_config(use_rerank=False)
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        ingests = [pool.submit(service.ingest, d, f"extra{i}.pdf") for i, d in enumerate(extra)]
        queries = [pool.submit(service.retrieve, facts[i % len(facts)].question, cfg) for i in range(60)]
        results = [q.result() for q in queries]
        for f in ingests:
            f.result()
    assert all(r.chunks for r in results)
    assert len(service.documents()) == 4
    # the persisted index must still load and agree with memory
    reopened = QueryDocService(service.settings, embedder=service.embedder)
    assert reopened.store.size == service.store.size


def test_generation_requests_are_bounded_before_retrieval(service, monkeypatch):
    """Requests beyond max_active + max_queue fail fast instead of queueing unboundedly."""
    import threading

    from querydoc.exceptions import QueueFullError
    from querydoc.services.concurrency import GenerationGate

    data, facts = make_synthetic_pdf(10, seed=9)
    service.ingest(data, "gate.pdf")
    service.gate = GenerationGate(max_active=1, max_queue=1, timeout_s=10)
    release = threading.Event()
    real_events = service._answer_events

    def slow_events(question, cfg, params, generate, started, wait_ms, history, cancel):
        release.wait(5)  # hold the slot; skip the LLM so the test needs no model
        yield from real_events(question, cfg, params, False, started, wait_ms, history, cancel)

    monkeypatch.setattr(service, "_answer_events", slow_events)
    results: list[object] = []

    def call():
        try:
            results.append(service.answer(facts[0].question))
        except QueueFullError as exc:
            results.append(exc)

    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads:
        t.start()
    import time

    time.sleep(0.3)
    release.set()
    for t in threads:
        t.join()
    rejected = [r for r in results if isinstance(r, QueueFullError)]
    assert len(rejected) == 2  # 1 active + 1 queued admitted, 2 rejected
    assert service.gate.active == 0 and service.gate.waiting == 0
