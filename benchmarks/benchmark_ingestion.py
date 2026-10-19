"""Ingestion pipeline timing for 10/50/100/200-page synthetic PDFs and the real
NIST documents: extraction, chunking, embedding, indexing and persistence.

Each run uses a fresh workspace and a cold embedding cache (the model itself is
loaded once and reused, as it is in the application).

Usage:  python benchmarks/benchmark_ingestion.py [--repeats 3]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
from pathlib import Path

from common import environment, load_corpus, write_results

from querydoc.config import Settings
from querydoc.embeddings.embedder import Embedder
from querydoc.evaluation.synthetic import make_synthetic_pdf
from querydoc.services.rag_service import QueryDocService

STAGES = ["extract", "chunk", "embed", "index", "persist"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    settings0 = Settings()
    embedder = Embedder(settings0.embedding_model, device="cpu", batch_size=settings0.embedding_batch_size)
    inputs = [(f"synthetic_{p}p.pdf", make_synthetic_pdf(p, seed=p)[0]) for p in (10, 50, 100, 200)]
    inputs += [(d.filename, d.data) for d in load_corpus()]

    rows, summary = [], {}
    for name, data in inputs:
        per = []
        for rep in range(args.repeats):
            tmp = Path(tempfile.mkdtemp(prefix="qd-ing-"))
            embedder.cache._store.clear()  # cold cache each repetition
            svc = QueryDocService(Settings(data_dir=tmp), embedder=embedder)
            r = svc.ingest(data, name)
            row = {"document": name, "repeat": rep, "pages": r.record.page_count, "chunks": r.record.chunk_count,
                   "mb": len(data) / 1024**2, **{f"{k}_ms": r.timings_ms.get(k, 0.0) for k in STAGES},
                   "total_ms": sum(r.timings_ms.values()),
                   "chunks_per_second": r.embedding["chunks_per_second"], "rss_after_mb": r.rss_mb_after}
            rows.append(row)
            per.append(row)
            shutil.rmtree(tmp, ignore_errors=True)
        summary[name] = {
            "pages": per[0]["pages"], "chunks": per[0]["chunks"],
            **{f"{k}_ms_mean": statistics.fmean(p[f"{k}_ms"] for p in per) for k in STAGES + ["total"]},
            "total_ms_stdev": statistics.stdev([p["total_ms"] for p in per]) if len(per) > 1 else 0.0,
            "pages_per_second": per[0]["pages"] / (statistics.fmean(p["total_ms"] for p in per) / 1000),
            "chunks_per_second_mean": statistics.fmean(p["chunks_per_second"] for p in per),
        }
        s = summary[name]
        print(f"{name:24s} pages={s['pages']:4d} chunks={s['chunks']:5d} total={s['total_ms_mean']:8.0f}ms "
              f"(extract {s['extract_ms_mean']:.0f} / embed {s['embed_ms_mean']:.0f}) "
              f"{s['pages_per_second']:.0f} pages/s", flush=True)

    payload = {
        "experiment": "ingestion pipeline timings",
        "repeats": args.repeats,
        "chunking": {"strategy": settings0.chunk_strategy, "size": settings0.chunk_size,
                     "overlap": settings0.chunk_overlap},
        "embedding_batch_size": settings0.embedding_batch_size,
        "summary": summary,
        "environment": environment([settings0.embedding_model]),
        "command": f"python benchmarks/benchmark_ingestion.py --repeats {args.repeats}",
    }
    out = write_results("ingestion", payload, rows, "raw.csv")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
