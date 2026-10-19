"""Concurrent query load test against one shared QueryDocService.

Closed-loop model: U simulated users (threads) each send R requests back to
back. Retrieval-only and full-generation tests are run separately:

* retrieval: U in {1, 2, 5, 10, 20}, the optimized retrieval pipeline over the
  full 4-document NIST index (multi-document queries).
* generation: U in {1, 2, 5, 10, 20} with the configured admission control
  (max_active_generations=1, bounded queue, timeout). Requests rejected by the
  queue limit are counted as failures (QueueFullError) - that is the designed
  back-pressure behaviour, not a crash.

Usage:  python benchmarks/benchmark_concurrency.py [--retrieval-requests 20 --generation-requests 2]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import tempfile
import time
from pathlib import Path

from common import EVAL_SET, PeakRSSSampler, environment, latency_summary, load_corpus, write_results
from querydoc.config import Settings
from querydoc.evaluation.relevance import load_eval_set
from querydoc.exceptions import QueryDocError
from querydoc.generation.llm import GenerationParams
from querydoc.services.rag_service import QueryDocService

LEVELS = [1, 2, 5, 10, 20]


def run_level(fn, users: int, per_user: int, questions: list[str]) -> dict:
    results: list[dict] = []

    def user(uid: int) -> None:
        for j in range(per_user):
            q = questions[(uid * per_user + j) % len(questions)]
            t = time.perf_counter()
            try:
                extra = fn(q)
                results.append({"ok": True, "ms": (time.perf_counter() - t) * 1000, **extra})
            except QueryDocError as exc:
                results.append({"ok": False, "ms": (time.perf_counter() - t) * 1000, "error": type(exc).__name__})

    with PeakRSSSampler(0.01) as mem:
        started = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=users) as pool:
            list(pool.map(user, range(users)))
        wall = time.perf_counter() - started
    ok = [r for r in results if r["ok"]]
    errors: dict[str, int] = {}
    for r in results:
        if not r["ok"]:
            errors[r["error"]] = errors.get(r["error"], 0) + 1
    out = {
        "users": users,
        "requests": len(results),
        "succeeded": len(ok),
        "failed": len(results) - len(ok),
        "error_rate": (len(results) - len(ok)) / len(results),
        "errors": errors,
        "wall_seconds": wall,
        "throughput_rps": len(ok) / wall,
        "latency": latency_summary([r["ms"] for r in ok]),
        "peak_rss_mb": mem.peak_mb,
    }
    if ok and "queue_wait_ms" in ok[0]:
        out["queue_wait"] = latency_summary([r["queue_wait_ms"] for r in ok])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-requests", type=int, default=20, help="requests per user")
    ap.add_argument("--generation-requests", type=int, default=2, help="requests per user")
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--skip-generation", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="qd-conc-"))
    settings = Settings(data_dir=tmp, max_active_generations=1, max_generation_queue=8,
                        generation_timeout_s=120, max_new_tokens=args.max_new_tokens)
    svc = QueryDocService(settings)
    for d in load_corpus():
        svc.ingest(d.data, d.filename)
    questions = [q.question for q in load_eval_set(EVAL_SET).questions]
    rcfg = svc.retrieval_config()
    svc.retrieve(questions[0], rcfg)  # load reranker, build BM25

    retrieval = []
    for users in LEVELS:
        r = run_level(lambda q: {"n": len(svc.retrieve(q, rcfg).chunks)}, users, args.retrieval_requests, questions)
        retrieval.append(r)
        print(f"retrieval  U={users:2d} ok={r['succeeded']:4d}/{r['requests']:4d} rps={r['throughput_rps']:6.1f} "
              f"p50={r['latency']['p50_ms']:7.1f} p95={r['latency']['p95_ms']:7.1f} "
              f"p99={r['latency']['p99_ms']:7.1f} rss={r['peak_rss_mb']:.0f}MB", flush=True)

    generation = []
    if not args.skip_generation:
        params = GenerationParams(max_new_tokens=args.max_new_tokens)
        svc.answer(questions[0], rcfg, params)  # load LLM, warm up

        def gen(q: str) -> dict:
            resp = svc.answer(q, rcfg, params)
            return {"queue_wait_ms": resp.timings_ms.get("queue_wait", 0.0), "mode": resp.mode}

        for users in LEVELS:
            r = run_level(gen, users, args.generation_requests, questions)
            generation.append(r)
            print(f"generation U={users:2d} ok={r['succeeded']:3d}/{r['requests']:3d} rps={r['throughput_rps']:5.2f} "
                  f"p50={r['latency']['p50_ms']:8.0f} p95={r['latency']['p95_ms']:8.0f} "
                  f"errors={r['errors']} rss={r['peak_rss_mb']:.0f}MB", flush=True)

    payload = {
        "experiment": "concurrent queries on a shared service (threads, closed loop)",
        "index": {"documents": len(svc.documents()), "chunks": svc.store.size,
                  "pages": sum(d.page_count for d in svc.documents())},
        "retrieval_config": rcfg.__dict__,
        "generation_controls": {"max_active": settings.max_active_generations,
                                "max_queue": settings.max_generation_queue,
                                "timeout_s": settings.generation_timeout_s,
                                "max_new_tokens": args.max_new_tokens,
                                "llm": settings.llm_model, "llm_device": svc._llm.device if svc._llm else None},
        "retrieval": retrieval,
        "generation": generation,
        "environment": environment([settings.embedding_model, settings.reranker_model, settings.llm_model]),
        "command": f"python benchmarks/benchmark_concurrency.py --retrieval-requests {args.retrieval_requests} "
                   f"--generation-requests {args.generation_requests} --max-new-tokens {args.max_new_tokens}",
    }
    rows = [{"kind": "retrieval", **{k: v for k, v in r.items() if not isinstance(v, dict)},
             **{f"lat_{k}": v for k, v in r["latency"].items()}} for r in retrieval]
    rows += [{"kind": "generation", **{k: v for k, v in r.items() if not isinstance(v, dict)},
              **{f"lat_{k}": v for k, v in r["latency"].items()}} for r in generation]
    out = write_results("concurrency", payload, rows, "summary.csv")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
