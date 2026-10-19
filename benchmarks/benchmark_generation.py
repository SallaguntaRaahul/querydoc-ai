"""Local LLM generation benchmark: latency, throughput and grounded-answer quality.

For each model: load time, then the full RAG pipeline on the held-out test
questions (answerable) plus the unanswerable set, over the full NIST index.

Quality checks (automatic, deterministic):
* answer_correct  - every answer_keyword appears in the answer (case-insensitive)
* cited           - at least one valid citation survived verification
* citation_on_evidence - some cited chunk covers a gold evidence span
* declined        - for unanswerable questions, the system returned insufficient evidence

Usage:  python benchmarks/benchmark_generation.py [--models Qwen/Qwen2.5-0.5B-Instruct ...]
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
from pathlib import Path

from common import EVAL_SET, environment, latency_summary, load_corpus, write_results

from querydoc.chunking.chunkers import joined_text
from querydoc.config import Settings
from querydoc.evaluation.relevance import GroundTruth, load_eval_set
from querydoc.generation.llm import GenerationParams
from querydoc.ingestion.pdf_loader import extract_pdf
from querydoc.services.rag_service import QueryDocService


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct"])
    ap.add_argument("--split", default="test")
    ap.add_argument("--max-new-tokens", type=int, default=128)
    args = ap.parse_args()

    es = load_eval_set(EVAL_SET)
    questions = es.split(args.split)
    corpus = load_corpus()
    tmp = Path(tempfile.mkdtemp(prefix="qd-gen-"))
    base = QueryDocService(Settings(data_dir=tmp))
    for d in corpus:
        base.ingest(d.data, d.filename)
    docs = [extract_pdf(d.data, d.filename, max_upload_mb=100) for d in corpus]
    gt = GroundTruth.build(es.questions, {d.doc_id: joined_text(d) for d in docs},
                           {d.filename: d.doc_id for d in docs})

    rows, summary = [], {}
    for model in args.models:
        svc = QueryDocService(Settings(data_dir=tmp, llm_model=model, max_new_tokens=args.max_new_tokens),
                              embedder=base.embedder)
        llm = svc.llm()
        params = GenerationParams(max_new_tokens=args.max_new_tokens)
        svc.answer(questions[0].question, params=params)  # warm-up (kernel compilation on MPS)
        model_rows = []
        for q in questions:
            resp = svc.answer(q.question, params=params)
            text = resp.answer.lower()
            cites = resp.citations.citations if resp.citations else []
            on_evidence = any(gt.judge(q.id, svc.store.get_chunk(c.chunk_id)) for c in cites
                              if svc.store.get_chunk(c.chunk_id))
            g = resp.generation
            model_rows.append({
                "model": model, "qid": q.id, "kind": "answerable", "status": resp.status, "mode": resp.mode,
                "answer_correct": all(k.lower() in text for k in q.answer_keywords),
                "cited": bool(cites), "citation_on_evidence": on_evidence,
                "invalid_tags": len(resp.citations.invalid_tags) if resp.citations else 0,
                "retrieval_ms": resp.timings_ms.get("retrieval"), "generation_ms": resp.timings_ms.get("generation"),
                "total_ms": resp.timings_ms.get("total"),
                "ttft_ms": g.time_to_first_token_ms if g else None,
                "completion_tokens": g.completion_tokens if g else 0,
                "tokens_per_s": g.tokens_per_second if g else None,
                "answer": resp.answer[:400],
            })
        for i, uq in enumerate(es.unanswerable):
            resp = svc.answer(uq, params=params)
            model_rows.append({
                "model": model, "qid": 101 + i, "kind": "unanswerable", "status": resp.status, "mode": resp.mode,
                "declined": resp.status == "insufficient_evidence",
                "total_ms": resp.timings_ms.get("total"), "answer": resp.answer[:400],
            })
        rows += model_rows
        ans = [r for r in model_rows if r["kind"] == "answerable"]
        gen = [r for r in ans if r["mode"] == "generated"]
        una = [r for r in model_rows if r["kind"] == "unanswerable"]
        summary[model] = {
            "device": llm.device,
            "revision": llm.revision,
            "load_seconds": llm.load_seconds,
            "answerable": len(ans),
            "answer_accuracy": sum(r["answer_correct"] for r in ans) / len(ans),
            "cited_rate": sum(r["cited"] for r in ans) / len(ans),
            "citation_on_evidence_rate": sum(r["citation_on_evidence"] for r in ans) / len(ans),
            "status_counts": {s: sum(r["status"] == s for r in ans) for s in {r["status"] for r in ans}},
            "invalid_tags_removed": sum(r["invalid_tags"] for r in ans),
            "unanswerable_declined_rate": sum(r["declined"] for r in una) / len(una) if una else None,
            "end_to_end_latency": latency_summary([r["total_ms"] for r in gen]),
            "generation_latency": latency_summary([r["generation_ms"] for r in gen]),
            "ttft": latency_summary([r["ttft_ms"] for r in gen]),
            "tokens_per_second_mean": statistics.fmean(r["tokens_per_s"] for r in gen) if gen else None,
            "mean_completion_tokens": statistics.fmean(r["completion_tokens"] for r in gen) if gen else None,
        }
        s = summary[model]
        print(f"{model}: device={s['device']} load={s['load_seconds']:.1f}s acc={s['answer_accuracy']:.2f} "
              f"cited={s['cited_rate']:.2f} on_evidence={s['citation_on_evidence_rate']:.2f} "
              f"declined_unans={s['unanswerable_declined_rate']} e2e_p50={s['end_to_end_latency']['p50_ms']:.0f}ms "
              f"p95={s['end_to_end_latency']['p95_ms']:.0f}ms tok/s={s['tokens_per_second_mean']}", flush=True)
        del svc, llm

    payload = {
        "experiment": "local generation latency and grounded answer quality",
        "split": args.split,
        "max_new_tokens": args.max_new_tokens,
        "retrieval_config": base.retrieval_config().__dict__,
        "summary": summary,
        "environment": environment(args.models),
        "command": "python benchmarks/benchmark_generation.py --models " + " ".join(args.models),
    }
    out = write_results("generation", payload, rows, "per_question.csv")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
