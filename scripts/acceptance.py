"""Automated acceptance check for QueryDoc AI (full-stack). Reads evidence files
only and classifies every criterion as PASS / FAIL / NOT TESTED / BLOCKED.
Functional tests never count as benchmark passes; a missed target stays FAIL.

Evidence producers:
  ./scripts/test_all.sh                 → results/tests/{junit,vitest-junit,playwright-junit}.xml
  python scripts/check_app.py           → results/app/launch.json
  python benchmarks/run_all_benchmarks.py  (+ benchmarks/benchmark_api.py) → results/*/results.json
Usage:  python scripts/acceptance.py   → results/acceptance/{acceptance.json, ACCEPTANCE.md}
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
PASS, FAIL, NOT_TESTED, BLOCKED = "PASS", "FAIL", "NOT TESTED", "BLOCKED"
REQUIRED_DOCS = [
    "README.md", "IMPLEMENTATION_STATUS.md", "docs/PROJECT_COMPLETE_GUIDE.md", "docs/ARCHITECTURE.md",
    "docs/TECH_STACK_DECISIONS.md", "docs/RAG_INTERNALS.md", "docs/PERFORMANCE_REPORT.md", "docs/EXPERIMENTS.md",
    "docs/TESTING_AND_VALIDATION.md", "docs/TROUBLESHOOTING.md", "docs/INTERVIEW_PREPARATION.md",
    "docs/RESUME_CLAIM_VALIDATION.md", "docs/API.md",
]


def load(rel: str) -> dict[str, Any] | None:
    p = R / rel
    return json.loads(p.read_text()) if p.exists() else None


def junit(name: str) -> dict[str, Any] | None:
    p = R / "tests" / name
    if not p.exists():
        return None
    root = ET.parse(p).getroot()
    cases: dict[str, str] = {}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for c in root.iter("testcase"):
        totals["tests"] += 1
        status = "passed"
        if c.find("failure") is not None:
            status, totals["failures"] = "failed", totals["failures"] + 1
        elif c.find("error") is not None:
            status, totals["errors"] = "error", totals["errors"] + 1
        elif c.find("skipped") is not None:
            status, totals["skipped"] = "skipped", totals["skipped"] + 1
        cases[c.get("name", "")] = status
    return {"totals": totals, "cases": cases, "file": f"results/tests/{name}"}


def main() -> int:
    py, vt, pw = junit("junit.xml"), junit("vitest-junit.xml"), junit("playwright-junit.xml")
    launch = load("app/launch.json")
    rows: list[dict[str, str]] = []

    def add(group: str, req: str, target: str, status: str, measured: str, evidence: str) -> None:
        rows.append({"group": group, "requirement": req, "target": target, "status": status, "measured": measured, "evidence": evidence})

    def e2e(req: str, needle: str) -> None:
        if not pw:
            add("Definition of done", req, "Playwright test passes", NOT_TESTED, "no Playwright results", "results/tests/playwright-junit.xml")
            return
        hits = {k: v for k, v in pw["cases"].items() if needle.lower() in k.lower()}
        if not hits:
            add("Definition of done", req, "Playwright test passes", NOT_TESTED, f"no test matching '{needle}'", pw["file"])
            return
        ok = all(v == "passed" for v in hits.values())
        add("Definition of done", req, "Playwright test passes", PASS if ok else FAIL,
            "; ".join(f"{k}: {v}" for k, v in hits.items()), pw["file"])

    # ---------------------------------------------------- definition of done
    if launch:
        build = launch.get("frontend_build", {})
        add("Definition of done", "1. React frontend builds", "vite build succeeds", PASS if build.get("ok") else FAIL,
            f"built in {build.get('seconds')} s", "results/app/launch.json")
        add("Definition of done", "2. FastAPI backend starts", "health OK, SPA + OpenAPI served",
            PASS if launch.get("backend_healthy") and launch.get("spa_served") and launch.get("spa_route_fallback") else FAIL,
            f"healthy in {launch.get('seconds_to_healthy')} s; {launch.get('openapi_paths')} API paths", "results/app/launch.json")
    else:
        add("Definition of done", "1. React frontend builds", "vite build succeeds", NOT_TESTED, "", "results/app/launch.json")
        add("Definition of done", "2. FastAPI backend starts", "health OK", NOT_TESTED, "", "results/app/launch.json")
    e2e("3–4. Real PDF uploaded and indexed (incl. 183 pages)", "upload: validation error, then two real PDFs")
    e2e("5–7. Question retrieves evidence, local LLM answers, citation opens the page", "ask a question")
    e2e("8. Conversations persist (follow-up, reload, history)", "follow-up question, persistence")
    e2e("9. Settings work (validation + persistence)", "settings: invalid input")
    e2e("10. Analytics shows real data", "analytics shows live telemetry")
    e2e("Stop generation", "stop a generation")
    e2e("Delete document and index entries", "delete a document")
    for name, j in (("backend pytest", py), ("frontend Vitest", vt)):
        if j:
            t = j["totals"]
            add("Definition of done", f"11. Automated tests — {name}", "0 failures, 0 errors",
                PASS if t["tests"] and not t["failures"] and not t["errors"] else FAIL,
                f"{t['tests']} tests, {t['failures']} failed, {t['errors']} errors, {t['skipped']} skipped", j["file"])
        else:
            add("Definition of done", f"11. Automated tests — {name}", "0 failures", NOT_TESTED, "", "results/tests/")
    if pw:
        functional = {k: v for k, v in pw["cases"].items() if "render cleanly" not in k and "layout" not in k
                      and "focus" not in k and "seed" not in k and "viewer side" not in k and "long titles" not in k
                      and "empty, loading" not in k}
        ok = all(v == "passed" for v in functional.values())
        add("Definition of done", "12. End-to-end tests (Playwright, real stack)", "all pass", PASS if functional and ok else FAIL,
            f"{sum(v == 'passed' for v in functional.values())}/{len(functional)} passed", pw["file"])
        visual = {k: v for k, v in pw["cases"].items() if k not in functional}
        shots = list((ROOT / "docs/images/ui").glob("*.png"))
        add("Definition of done", "13. Visual inspection (desktop/tablet/mobile × dark/light, states)",
            "visual specs pass and screenshots captured",
            PASS if visual and all(v == "passed" for v in visual.values()) and len(shots) >= 30 else FAIL,
            f"{sum(v == 'passed' for v in visual.values())}/{len(visual)} visual checks; {len(shots)} screenshots",
            "docs/images/ui/")
    bench_files = ["relevance", "retrieval_latency", "retrieval_latency_cpu", "embeddings", "concurrency", "generation",
                   "ingestion", "api_e2e"]
    present = [b for b in bench_files if (R / b / "results.json").exists()]
    add("Definition of done", "14. Benchmark results recorded", "all benchmark result files present",
        PASS if len(present) == len(bench_files) else FAIL, f"{len(present)}/{len(bench_files)}: {', '.join(present)}", "results/")
    missing = [d for d in REQUIRED_DOCS if not (ROOT / d).exists() or (ROOT / d).stat().st_size < 1500]
    add("Definition of done", "15. Documentation complete", "all required documents present",
        PASS if not missing else FAIL, "all present" if not missing else f"missing/short: {missing}", "docs/")
    rcv = ROOT / "docs/RESUME_CLAIM_VALIDATION.md"
    statuses = sum(rcv.read_text().count(s) for s in ("**PASS**", "**FAIL**")) if rcv.exists() else 0
    add("Definition of done", "16. Every resume claim has an evidence status", "claim table with statuses",
        PASS if statuses >= 10 else FAIL, f"{statuses} verdicts in claim table", "docs/RESUME_CLAIM_VALIDATION.md")

    # ------------------------------------------------------------- targets
    rel, lat, lat_cpu, emb, conc, gen, api = (load(f"{n}/results.json") for n in
        ("relevance", "retrieval_latency", "retrieval_latency_cpu", "embeddings", "concurrency", "generation", "api_e2e"))
    if rel:
        t, a = rel["comparison"]["test"], rel["comparison"]["all"]
        imp = t["relative_improvement_pct"]["ndcg@5"]
        add("Performance targets", "Context relevance improvement", "≥ 40% relative nDCG@5 (held-out test split)",
            PASS if imp >= 40 else FAIL,
            f"{t['baseline']['ndcg@5']:.3f} → {t['optimized']['ndcg@5']:.3f} = {imp:+.1f}% (CI95 {t['primary_metric_ci95_pct'][0]:+.0f}…{t['primary_metric_ci95_pct'][1]:+.0f}%); all 63: {a['relative_improvement_pct']['ndcg@5']:+.1f}%",
            "results/relevance/results.json")
    for label, data, path in (("GPU reranker", lat, "retrieval_latency"), ("CPU-only reranker", lat_cpu, "retrieval_latency_cpu")):
        if data:
            big = [v for v in data["summary"].values() if v["config"] == "optimized" and v["pages"] >= 100]
            worst = max(big, key=lambda v: v["pooled"]["p95_ms"])
            add("Performance targets", f"Retrieval latency, 100+ pages ({label})", "p95 < 300 ms",
                PASS if all(v["pooled"]["p95_ms"] < 300 for v in big) else FAIL,
                f"worst p95 {worst['pooled']['p95_ms']:.0f} ms, p50 {worst['pooled']['p50_ms']:.0f} ms ({worst['dataset']})",
                f"results/{path}/results.json")
    if emb:
        c = emb["comparisons"]
        red = c["single_pass_vs_streaming_32"]["peak_rss_reduction_pct"]
        add("Performance targets", "Peak-memory reduction", "≥ 35% peak RSS (batched vs unbatched embedding)",
            PASS if red >= 35 else FAIL,
            f"{red:.1f}% vs unbatched; {c['batch_256_vs_streaming_32']['peak_rss_reduction_pct']:.1f}% vs batch-256; "
            f"{c['batch_32_vs_streaming_32']['peak_rss_reduction_pct']:.1f}% vs library default", "results/embeddings/results.json")
    if conc:
        levels = conc["retrieval"]
        add("Performance targets", "Concurrent retrieval", "tested at ≥ 3 loads, 0 errors",
            PASS if len(levels) >= 3 and all(r["error_rate"] == 0 for r in levels) else FAIL,
            ", ".join(f"{r['users']}u {r['throughput_rps']:.1f} rps p95 {r['latency']['p95_ms']:.0f} ms" for r in levels),
            "results/concurrency/results.json")
    if gen:
        g = gen["summary"].get("Qwen/Qwen2.5-1.5B-Instruct") or next(iter(gen["summary"].values()))
        add("Performance targets", "Local LLM generation latency (engine)", "measured (no target)", PASS,
            f"p50 {g['generation_latency']['p50_ms'] / 1000:.2f} s, TTFT p50 {g['ttft']['p50_ms'] / 1000:.2f} s, {g['tokens_per_second_mean']:.1f} tok/s",
            "results/generation/results.json")
    if api:
        s = api["summary"]
        add("Performance targets", "End-to-end answer latency via HTTP API", "< 300 ms (stretch, not a stated target)",
            PASS if s["total_generated"]["p95_ms"] < 300 else FAIL,
            f"evidence p50 {s['time_to_evidence']['p50_ms']:.0f} ms · first token p50 {s['time_to_first_token']['p50_ms']:.0f} ms · "
            f"total p50 {s['total_generated']['p50_ms'] / 1000:.2f} s / p95 {s['total_generated']['p95_ms'] / 1000:.2f} s",
            "results/api_e2e/results.json")
    else:
        add("Performance targets", "End-to-end answer latency via HTTP API", "measured", NOT_TESTED, "", "results/api_e2e/results.json")

    out = R / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "acceptance.json").write_text(json.dumps({"generated_utc": stamp, "criteria": rows}, indent=2))
    md = ["# Acceptance results", "", f"Generated {stamp} by `python scripts/acceptance.py`.", ""]
    for group in ("Definition of done", "Performance targets"):
        md += [f"## {group}", "", "| Requirement | Target | Status | Measured | Evidence |", "|---|---|---|---|---|"]
        md += [f"| {r['requirement']} | {r['target']} | **{r['status']}** | {r['measured']} | `{r['evidence']}` |"
               for r in rows if r["group"] == group]
        md.append("")
    (out / "ACCEPTANCE.md").write_text("\n".join(md))
    for r in rows:
        print(f"{r['status']:10s} {r['requirement'][:58]:58s} {r['measured'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
