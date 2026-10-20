"""Retrieval latency benchmark (query text in -> ranked passages out).

Measures warm per-query latency of ``Retriever.retrieve`` — query embedding,
FAISS search, optional BM25 fusion, de-duplication and cross-encoder reranking —
for documents of 10/50/100/200 synthetic pages, the 183-page NIST SP 800-37r2,
and the full 4-document NIST corpus (391 pages). LLM generation is NOT included;
see benchmark_generation.py for end-to-end answer latency.

Protocol: build index -> 1 cold query (reported separately) -> 10 warm-up
queries -> N timed queries cycling through the question set; repeated for
``--trials`` independent trials. Timer: time.perf_counter().

Usage:  python benchmarks/benchmark_retrieval.py [--queries 200 --trials 3]
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import asdict

from common import EVAL_SET, environment, latency_summary, load_corpus, write_results
from querydoc.chunking.chunkers import ChunkingConfig, chunk_document
from querydoc.config import Settings
from querydoc.embeddings.embedder import Embedder
from querydoc.evaluation.relevance import load_eval_set
from querydoc.evaluation.synthetic import make_synthetic_pdf
from querydoc.ingestion.pdf_loader import extract_pdf
from querydoc.retrieval.retriever import Reranker, RetrievalConfig, Retriever
from querydoc.vectorstore.faiss_store import FaissVectorStore

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def configs(args: argparse.Namespace) -> dict[str, tuple[ChunkingConfig, RetrievalConfig]]:
    opt_chunk = ChunkingConfig(strategy=args.opt_strategy, chunk_size=args.opt_size, chunk_overlap=args.opt_overlap)
    return {
        "baseline_dense": (ChunkingConfig(chunk_size=1000, chunk_overlap=200), RetrievalConfig(top_k=5, dedup=False)),
        "optimized": (
            opt_chunk,
            RetrievalConfig(top_k=5, fetch_k=args.fetch_k, use_hybrid=True, use_rerank=True, dedup=True,
                            rerank_k=args.rerank_k),
        ),
        "optimized_no_rerank": (
            opt_chunk, RetrievalConfig(top_k=5, fetch_k=args.fetch_k, use_hybrid=True, dedup=True)
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--opt-strategy", default="recursive")
    ap.add_argument("--opt-size", type=int, default=1000)
    ap.add_argument("--opt-overlap", type=int, default=200)
    ap.add_argument("--fetch-k", type=int, default=30)
    ap.add_argument("--rerank-k", type=int, default=20)
    ap.add_argument("--reranker-device", default="mps")
    ap.add_argument("--name", default="retrieval_latency", help="results/<name>/")
    args = ap.parse_args()

    eval_set = load_eval_set(EVAL_SET)
    real_qs = [q.question for q in eval_set.questions]
    corpus = {d.filename: d.data for d in load_corpus()}

    datasets: dict[str, tuple[list[bytes], list[str]]] = {}
    for pages in (10, 50, 100, 200):
        data, facts = make_synthetic_pdf(pages, seed=pages)
        datasets[f"synthetic_{pages}p"] = ([data], [f.question for f in facts] + real_qs[:20])
    datasets["nist_800-37r2_183p"] = (
        [corpus["NIST.SP.800-37r2.pdf"]],
        [q.question for q in eval_set.questions if q.doc == "NIST.SP.800-37r2.pdf"] + real_qs,
    )
    datasets["nist_corpus_391p"] = (list(corpus.values()), real_qs)

    embedder = Embedder(EMBED_MODEL, device="cpu")
    reranker = Reranker(RERANK_MODEL, device=args.reranker_device, max_length=Settings().reranker_max_length)
    rows, summary = [], {}
    for ds_name, (pdfs, questions) in datasets.items():
        docs = [extract_pdf(b, f"{ds_name}_{i}.pdf", max_upload_mb=100) for i, b in enumerate(pdfs)]
        pages = sum(d.page_count for d in docs)
        for cfg_name, (ccfg, rcfg) in configs(args).items():
            chunks = [c for d in docs for c in chunk_document(d, ccfg)]
            store = FaissVectorStore(embedder.dim, EMBED_MODEL)
            store.add(chunks, embedder.embed_texts([c.text for c in chunks]))
            retriever = Retriever(store, embedder, reranker)
            retriever.bm25._ensure()  # build lexical index outside the timed region
            cold = retriever.retrieve("What is the purpose of this document?", rcfg).latency_ms
            trial_stats = []
            all_ms: list[float] = []
            stage_ms: dict[str, list[float]] = {}
            for trial in range(args.trials):
                for q in questions[:10]:
                    retriever.retrieve(q, rcfg)
                ms = []
                for i in range(args.queries):
                    t = time.perf_counter()
                    res = retriever.retrieve(questions[i % len(questions)], rcfg)
                    elapsed = (time.perf_counter() - t) * 1000
                    ms.append(elapsed)
                    for k, v in res.timings_ms.items():
                        stage_ms.setdefault(k, []).append(v)
                    rows.append({"dataset": ds_name, "config": cfg_name, "trial": trial, "i": i, "latency_ms": elapsed})
                trial_stats.append(latency_summary(ms))
                all_ms += ms
            pooled = latency_summary(all_ms)
            summary[f"{ds_name}|{cfg_name}"] = {
                "dataset": ds_name, "config": cfg_name, "pages": pages, "chunks": len(chunks),
                "cold_first_query_ms": cold,
                "pooled": pooled,
                "per_trial_p50_ms": [s["p50_ms"] for s in trial_stats],
                "per_trial_p95_ms": [s["p95_ms"] for s in trial_stats],
                "p95_trial_stdev_ms": statistics.stdev([s["p95_ms"] for s in trial_stats]) if args.trials > 1 else 0,
                "stage_mean_ms": {k: statistics.fmean(v) for k, v in stage_ms.items()},
                "under_300ms_p95": pooled["p95_ms"] < 300,
            }
            print(f"{ds_name:22s} {cfg_name:20s} pages={pages:4d} chunks={len(chunks):5d} "
                  f"p50={pooled['p50_ms']:6.1f} p95={pooled['p95_ms']:6.1f} p99={pooled['p99_ms']:6.1f} "
                  f"cold={cold:6.1f}", flush=True)

    payload = {
        "experiment": "warm retrieval latency (excludes LLM generation)",
        "queries_per_trial": args.queries,
        "trials": args.trials,
        "configs": {k: {"chunking": asdict(c), "retrieval": asdict(r)} for k, (c, r) in configs(args).items()},
        "reranker_device": args.reranker_device,
        "summary": summary,
        "environment": environment([EMBED_MODEL, RERANK_MODEL]),
        "command": "python benchmarks/benchmark_retrieval.py " + " ".join(
            f"--{k.replace('_', '-')} {v}" for k, v in vars(args).items()),
    }
    out = write_results(args.name, payload, rows, "raw.csv")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
