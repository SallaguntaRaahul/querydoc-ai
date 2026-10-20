"""CPU-only reranking trade-off: quality (dev/test nDCG@5 on the NIST benchmark) vs
latency for different numbers of reranked candidates and passage truncation lengths.

The deployed CPU profile is chosen by a fixed rule decided before running:
  best dev nDCG@5 among settings whose CPU retrieval p95 (full pipeline, 100+ page
  corpus) is < 300 ms. Test-split numbers are reported, never used for selection.

Usage: python benchmarks/benchmark_cpu_profile.py [--threads 8 --queries 120]
"""

from __future__ import annotations

import argparse
import time

import torch
from common import EVAL_SET, environment, latency_summary, load_corpus, write_results
from querydoc.chunking.chunkers import ChunkingConfig, chunk_document, joined_text
from querydoc.embeddings.embedder import Embedder, configure_torch_threads
from querydoc.evaluation.relevance import (
    GroundTruth,
    aggregate,
    load_eval_set,
    relative_improvement,
    score_ranking,
)
from querydoc.ingestion.pdf_loader import extract_pdf
from querydoc.retrieval.retriever import Reranker, RetrievalConfig, Retriever
from querydoc.vectorstore.faiss_store import FaissVectorStore

EMBED = "sentence-transformers/all-MiniLM-L6-v2"
RERANK = "cross-encoder/ms-marco-MiniLM-L-6-v2"
GRID = [(20, 512), (20, 256), (20, 192), (20, 128), (15, 256), (12, 256), (12, 512), (10, 512), (10, 256)]
METRICS = ["hit@5", "mrr", "ndcg@5"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--queries", type=int, default=120)
    args = ap.parse_args()
    configure_torch_threads(args.threads)

    es = load_eval_set(EVAL_SET)
    docs = [extract_pdf(d.data, d.filename, max_upload_mb=100) for d in load_corpus()]
    gt = GroundTruth.build(es.questions, {d.doc_id: joined_text(d) for d in docs}, {d.filename: d.doc_id for d in docs})
    cfg = ChunkingConfig(chunk_size=1000, chunk_overlap=200)
    chunks = [c for d in docs for c in chunk_document(d, cfg)]
    embedder = Embedder(EMBED, device="cpu", torch_threads=args.threads)
    store = FaissVectorStore(embedder.dim, EMBED)
    store.add(chunks, embedder.embed_texts([c.text for c in chunks]))
    n_rel = {q.id: sum(1 for c in chunks if gt.judge(q.id, c)) for q in es.questions}
    questions = [q.question for q in es.questions]

    def evaluate(retriever: Retriever, rcfg: RetrievalConfig) -> dict:
        rows = []
        for q in es.questions:
            res = retriever.retrieve(q.question, rcfg)
            m = score_ranking([gt.judge(q.id, r.chunk) for r in res.chunks], len(gt.spans[q.id]), n_rel[q.id])
            rows.append({**m, "split": q.split})
        return {s: aggregate([r for r in rows if s == "all" or r["split"] == s], METRICS) for s in ("dev", "test", "all")}

    def latency(retriever: Retriever, rcfg: RetrievalConfig) -> dict:
        for q in questions[:10]:
            retriever.retrieve(q, rcfg)
        ms = []
        for i in range(args.queries):
            t = time.perf_counter()
            retriever.retrieve(questions[i % len(questions)], rcfg)
            ms.append((time.perf_counter() - t) * 1000)
        return latency_summary(ms)

    baseline_ret = Retriever(store, embedder, None)
    base = evaluate(baseline_ret, RetrievalConfig(top_k=5, dedup=False))
    results = []
    for k, max_len in GRID:
        reranker = Reranker(RERANK, device="cpu")
        reranker.model.max_length = max_len
        retriever = Retriever(store, embedder, reranker)
        rcfg = RetrievalConfig(top_k=5, fetch_k=30, use_hybrid=True, use_rerank=True, dedup=True, rerank_k=k)
        quality = evaluate(retriever, rcfg)
        lat = latency(retriever, rcfg)
        row = {"rerank_k": k, "max_length": max_len, "quality": quality, "latency": lat,
               "test_rel_improvement_pct": relative_improvement(base["test"]["ndcg@5"], quality["test"]["ndcg@5"]),
               "all_rel_improvement_pct": relative_improvement(base["all"]["ndcg@5"], quality["all"]["ndcg@5"])}
        results.append(row)
        print(f"k={k:2d} len={max_len:3d}  dev={quality['dev']['ndcg@5']:.3f} test={quality['test']['ndcg@5']:.3f} "
              f"all={quality['all']['ndcg@5']:.3f} (test {row['test_rel_improvement_pct']:+.1f}%)  "
              f"p50={lat['p50_ms']:.0f} p95={lat['p95_ms']:.0f} ms", flush=True)
        del reranker, retriever

    feasible = [r for r in results if r["latency"]["p95_ms"] < 300]
    chosen = max(feasible, key=lambda r: r["quality"]["dev"]["ndcg@5"]) if feasible else None
    payload = {
        "experiment": "CPU-only reranking profile: quality vs latency",
        "selection_rule": "max dev nDCG@5 subject to CPU retrieval p95 < 300 ms (fixed before running)",
        "threads": args.threads, "queries_per_setting": args.queries,
        "corpus_pages": sum(d.page_count for d in docs), "chunks": len(chunks),
        "baseline": base, "results": results, "chosen": chosen,
        "environment": environment([EMBED, RERANK]),
        "command": f"python benchmarks/benchmark_cpu_profile.py --threads {args.threads} --queries {args.queries}",
    }
    write_results("cpu_profile", payload, [
        {"rerank_k": r["rerank_k"], "max_length": r["max_length"], **{f"{s}_ndcg": r["quality"][s]["ndcg@5"] for s in ("dev", "test", "all")},
         "p50_ms": r["latency"]["p50_ms"], "p95_ms": r["latency"]["p95_ms"]} for r in results], "summary.csv")
    print("chosen:", {k: chosen[k] for k in ("rerank_k", "max_length")} if chosen else None)
    _ = torch


if __name__ == "__main__":
    main()
