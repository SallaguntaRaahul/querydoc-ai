"""Automated acceptance check. Reads the evidence files produced by the test
suite, the benchmarks and the Streamlit launch check, and classifies every
criterion as PASS / FAIL / NOT TESTED / BLOCKED. A functional test never counts
as a benchmark pass; a missed target stays FAIL.

Usage:
  pytest --junitxml=results/tests/junit.xml        # evidence: automated tests
  python benchmarks/run_all_benchmarks.py           # evidence: benchmarks
  python scripts/check_streamlit.py                 # evidence: app launch
  python scripts/acceptance.py                      # -> results/acceptance/
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
    "README.md", "docs/PROJECT_COMPLETE_GUIDE.md", "docs/ARCHITECTURE.md", "docs/TECH_STACK_DECISIONS.md",
    "docs/RAG_INTERNALS.md", "docs/PERFORMANCE_REPORT.md", "docs/EXPERIMENTS.md",
    "docs/TESTING_AND_VALIDATION.md", "docs/TROUBLESHOOTING.md", "docs/INTERVIEW_PREPARATION.md",
    "docs/RESUME_CLAIM_VALIDATION.md",
]


def load(rel: str) -> dict[str, Any] | None:
    p = R / rel
    return json.loads(p.read_text()) if p.exists() else None


def junit() -> dict[str, Any] | None:
    p = R / "tests" / "junit.xml"
    if not p.exists():
        return None
    root = ET.parse(p).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    cases: dict[str, str] = {}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for k in totals:
            totals[k] += int(s.get(k, 0))
        for c in s.iter("testcase"):
            status = "passed"
            if c.find("failure") is not None:
                status = "failed"
            elif c.find("error") is not None:
                status = "error"
            elif c.find("skipped") is not None:
                status = "skipped"
            cases[c.get("name", "")] = status
    return {"totals": totals, "cases": cases}


def case(j: dict | None, name: str) -> str | None:
    if not j:
        return None
    return next((v for k, v in j["cases"].items() if k.startswith(name)), None)


def main() -> int:
    j = junit()
    ing, emb, rel, lat, conc, gen = (load(f"{n}/results.json") for n in
                                     ("ingestion", "embeddings", "relevance", "retrieval_latency", "concurrency", "generation"))
    st = load("streamlit/launch.json")
    rows: list[dict[str, str]] = []

    def add(req: str, target: str, status: str, measured: str, evidence: str) -> None:
        rows.append({"requirement": req, "target": target, "status": status, "measured": measured, "evidence": evidence})

    def from_case(req: str, target: str, name: str, evidence: str = "results/tests/junit.xml") -> None:
        c = case(j, name)
        if c is None:
            add(req, target, NOT_TESTED, "test result missing", evidence)
        else:
            add(req, target, PASS if c == "passed" else (BLOCKED if c == "skipped" else FAIL), f"{name}: {c}", evidence)

    # functional ------------------------------------------------------------
    if ing:
        big = {k: v for k, v in ing["summary"].items() if v["pages"] >= 100}
        add("PDF ingestion", "Works for 100+ pages", PASS if big else FAIL,
            ", ".join(f"{k}: {v['pages']} pages in {v['total_ms_mean'] / 1000:.1f}s" for k, v in big.items()),
            "results/ingestion/results.json")
    else:
        add("PDF ingestion", "Works for 100+ pages", NOT_TESTED, "", "results/ingestion/results.json")
    from_case("Multiple PDFs", "Functional", "test_multi_document_isolation_and_delete")
    add("Local embeddings", "Functional", PASS if emb else NOT_TESTED,
        f"{len(emb['aggregate'])} strategies benchmarked" if emb else "", "results/embeddings/results.json")
    from_case("FAISS indexing", "Functional", "test_store_add_search_filter_delete")
    from_case("Persistent indexes", "Functional", "test_index_persists_across_restart")
    if gen:
        ok = {m: s for m, s in gen["summary"].items() if s["answerable"] and s["end_to_end_latency"]["n"] > 0}
        add("Local Hugging Face LLM", "Functional", PASS if ok else FAIL,
            "; ".join(f"{m} on {s['device']}" for m, s in ok.items()), "results/generation/results.json")
    else:
        add("Local Hugging Face LLM", "Functional", NOT_TESTED, "", "results/generation/results.json")
    from_case("Citation-grounded answers", "Tested", "test_supported_question_answered_with_valid_citation")

    # benchmarks ----------------------------------------------------------------
    if lat:
        big = [v for v in lat["summary"].values() if v["config"] == "optimized" and v["pages"] >= 100]
        worst = max(big, key=lambda v: v["pooled"]["p95_ms"]) if big else None
        add("Retrieval latency", "p95 < 300 ms on 100+ page docs (optimized pipeline, warm)",
            PASS if big and all(v["pooled"]["p95_ms"] < 300 for v in big) else FAIL,
            (f"worst p95 {worst['pooled']['p95_ms']:.0f} ms / p50 {worst['pooled']['p50_ms']:.0f} ms "
             f"({worst['dataset']})") if worst else "no 100+ page runs",
            "results/retrieval_latency/results.json")
    else:
        add("Retrieval latency", "p95 < 300 ms", NOT_TESTED, "", "results/retrieval_latency/results.json")
    lat_cpu = load("retrieval_latency_cpu/results.json")
    if lat_cpu:
        big = [v for v in lat_cpu["summary"].values() if v["config"] == "optimized" and v["pages"] >= 100]
        worst = max(big, key=lambda v: v["pooled"]["p95_ms"])
        add("Retrieval latency, CPU-only reranker", "p95 < 300 ms on 100+ page docs",
            PASS if all(v["pooled"]["p95_ms"] < 300 for v in big) else FAIL,
            f"worst p95 {worst['pooled']['p95_ms']:.0f} ms ({worst['dataset']})",
            "results/retrieval_latency_cpu/results.json")
    if gen:
        default = gen["summary"].get("Qwen/Qwen2.5-1.5B-Instruct") or next(iter(gen["summary"].values()))
        e2e = default["end_to_end_latency"]
        add("End-to-end answer latency (default LLM)", "< 300 ms (stretch; not a stated target)",
            PASS if e2e["p95_ms"] < 300 else FAIL,
            f"p50 {e2e['p50_ms'] / 1000:.1f} s, p95 {e2e['p95_ms'] / 1000:.1f} s", "results/generation/results.json")
    if rel:
        t = rel["comparison"]["test"]
        a = rel["comparison"]["all"]
        imp = t["relative_improvement_pct"]["ndcg@5"]
        add("Context relevance improvement", ">= 40% relative (nDCG@5, held-out test split)",
            PASS if imp >= 40 else FAIL,
            f"{t['baseline']['ndcg@5']:.3f} -> {t['optimized']['ndcg@5']:.3f} = {imp:+.1f}% "
            f"(CI95 {t['primary_metric_ci95_pct'][0]:+.0f}..{t['primary_metric_ci95_pct'][1]:+.0f}%); "
            f"all 63 questions {a['relative_improvement_pct']['ndcg@5']:+.1f}%",
            "results/relevance/results.json")
    else:
        add("Context relevance improvement", ">= 40%", NOT_TESTED, "", "results/relevance/results.json")
    if emb:
        c = emb["comparisons"]["single_pass_vs_streaming_32"]
        strict = emb["comparisons"]["batch_256_vs_streaming_32"]
        red = c["peak_rss_reduction_pct"]
        add("Peak-memory reduction", ">= 35% peak RSS, batched streaming vs unbatched single pass",
            PASS if red is not None and red >= 35 else FAIL,
            f"{red:.1f}% vs single pass; {strict['peak_rss_reduction_pct']:.1f}% vs batch-256; "
            f"{emb['comparisons']['batch_32_vs_streaming_32']['peak_rss_reduction_pct']:.1f}% vs library default batch-32",
            "results/embeddings/results.json")
    else:
        add("Peak-memory reduction", ">= 35%", NOT_TESTED, "", "results/embeddings/results.json")
    if conc:
        levels = conc["retrieval"]
        clean = all(r["error_rate"] == 0 for r in levels)
        gen_levels = conc.get("generation", [])
        if gen_levels:
            ok_upto = max((r["users"] for r in gen_levels if r["error_rate"] == 0), default=0)
            add("Concurrent generation", "info: bounded admission control",
                PASS if ok_upto >= 2 else FAIL,
                f"0 errors up to {ok_upto} users; "
                + ", ".join(f"{r['users']}u: {r['errors']}" for r in gen_levels if r["errors"]),
                "results/concurrency/results.json")
        add("Concurrent retrieval", "Tested at multiple loads",
            PASS if len(levels) >= 3 and clean else FAIL,
            ", ".join(f"{r['users']}u: {r['throughput_rps']:.0f} rps p95 {r['latency']['p95_ms']:.0f} ms" for r in levels),
            "results/concurrency/results.json")
    else:
        gen_levels = conc.get("generation", [])
        if gen_levels:
            ok_upto = max((r["users"] for r in gen_levels if r["error_rate"] == 0), default=0)
            add("Concurrent generation", "info: bounded admission control",
                PASS if ok_upto >= 2 else FAIL,
                f"0 errors up to {ok_upto} users; "
                + ", ".join(f"{r['users']}u: {r['errors']}" for r in gen_levels if r["errors"]),
                "results/concurrency/results.json")
        add("Concurrent retrieval", "Tested at multiple loads", NOT_TESTED, "", "results/concurrency/results.json")

    # app / tests / docs ------------------------------------------------------
    if st:
        add("Streamlit application", "Launches successfully", PASS if st["healthy"] and st["page_served"] else FAIL,
            f"healthy in {st.get('seconds_to_healthy')} s", "results/streamlit/launch.json")
    else:
        add("Streamlit application", "Launches successfully", NOT_TESTED, "", "results/streamlit/launch.json")
    if j:
        t = j["totals"]
        add("Automated tests", "Pass", PASS if t["failures"] == 0 and t["errors"] == 0 and t["tests"] > 0 else FAIL,
            f"{t['tests']} tests, {t['failures']} failures, {t['errors']} errors, {t['skipped']} skipped",
            "results/tests/junit.xml")
    else:
        add("Automated tests", "Pass", NOT_TESTED, "", "results/tests/junit.xml")
    missing = [d for d in REQUIRED_DOCS if not (ROOT / d).exists() or (ROOT / d).stat().st_size < 1500]
    add("Documentation", "Complete", PASS if not missing else FAIL,
        "all required documents present" if not missing else f"missing/short: {missing}", "docs/")

    out = R / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "acceptance.json").write_text(json.dumps({"generated_utc": stamp, "criteria": rows}, indent=2))
    md = ["# Acceptance results", "", f"Generated {stamp} by `python scripts/acceptance.py`.", "",
          "| Requirement | Target | Status | Measured | Evidence |", "|---|---|---|---|---|"]
    md += [f"| {r['requirement']} | {r['target']} | **{r['status']}** | {r['measured']} | `{r['evidence']}` |" for r in rows]
    (out / "ACCEPTANCE.md").write_text("\n".join(md) + "\n")
    for r in rows:
        print(f"{r['status']:10s} {r['requirement']:32s} {r['measured']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
