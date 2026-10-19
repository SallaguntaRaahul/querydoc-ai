"""Retrieval-quality experiment: baseline vs. tuned pipelines on the NIST corpus.

Protocol
  1. All four NIST PDFs are indexed together (multi-document retrieval).
  2. Every chunking config x retrieval config is evaluated on all 63 questions.
  3. The optimized config is chosen *automatically* as the best mean nDCG@5 on
     the dev split (odd ids). The test split (even ids) is never used to choose.
  4. Baseline vs. optimized is reported on test, dev and all questions, with a
     95% paired-bootstrap confidence interval for the relative improvement.

Usage:  python benchmarks/benchmark_relevance.py [--quick]
"""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict

from common import EVAL_SET, environment, load_corpus, write_results

from querydoc.chunking.chunkers import ChunkingConfig, chunk_document, joined_text
from querydoc.embeddings.embedder import Embedder
from querydoc.evaluation.relevance import (
    PRIMARY_METRIC,
    GroundTruth,
    aggregate,
    bootstrap_ci,
    load_eval_set,
    relative_improvement,
    score_ranking,
)
from querydoc.ingestion.pdf_loader import extract_pdf
from querydoc.retrieval.retriever import Reranker, RetrievalConfig, Retriever
from querydoc.vectorstore.faiss_store import FaissVectorStore

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
METRICS = ["hit@5", "precision@5", "recall@5", "mrr", "ndcg@5"]
K = 5

BASELINE_CHUNKING = ("recursive", 1000, 200)
BASELINE_RETRIEVAL = "dense"

CHUNKINGS = [
    ("recursive", 1000, 200),
    ("recursive", 1000, 0),
    ("recursive", 750, 150),
    ("recursive", 500, 100),
    ("recursive", 384, 64),
    ("recursive", 256, 50),
    ("fixed", 1000, 200),
    ("fixed", 500, 100),
    ("sentence", 1000, 200),
    ("sentence", 500, 100),
]

RETRIEVALS: dict[str, RetrievalConfig] = {
    "dense": RetrievalConfig(top_k=K, dedup=False),
    "dense+dedup": RetrievalConfig(top_k=K, fetch_k=30, dedup=True),
    "dense+mmr": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_mmr=True),
    "hybrid": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_hybrid=True),
    "dense+rerank": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_rerank=True),
    "hybrid+rerank": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_hybrid=True, use_rerank=True),
    "hybrid+mmr+rerank": RetrievalConfig(
        top_k=K, fetch_k=30, dedup=True, use_hybrid=True, use_mmr=True, use_rerank=True
    ),
    # latency-capped variants: only the best N fused candidates go to the cross-encoder
    "dense+rerank@20": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_rerank=True, rerank_k=20),
    "hybrid+rerank@20": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_hybrid=True, use_rerank=True, rerank_k=20),
    "hybrid+rerank@10": RetrievalConfig(top_k=K, fetch_k=30, dedup=True, use_hybrid=True, use_rerank=True, rerank_k=10),
}
# The deployed configuration must fit the sub-300 ms p95 retrieval target. Mean latency
# measured during this sweep must be <= LATENCY_BUDGET_MS (half the target, leaving
# headroom for tail latency); the authoritative p50/p95 come from benchmark_retrieval.py.
LATENCY_BUDGET_MS = 150.0


