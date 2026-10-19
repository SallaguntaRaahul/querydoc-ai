"""End-to-end latency through the real HTTP API (what the React app experiences).

Starts a fresh FastAPI server (empty temporary workspace, real models), uploads
the four NIST PDFs through POST /documents/upload and times upload → ready, then
streams the held-out test questions through POST /chat/stream and records, per
question, client-side wall-clock times for:

* time to evidence  — request sent → SSE ``retrieval`` event (queueing + retrieval)
* time to first token — request sent → first ``token`` event
* total — request sent → ``done`` event (generation + citation verification + DB write)

Usage:  python benchmarks/benchmark_api.py [--port 8400] [--max-new-tokens 128]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from common import EVAL_SET, ROOT, environment, latency_summary, load_corpus, write_results
from querydoc.evaluation.relevance import load_eval_set


def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _json(url: str, method: str = "GET", body: bytes | None = None, ctype: str = "application/json") -> dict:
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 - localhost only
        return json.loads(r.read() or b"{}")


def stream(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
    t0 = time.perf_counter()
    out: dict = {"tokens": 0}
    event = None
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
        for raw in r:
            line = raw.decode().rstrip("\n")
            now = (time.perf_counter() - t0) * 1000
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                if event == "retrieval":
                    out["time_to_evidence_ms"] = now
                    out["server_retrieval_ms"] = data.get("latency_ms")
                elif event == "token":
                    out.setdefault("time_to_first_token_ms", now)
                    out["tokens"] += 1
                elif event == "done":
                    out["total_ms"] = now
                    m = data["message"]
                    out.update(status=m["status"], mode=m["mode"], cited=bool(m["citations"]),
                               server_timings=m["timings_ms"])
                elif event == "error":
                    out.update(total_ms=now, status="error", error=data.get("code"))
                event = None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8400)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}/api/v1"
    tmp = Path(tempfile.mkdtemp(prefix="qd-api-bench-"))
    env = {**os.environ, "QUERYDOC_DATA_DIR": str(tmp), "QUERYDOC_LOAD_MODELS_ON_STARTUP": "true",
           "QUERYDOC_MAX_NEW_TOKENS": str(args.max_new_tokens), "QUERYDOC_LOG_LEVEL": "WARNING"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.port)],
                            cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(240):
            try:
                health = _json(f"{base}/health")
                if health["models"]["llm"]["loaded"]:
                    break
            except OSError:
                pass
            time.sleep(1)
        ingest = []
        for d in load_corpus():
            body, ctype = _multipart(d.filename, d.data)
            t0 = time.perf_counter()
            doc = _json(f"{base}/documents/upload", "POST", body, ctype)["documents"][0]
            accepted_ms = (time.perf_counter() - t0) * 1000
            while True:
                st = _json(f"{base}/documents/{doc['id']}/status")
                if st["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.1)
            info = _json(f"{base}/documents/{doc['id']}")
            ingest.append({"document": d.filename, "pages": info["page_count"], "chunks": info["chunk_count"],
                           "status": st["status"], "upload_accepted_ms": accepted_ms,
                           "upload_to_ready_ms": (time.perf_counter() - t0) * 1000})
            print(f"ingested {d.filename}: {info['page_count']} pages in {ingest[-1]['upload_to_ready_ms'] / 1000:.1f}s", flush=True)

        questions = [q.question for q in load_eval_set(EVAL_SET).split("test")]
        stream(f"{base}/chat/stream", {"message": questions[0]})  # warm-up (MPS kernels, reranker)
        rows = []
        for i, q in enumerate(questions):
            r = stream(f"{base}/chat/stream", {"message": q})
            r["question"] = q
            rows.append(r)
            print(f"[{i + 1}/{len(questions)}] evidence {r.get('time_to_evidence_ms', 0):.0f} ms · "
                  f"first token {r.get('time_to_first_token_ms', 0):.0f} ms · total {r['total_ms']:.0f} ms · {r.get('status')}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    gen = [r for r in rows if r.get("mode") == "generated"]
    summary = {
        "questions": len(rows),
        "generated": len(gen),
        "status_counts": {s: sum(r.get("status") == s for r in rows) for s in sorted({r.get("status") for r in rows})},
        "time_to_evidence": latency_summary([r["time_to_evidence_ms"] for r in rows if "time_to_evidence_ms" in r]),
        "server_retrieval": latency_summary([r["server_retrieval_ms"] for r in rows if r.get("server_retrieval_ms")]),
        "time_to_first_token": latency_summary([r["time_to_first_token_ms"] for r in gen if "time_to_first_token_ms" in r]),
        "total_generated": latency_summary([r["total_ms"] for r in gen]),
        "total_all": latency_summary([r["total_ms"] for r in rows]),
        "mean_tokens": statistics.fmean(r["tokens"] for r in gen) if gen else None,
    }
    payload = {
        "experiment": "end-to-end latency through the HTTP API (SSE streaming, real models)",
        "max_new_tokens": args.max_new_tokens,
        "ingestion": ingest,
        "summary": summary,
        "environment": environment(["sentence-transformers/all-MiniLM-L6-v2", "cross-encoder/ms-marco-MiniLM-L-6-v2",
                                    "Qwen/Qwen2.5-1.5B-Instruct"]),
        "command": f"python benchmarks/benchmark_api.py --max-new-tokens {args.max_new_tokens}",
    }
    out = write_results("api_e2e", payload, rows, "per_question.csv")
    s = summary
    print(f"time to evidence p50 {s['time_to_evidence']['p50_ms']:.0f} p95 {s['time_to_evidence']['p95_ms']:.0f} ms | "
          f"first token p50 {s['time_to_first_token']['p50_ms']:.0f} | total p50 {s['total_generated']['p50_ms']:.0f} "
          f"p95 {s['total_generated']['p95_ms']:.0f} ms")
    print(f"results -> {out}")


if __name__ == "__main__":
    main()
