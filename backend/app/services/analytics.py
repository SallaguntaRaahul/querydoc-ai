"""Analytics: runtime telemetry recorded by this installation, and benchmark
evidence read from ``results/``. The two are returned separately and labelled;
nothing here is synthesised."""

from __future__ import annotations

import json
import os
import resource
import sys
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Conversation, Document, QueryLog
from app.rag.engine import EngineManager


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def _summary(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "p50": _pct(values, 50), "p95": _pct(values, 95),
            "mean": round(sum(values) / len(values), 2) if values else None}


def overview(db: Session, manager: EngineManager) -> dict[str, Any]:
    docs = list(db.scalars(select(Document)))
    ready = [d for d in docs if d.status == "ready"]
    logs = list(db.scalars(select(QueryLog).order_by(QueryLog.created_at.desc()).limit(500)))
    gen_logs = [q for q in logs if q.mode == "generated"]
    svc = manager.service
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / 1024**2 if sys.platform == "darwin" else peak / 1024  # bytes on macOS, KiB on Linux
    ingest = [
        {
            "document_id": d.id, "filename": d.filename, "pages": d.page_count, "chunks": d.chunk_count,
            "total_ms": round(sum(d.timings_ms.values()), 1) if d.timings_ms else None,
            "timings_ms": d.timings_ms, "chunks_per_second": d.embedding_stats.get("chunks_per_second"),
        }
        for d in ready if d.timings_ms
    ]
    return {
        "source": "runtime",
        "documents": {
            "total": len(docs), "ready": len(ready),
            "processing": sum(d.status in {"queued", "processing"} for d in docs),
            "failed": sum(d.status == "failed" for d in docs),
            "pages": sum(d.page_count for d in ready), "chunks": sum(d.chunk_count for d in ready),
            "bytes": sum(d.size_bytes for d in ready),
        },
        "conversations": db.scalar(select(func.count()).select_from(Conversation)) or 0,
        "index": {
            "vectors": svc.store.size, "approx_bytes": svc.store.memory_bytes(), "type": svc.store.index_type,
            "embedding_model": svc.embedder.model_name, "dim": svc.embedder.dim,
        },
        "queries": {
            "total": len(logs),
            "by_mode": {m: sum(q.mode == m for q in logs) for m in sorted({q.mode for q in logs})},
            "retrieval_ms": _summary([q.retrieval_ms for q in logs if q.retrieval_ms is not None]),
            "generation_ms": _summary([q.generation_ms for q in gen_logs if q.generation_ms is not None]),
            "ttft_ms": _summary([q.ttft_ms for q in gen_logs if q.ttft_ms is not None]),
            "total_ms": _summary([q.total_ms for q in gen_logs if q.total_ms is not None]),
            "recent": [
                {"at": q.created_at.isoformat(), "mode": q.mode, "retrieval_ms": q.retrieval_ms,
                 "generation_ms": q.generation_ms, "total_ms": q.total_ms}
                for q in reversed(logs[:60])
            ],
        },
        "ingestion": ingest,
        "process": {
            "rss_mb": round(psutil.Process(os.getpid()).memory_info().rss / 1024**2, 1),
            "peak_rss_mb": round(peak_mb, 1),
            "note": "Process RSS. Model weights on an Apple GPU (MPS) live in unified memory and are not fully counted.",
        },
        "models": manager.model_status(),
    }


def _read(results_dir: Path, name: str) -> dict[str, Any] | None:
    p = results_dir / name / "results.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _meta(d: dict[str, Any]) -> dict[str, Any]:
    env = d.get("environment", {})
    return {"command": d.get("command"), "timestamp": env.get("timestamp_utc"), "git_commit": env.get("git_commit"),
            "hardware": f"{env.get('cpu')} · {env.get('ram_gb')} GB", "swap_used_gb": env.get("swap_used_gb_at_start")}


def benchmarks(results_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "benchmark", "results_dir": str(results_dir)}
    if rel := _read(results_dir, "relevance"):
        out["relevance"] = {
            "meta": _meta(rel), "primary_metric": rel["primary_metric_name"], "baseline": rel["baseline"],
            "optimized": rel["optimized_selected_on_dev"], "selection_rule": rel.get("selection_rule"),
            "comparison": rel["comparison"],
            "sweep": [
                {"chunking": k.split("|")[0], "retrieval": k.split("|")[1], "ndcg_all": v["all"]["ndcg@5"],
                 "ndcg_dev": v["dev"]["ndcg@5"], "ndcg_test": v["test"]["ndcg@5"], "hit_all": v["all"]["hit@5"],
                 "latency_ms": v["all"]["latency_ms"]}
                for k, v in rel["summary"].items()
            ],
        }
    for name in ("retrieval_latency", "retrieval_latency_cpu"):
        if lat := _read(results_dir, name):
            out[name] = {
                "meta": _meta(lat), "reranker_device": lat.get("reranker_device", "cpu"),
                "rows": [
                    {"dataset": v["dataset"], "config": v["config"], "pages": v["pages"], "chunks": v["chunks"],
                     "p50_ms": v["pooled"]["p50_ms"], "p95_ms": v["pooled"]["p95_ms"], "p99_ms": v["pooled"]["p99_ms"],
                     "cold_ms": v["cold_first_query_ms"]}
                    for v in lat["summary"].values()
                ],
            }
    if emb := _read(results_dir, "embeddings"):
        out["embeddings"] = {
            "meta": _meta(emb), "document": emb["document"], "comparisons": emb["comparisons"],
            "rows": [
                {"strategy": k, "peak_rss_mb": v["peak_rss_mb"]["mean"], "working_set_mb": v["embedding_working_set_mb"]["mean"],
                 "chunks_per_second": v["chunks_per_second"]["mean"], "chunks": v["chunks"]}
                for k, v in emb["aggregate"].items()
            ],
        }
    if conc := _read(results_dir, "concurrency"):
        out["concurrency"] = {
            "meta": _meta(conc), "index": conc["index"], "generation_controls": conc["generation_controls"],
            "retrieval": [{"users": r["users"], "requests": r["requests"], "errors": r["failed"],
                           "rps": r["throughput_rps"], "p50_ms": r["latency"]["p50_ms"], "p95_ms": r["latency"]["p95_ms"]}
                          for r in conc["retrieval"]],
            "generation": [{"users": r["users"], "requests": r["requests"], "ok": r["succeeded"], "errors": r["errors"],
                            "rps": r["throughput_rps"], "p50_ms": r["latency"]["p50_ms"], "p95_ms": r["latency"]["p95_ms"]}
                           for r in conc["generation"]],
        }
    if gen := _read(results_dir, "generation"):
        out["generation"] = {
            "meta": _meta(gen),
            "models": [
                {"model": m, "accuracy": s["answer_accuracy"], "cited_rate": s["cited_rate"],
                 "model_tagged_rate": s.get("model_tagged_rate"), "on_evidence_rate": s["citation_on_evidence_rate"],
                 "declined_unanswerable": s["unanswerable_declined_rate"], "e2e_p50_ms": s["end_to_end_latency"]["p50_ms"],
                 "e2e_p95_ms": s["end_to_end_latency"]["p95_ms"], "ttft_p50_ms": s["ttft"]["p50_ms"],
                 "tokens_per_second": s["tokens_per_second_mean"]}
                for m, s in gen["summary"].items()
            ],
        }
    if ing := _read(results_dir, "ingestion"):
        out["ingestion"] = {"meta": _meta(ing), "rows": [{"document": k, **v} for k, v in ing["summary"].items()]}
    if api := _read(results_dir, "api_e2e"):
        out["api_e2e"] = api
    return out