def chunk_key(c: tuple[str, int, int]) -> str:
    return f"{c[0]}-{c[1]}-{c[2]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="baseline chunking + 500/100 only")
    ap.add_argument("--reranker-device", default="cpu")
    args = ap.parse_args()

    eval_set = load_eval_set(EVAL_SET)
    corpus = load_corpus()
    docs = [extract_pdf(d.data, d.filename, max_upload_mb=100) for d in corpus]
    filename_to_id = {d.filename: d.doc_id for d in docs}
    texts = {d.doc_id: joined_text(d) for d in docs}
    gt = GroundTruth.build(eval_set.questions, texts, filename_to_id)
    if gt.missing:
        raise SystemExit(f"evidence spans not found: {gt.missing}")

    embedder = Embedder(EMBED_MODEL, device="cpu", batch_size=32)
    reranker = Reranker(RERANK_MODEL, device=args.reranker_device)
    chunkings = [BASELINE_CHUNKING, ("recursive", 500, 100)] if args.quick else CHUNKINGS

    rows: list[dict] = []
    summary: dict[str, dict] = {}
    index_info: dict[str, dict] = {}
    for strategy, size, overlap in chunkings:
        ck = chunk_key((strategy, size, overlap))
        cfg = ChunkingConfig(strategy=strategy, chunk_size=size, chunk_overlap=overlap)
        chunks = [c for d in docs for c in chunk_document(d, cfg)]
        t = time.perf_counter()
        vectors = embedder.embed_texts([c.text for c in chunks])
        embed_s = time.perf_counter() - t
        store = FaissVectorStore(embedder.dim, EMBED_MODEL)
        store.add(chunks, vectors)
        retriever = Retriever(store, embedder, reranker)
        n_relevant = {
            q.id: sum(1 for c in chunks if gt.judge(q.id, c)) for q in eval_set.questions
        }
        index_info[ck] = {
            "chunks": len(chunks),
            "mean_chars": sum(len(c.text) for c in chunks) / len(chunks),
            "embed_seconds": embed_s,
            "questions_without_relevant_chunk": [q for q, n in n_relevant.items() if n == 0],
        }
        print(f"[{ck}] {len(chunks)} chunks", flush=True)
        for rname, rcfg in RETRIEVALS.items():
            per_q = []
            for q in eval_set.questions:
                res = retriever.retrieve(q.question, rcfg)
                covered = [gt.judge(q.id, r.chunk) for r in res.chunks]
                m = score_ranking(covered, len(gt.spans[q.id]), n_relevant[q.id], k=K)
                row = {
                    "chunking": ck, "retrieval": rname, "qid": q.id, "split": q.split, "doc": q.doc,
                    **m, "latency_ms": res.latency_ms,
                    "retrieved": "|".join(f"{r.chunk.chunk_id}:{int(bool(c))}" for r, c in zip(res.chunks, covered, strict=True)),
                }
                rows.append(row)
                per_q.append(row)
            key = f"{ck}|{rname}"
            summary[key] = {
                split: aggregate([r for r in per_q if split == "all" or r["split"] == split], METRICS + ["latency_ms"])
                for split in ("dev", "test", "all")
            }
            s = summary[key]
            print(f"   {rname:20s} dev ndcg={s['dev']['ndcg@5']:.3f} test ndcg={s['test']['ndcg@5']:.3f} "
                  f"all ndcg={s['all']['ndcg@5']:.3f} hit={s['all']['hit@5']:.3f} "
                  f"lat={s['all']['latency_ms']:.1f}ms", flush=True)

    baseline_key = f"{chunk_key(BASELINE_CHUNKING)}|{BASELINE_RETRIEVAL}"
    unconstrained_key = max(summary, key=lambda k: summary[k]["dev"][PRIMARY_METRIC])
    feasible = [k for k in summary if summary[k]["all"]["latency_ms"] <= LATENCY_BUDGET_MS]
    best_key = max(feasible, key=lambda k: summary[k]["dev"][PRIMARY_METRIC])

    def per_query(key: str, split: str) -> list[float]:
        ck, rn = key.split("|")
        sel = [r for r in rows if r["chunking"] == ck and r["retrieval"] == rn and (split == "all" or r["split"] == split)]
        return [r[PRIMARY_METRIC] for r in sorted(sel, key=lambda r: r["qid"])]

    comparison = {}
    for split in ("test", "dev", "all"):
        b = summary[baseline_key][split]
        o = summary[best_key][split]
        comparison[split] = {
            "baseline": b,
            "optimized": o,
            "relative_improvement_pct": {m: relative_improvement(b[m], o[m]) for m in METRICS},
            "absolute_improvement_pts": {m: (o[m] - b[m]) * 100 for m in METRICS},
            "primary_metric_ci95_pct": bootstrap_ci(per_query(baseline_key, split), per_query(best_key, split)),
        }

    payload = {
        "experiment": "retrieval relevance: baseline vs dev-selected optimized pipeline",
        "primary_metric": PRIMARY_METRIC,
        "primary_metric_name": "Context Relevance (mean nDCG@5, evidence-span relevance)",
        "k": K,
        "baseline": baseline_key,
        "optimized_selected_on_dev": best_key,
        "selection_rule": f"max dev {PRIMARY_METRIC} subject to sweep mean latency <= {LATENCY_BUDGET_MS} ms",
        "unconstrained_best_on_dev": unconstrained_key,
        "unconstrained_test": summary[unconstrained_key]["test"],
        "reranker_device": args.reranker_device,
        "comparison": comparison,
        "summary": summary,
        "index_info": index_info,
        "retrieval_configs": {k: asdict(v) for k, v in RETRIEVALS.items()},
        "corpus": [{"file": d.filename, "pages": d.page_count, "doc_id": d.doc_id} for d in docs],
        "questions": {"total": len(eval_set.questions), "dev": len(eval_set.split("dev")), "test": len(eval_set.split("test"))},
        "environment": environment([EMBED_MODEL, RERANK_MODEL]),
        "command": "python benchmarks/benchmark_relevance.py" + (" --quick" if args.quick else "")
        + f" --reranker-device {args.reranker_device}",
    }
    out = write_results("relevance", payload, rows, "per_query.csv")
    t = comparison["test"]
    print(f"\nbaseline={baseline_key}  optimized(dev-selected, latency-feasible)={best_key}  "
          f"unconstrained={unconstrained_key}")
    print(f"TEST  nDCG@5 {t['baseline']['ndcg@5']:.3f} -> {t['optimized']['ndcg@5']:.3f}  "
          f"rel {t['relative_improvement_pct']['ndcg@5']:+.1f}%  CI95 {t['primary_metric_ci95_pct']}")
    a = comparison["all"]
    print(f"ALL   nDCG@5 {a['baseline']['ndcg@5']:.3f} -> {a['optimized']['ndcg@5']:.3f}  "
          f"rel {a['relative_improvement_pct']['ndcg@5']:+.1f}%")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
