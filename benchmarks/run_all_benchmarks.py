"""Run every benchmark sequentially (each in its own process) and then the charts.

Usage:  python benchmarks/run_all_benchmarks.py [--skip-generation]
Total runtime on an M3 Pro: roughly 45-60 minutes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-generation", action="store_true")
    args = ap.parse_args()
    steps = [
        ["benchmark_ingestion.py"],
        ["benchmark_embeddings.py"],
        ["benchmark_relevance.py"],
        ["benchmark_retrieval.py"],
        ["benchmark_concurrency.py"] + (["--skip-generation"] if args.skip_generation else []),
    ]
    if not args.skip_generation:
        steps.append(["benchmark_generation.py"])
    steps.append(["make_charts.py"])
    failed = []
    for step in steps:
        print(f"\n=== {' '.join(step)} ===", flush=True)
        t = time.perf_counter()
        rc = subprocess.call([sys.executable, str(HERE / step[0]), *step[1:]])
        print(f"=== {step[0]} exit={rc} in {time.perf_counter() - t:.0f}s ===", flush=True)
        if rc:
            failed.append(step[0])
    print("\nFAILED: " + ", ".join(failed) if failed else "\nAll benchmarks completed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
