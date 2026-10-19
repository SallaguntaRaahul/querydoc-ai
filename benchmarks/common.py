"""Shared benchmark utilities: environment capture, corpus loading and result IO."""

from __future__ import annotations

import contextlib
import csv
import json
import os
import platform
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import querydoc  # noqa: E402,F401  (applies the macOS OpenMP guard before torch/faiss load)

RESULTS = ROOT / "results"
CORPUS_DIR = ROOT / "data" / "corpus"
EVAL_SET = ROOT / "eval" / "questions.json"


def _pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _hf_revision(repo: str) -> str | None:
    """Commit hash of the locally cached snapshot of a Hugging Face repo."""
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    ref = cache / f"models--{repo.replace('/', '--')}" / "refs" / "main"
    return ref.read_text().strip() if ref.exists() else None


def environment(models: Iterable[str] = ()) -> dict[str, Any]:
    import torch

    cpu = platform.processor()
    if sys.platform == "darwin":
        with contextlib.suppress(Exception):
            cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    try:
        git = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        git = None
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git,
        "os": f"{platform.system()} {platform.release()} ({platform.platform()})",
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": psutil.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "ram_available_gb_at_start": round(psutil.virtual_memory().available / 1024**3, 1),
        "swap_used_gb_at_start": round(psutil.swap_memory().used / 1024**3, 1),
        "python": sys.version.split()[0],
        "torch_threads": torch.get_num_threads(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "mps_available": bool(torch.backends.mps.is_available()),
        "cuda_available": bool(torch.cuda.is_available()),
        "packages": {
            p: _pkg_version(p)
            for p in [
                "torch", "transformers", "sentence-transformers", "faiss-cpu", "pymupdf",
                "langchain-core", "langchain-text-splitters", "numpy", "pandas", "streamlit", "rank-bm25",
            ]
        },
        "models": {m: _hf_revision(m) for m in models},
    }


def write_results(name: str, payload: dict[str, Any], rows: Sequence[dict[str, Any]] | None = None,
                  csv_name: str | None = None) -> Path:
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(payload, indent=2, default=str))
    if rows:
        keys: list[str] = []
        for r in rows:
            keys += [k for k in r if k not in keys]
        with (out / (csv_name or "raw.csv")).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    return out


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def latency_summary(ms: Sequence[float]) -> dict[str, float]:
    import statistics

    return {
        "n": len(ms),
        "mean_ms": statistics.fmean(ms) if ms else float("nan"),
        "stdev_ms": statistics.stdev(ms) if len(ms) > 1 else 0.0,
        "p50_ms": percentile(ms, 50),
        "p95_ms": percentile(ms, 95),
        "p99_ms": percentile(ms, 99),
        "max_ms": max(ms) if ms else float("nan"),
    }


class PeakRSSSampler:
    """Samples this process's resident set size in a background thread.

    RSS is what the OS reports as physically resident for the process (includes
    the Python heap, PyTorch/FAISS native allocations and mapped model weights
    that have been touched). Sampling at ``interval_s`` can miss sub-interval
    spikes, so it is a lower bound on the true peak.
    """

    def __init__(self, interval_s: float = 0.005) -> None:
        self.interval_s = interval_s
        self.proc = psutil.Process(os.getpid())
        self.peak = 0
        self.start_rss = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> PeakRSSSampler:
        self.start_rss = self.peak = self.proc.memory_info().rss
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(self.interval_s)

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        self.peak = max(self.peak, self.proc.memory_info().rss)

    @property
    def peak_mb(self) -> float:
        return self.peak / 1024**2

    @property
    def delta_mb(self) -> float:
        return (self.peak - self.start_rss) / 1024**2


@dataclass
class CorpusDoc:
    filename: str
    data: bytes


def load_corpus() -> list[CorpusDoc]:
    files = sorted(CORPUS_DIR.glob("*.pdf"))
    if not files:
        raise SystemExit("Corpus missing. Run: python scripts/download_corpus.py")
    return [CorpusDoc(f.name, f.read_bytes()) for f in files]
