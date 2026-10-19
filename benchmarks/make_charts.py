"""Render PNG charts from results/*/results.json into docs/images/.

Colors: categorical slots 1-3 of the validated reference palette (blue, orange,
aqua), light surface. Every chart with >= 2 series has a legend; values are
direct-labeled selectively; there is never a second y-axis.

Usage:  python benchmarks/make_charts.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "images"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
TARGET = "#52514e"


def style(ax, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def fig(w: float = 8, h: float = 4.2):
    f, ax = plt.subplots(figsize=(w, h), dpi=150)
    f.patch.set_facecolor(SURFACE)
    return f, ax


def load(name: str) -> dict | None:
    p = RES / name / "results.json"
    return json.loads(p.read_text()) if p.exists() else None


def bars(ax, groups: list[str], series: dict[str, list[float]], colors: list[str], fmt: str = "{:.2f}",
         label_series: set[str] | None = None) -> None:
    n = len(series)
    width = 0.8 / n
    for i, ((name, vals), color) in enumerate(zip(series.items(), colors, strict=False)):
        xs = [g + (i - (n - 1) / 2) * width for g in range(len(groups))]
        rects = ax.bar(xs, vals, width * 0.92, color=color, label=name, edgecolor=SURFACE, linewidth=1)
        if label_series is None or name in label_series:
            ax.bar_label(rects, labels=[fmt.format(v) for v in vals], fontsize=7, color=INK2, padding=2)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups, fontsize=8)


def relevance_chart(rel: dict) -> None:
    metrics = ["hit@5", "precision@5", "recall@5", "mrr", "ndcg@5"]
    t = rel["comparison"]["test"]
    f, ax = fig()
    bars(ax, metrics, {"Baseline (recursive 1000/200, dense top-5)": [t["baseline"][m] for m in metrics],
                       f"Optimized ({rel['optimized_selected_on_dev']})": [t["optimized"][m] for m in metrics]},
         [S1, S2])
    style(ax, "Retrieval quality on held-out test questions (n=31)", "score")
    ax.set_ylim(0, 1.1)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    f.tight_layout()
    f.savefig(OUT / "relevance_baseline_vs_optimized.png")
    plt.close(f)

    # chunking sweep: nDCG@5 (all questions) for dense vs hybrid+rerank
    summ = rel["summary"]
    chunkings = list(rel["index_info"])
    f, ax = fig(9, 4.2)
    bars(ax, [c.replace("recursive", "rec").replace("sentence", "sent") for c in chunkings],
         {"dense": [summ[f"{c}|dense"]["all"]["ndcg@5"] for c in chunkings],
          "hybrid": [summ[f"{c}|hybrid"]["all"]["ndcg@5"] for c in chunkings],
          "hybrid+rerank": [summ[f"{c}|hybrid+rerank"]["all"]["ndcg@5"] for c in chunkings]},
         [S1, S2, S3], label_series={"hybrid+rerank"})
    style(ax, "nDCG@5 by chunking strategy (all 63 questions)", "nDCG@5")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    f.tight_layout()
    f.savefig(OUT / "relevance_chunking_sweep.png")
    plt.close(f)


def latency_chart(lat: dict) -> None:
    summ = lat["summary"]
    datasets = list(dict.fromkeys(v["dataset"] for v in summ.values()))
    f, ax = fig(9, 4.2)
    bars(ax, [d.replace("synthetic_", "syn ").replace("nist_", "") for d in datasets],
         {"baseline dense p95": [summ[f"{d}|baseline_dense"]["pooled"]["p95_ms"] for d in datasets],
          "optimized (hybrid+rerank) p50": [summ[f"{d}|optimized"]["pooled"]["p50_ms"] for d in datasets],
          "optimized (hybrid+rerank) p95": [summ[f"{d}|optimized"]["pooled"]["p95_ms"] for d in datasets]},
         [S1, S3, S2], fmt="{:.0f}", label_series={"optimized (hybrid+rerank) p95"})
    ax.axhline(300, color=TARGET, linestyle="--", linewidth=1)
    ax.text(len(datasets) - 0.5, 305, "300 ms target", fontsize=7, color=TARGET, ha="right", va="bottom")
    style(ax, f"Warm retrieval latency by document size, reranker on {lat.get('reranker_device', 'cpu').upper()} "
              "(excludes LLM generation)", "milliseconds")
    ax.set_ylim(0, 420)
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=3)
    f.tight_layout()
    f.savefig(OUT / "retrieval_latency.png")
    plt.close(f)


def memory_chart(emb: dict) -> None:
    agg = emb["aggregate"]
    names = list(agg)
    f, ax = fig(9, 4.2)
    vals = [agg[n]["peak_rss_mb"]["mean"] for n in names]
    colors = [S2 if n == "single_pass" else (S3 if n.startswith("streaming") else S1) for n in names]
    rects = ax.bar(range(len(names)), vals, 0.7, color=colors, edgecolor=SURFACE)
    ax.bar_label(rects, labels=[f"{v:.0f}" for v in vals], fontsize=7, color=INK2, padding=2)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, fontsize=8, rotation=25, ha="right")
    style(ax, f"Peak process RSS while embedding {emb['document']} ({agg[names[0]]['chunks']} chunks)", "MB")
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=S2, label="unbatched single pass"),
                       Patch(color=S1, label="SentenceTransformer.encode(batch_size=N)"),
                       Patch(color=S3, label="QueryDoc streaming mini-batches")],
              frameon=False, fontsize=8, loc="upper right")
    f.tight_layout()
    f.savefig(OUT / "embedding_peak_memory.png")
    plt.close(f)

    f, ax = fig(9, 4.2)
    vals = [agg[n]["chunks_per_second"]["mean"] for n in names]
    rects = ax.bar(range(len(names)), vals, 0.7, color=colors, edgecolor=SURFACE)
    ax.bar_label(rects, labels=[f"{v:.0f}" for v in vals], fontsize=7, color=INK2, padding=2)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, fontsize=8, rotation=25, ha="right")
    style(ax, "Embedding throughput by strategy (CPU)", "chunks per second")
    f.tight_layout()
    f.savefig(OUT / "embedding_throughput.png")
    plt.close(f)


def concurrency_chart(conc: dict) -> None:
    r = conc["retrieval"]
    users = [x["users"] for x in r]
    f, ax = fig(8, 4)
    ax.plot(users, [x["throughput_rps"] for x in r], color=S1, linewidth=2, marker="o", markersize=6)
    for u, x in zip(users, r, strict=True):
        ax.annotate(f"{x['throughput_rps']:.0f}", (u, x["throughput_rps"]), textcoords="offset points",
                    xytext=(0, 7), fontsize=7, color=INK2, ha="center")
    style(ax, "Retrieval throughput vs concurrent users (0 errors at every level)", "requests per second")
    ax.set_xlabel("concurrent users", color=INK2, fontsize=9)
    ax.set_xticks(users)
    ax.set_ylim(0, max(x["throughput_rps"] for x in r) * 1.25)
    f.tight_layout()
    f.savefig(OUT / "concurrency_throughput.png")
    plt.close(f)

    f, ax = fig(8, 4)
    ax.plot(users, [x["latency"]["p50_ms"] for x in r], color=S3, linewidth=2, marker="o", markersize=6, label="p50")
    ax.plot(users, [x["latency"]["p95_ms"] for x in r], color=S2, linewidth=2, marker="o", markersize=6, label="p95")
    style(ax, "Retrieval latency vs concurrent users", "milliseconds")
    ax.set_xlabel("concurrent users", color=INK2, fontsize=9)
    ax.set_xticks(users)
    ax.legend(frameon=False, fontsize=8)
    f.tight_layout()
    f.savefig(OUT / "concurrency_latency.png")
    plt.close(f)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("relevance", relevance_chart), ("retrieval_latency", latency_chart),
                     ("embeddings", memory_chart), ("concurrency", concurrency_chart)]:
        data = load(name)
        if data:
            fn(data)
            print(f"chart: {name}")
        else:
            print(f"skip: {name} (no results)")


if __name__ == "__main__":
    main()
