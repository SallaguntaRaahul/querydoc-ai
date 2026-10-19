"""Embedding throughput and peak-memory benchmark.

Each configuration runs in a *fresh subprocess* so peak RSS is not polluted by
earlier runs. Inside the worker:

  1. load the SentenceTransformer model (CPU) and run one warm-up encode,
  2. record RSS ("after_load"),
  3. embed every chunk of the target document(s) with the given strategy while a
     5 ms sampler tracks peak RSS,
  4. report peak RSS, peak-minus-after_load ("embedding working set"), time.

What is counted: process resident set size (psutil RSS) — Python objects,
PyTorch CPU tensors/activations, tokenizer buffers, FAISS is not involved.
Model weights are resident in both baseline and optimized runs, so the
"working set" delta isolates memory attributable to the embedding strategy.

Strategies
  single_pass        all chunks in ONE forward pass (no mini-batching), as naive
                     code calling the HF model directly on the whole list does.
  batch_N            SentenceTransformer.encode(batch_size=N) on the full list,
                     returning one array (N = 1, 8, 16, 32, 64, 128, 256).
  streaming_N        QueryDoc's Embedder: mini-batches of N written straight
                     into a preallocated float32 matrix (no retained per-batch
                     tensors), with duplicate-text skipping.

Usage:  python benchmarks/benchmark_embeddings.py [--repeats 3]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time

from common import ROOT, environment, load_corpus, write_results

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TARGET_DOC = "NIST.SP.800-37r2.pdf"  # 183 pages - the "100+ page document" case
STRATEGIES = (
    ["single_pass"]
    + [f"batch_{n}" for n in (1, 8, 16, 32, 64, 128, 256)]
    + [f"streaming_{n}" for n in (16, 32, 64)]
)


def worker(strategy: str, doc_name: str, chunk_size: int, chunk_overlap: int) -> dict:
    import gc

    import numpy as np
    import torch
    from common import PeakRSSSampler

    from querydoc.chunking.chunkers import ChunkingConfig, chunk_document
    from querydoc.embeddings.embedder import Embedder
    from querydoc.ingestion.pdf_loader import extract_pdf

    data = next(d.data for d in load_corpus() if d.filename == doc_name)
    doc = extract_pdf(data, doc_name, max_upload_mb=100)
    chunks = chunk_document(doc, ChunkingConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap))
    texts = [c.text for c in chunks]
    del doc, data
    emb = Embedder(EMBED_MODEL, device="cpu", batch_size=32, cache_dir=None)
    emb.embed_texts(texts[:8], use_cache=False)  # warm-up
    gc.collect()

    model = emb.model
    with PeakRSSSampler() as mem:
        t = time.perf_counter()
        if strategy == "single_pass":
            feats = model.tokenize(texts)
            with torch.inference_mode():
                out = model.forward(feats)["sentence_embedding"]
            vecs = torch.nn.functional.normalize(out, dim=1).numpy()
        elif strategy.startswith("batch_"):
            vecs = model.encode(texts, batch_size=int(strategy.split("_")[1]), normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
        else:
            vecs = emb.embed_texts(texts, batch_size=int(strategy.split("_")[1]), use_cache=False)
        seconds = time.perf_counter() - t
    assert vecs.shape == (len(texts), emb.dim)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1, atol=1e-3)
    return {
        "strategy": strategy,
        "chunks": len(texts),
        "seconds": seconds,
        "chunks_per_second": len(texts) / seconds,
        "rss_after_load_mb": mem.start_rss / 1024**2,
        "peak_rss_mb": mem.peak_mb,
        "embedding_working_set_mb": mem.delta_mb,
        "torch_threads": torch.get_num_threads(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--doc", default=TARGET_DOC)
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--chunk-overlap", type=int, default=200)
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.worker:
        print("RESULT " + json.dumps(worker(args.worker, args.doc, args.chunk_size, args.chunk_overlap)))
        return

    rows = []
    for rep in range(args.repeats):
        for strategy in STRATEGIES:
            cmd = [sys.executable, __file__, "--worker", strategy, "--doc", args.doc,
                   "--chunk-size", str(args.chunk_size), "--chunk-overlap", str(args.chunk_overlap)]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
            if line is None:
                row = {"strategy": strategy, "error": proc.stderr[-500:]}
            else:
                row = json.loads(line[7:])
            row["repeat"] = rep
            rows.append(row)
            print(f"rep{rep} {strategy:14s} " + (
                f"peak={row['peak_rss_mb']:.0f}MB ws={row['embedding_working_set_mb']:.0f}MB "
                f"{row['chunks_per_second']:.0f} chunks/s" if "error" not in row else "ERROR"), flush=True)

    agg = {}
    for s in STRATEGIES:
        ok = [r for r in rows if r["strategy"] == s and "error" not in r]
        if not ok:
            continue
        agg[s] = {
            k: {"mean": statistics.fmean(r[k] for r in ok),
                "stdev": statistics.stdev([r[k] for r in ok]) if len(ok) > 1 else 0.0}
            for k in ("peak_rss_mb", "embedding_working_set_mb", "chunks_per_second", "seconds")
        }
        agg[s]["chunks"] = ok[0]["chunks"]

    def reduction(base: str, opt: str, key: str) -> float | None:
        if base not in agg or opt not in agg:
            return None
        b, o = agg[base][key]["mean"], agg[opt][key]["mean"]
        return (b - o) / b * 100

    comparisons = {
        f"{b}_vs_{o}": {
            "peak_rss_reduction_pct": reduction(b, o, "peak_rss_mb"),
            "working_set_reduction_pct": reduction(b, o, "embedding_working_set_mb"),
            "throughput_change_pct": (
                (agg[o]["chunks_per_second"]["mean"] / agg[b]["chunks_per_second"]["mean"] - 1) * 100
                if b in agg and o in agg else None
            ),
        }
        for b, o in [("single_pass", "streaming_32"), ("batch_256", "streaming_32"),
                     ("batch_128", "streaming_32"), ("batch_32", "streaming_32")]
    }
    payload = {
        "experiment": "embedding peak memory and throughput vs batching strategy",
        "document": args.doc,
        "chunking": {"strategy": "recursive", "chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap},
        "measurement": "psutil RSS sampled every 5 ms in a fresh subprocess per run; CPU inference",
        "repeats": args.repeats,
        "aggregate": agg,
        "comparisons": comparisons,
        "environment": environment([EMBED_MODEL]),
        "command": f"python benchmarks/benchmark_embeddings.py --repeats {args.repeats} --doc {args.doc} "
                   f"--chunk-size {args.chunk_size} --chunk-overlap {args.chunk_overlap}",
    }
    out = write_results("embeddings", payload, rows, "raw.csv")
    print(json.dumps(comparisons, indent=2))
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
