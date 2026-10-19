# Experiments

**Project:** QueryDoc AI · **Author:** Raahul Sallagunta

Every number here is copied from a result file under `results/`; the command that
produced it is stored in that file (`"command"`) together with the hardware/software
environment. Hardware for all runs: Apple M3 Pro (11 CPU cores, integrated GPU via
MPS), 18 GB RAM, macOS 26.5, Python 3.12, PyTorch 2.14, under real background load
(6.7–8.9 GB swap in use at the start of runs, recorded per file).

---

## E1. Retrieval quality: baseline vs. optimized (`results/relevance/`)

**Question.** How much does the retrieval pipeline improve the relevance of the context given to the LLM?

**Setup.**
- Corpus: four public-domain NIST publications indexed together (AI 100-1 48 pp., SP 800-63B 80 pp., SP 800-61r2 80 pp., SP 800-37r2 183 pp.; 391 pages).
- Questions: 63, each with verbatim evidence spans (`eval/questions.json`). Dev = odd ids (32), test = even ids (31).
- Relevance: a chunk is relevant if it covers ≥ 50% of an evidence span's characters (chunk-size independent).
- Primary metric "Context Relevance" = mean nDCG@5, defined in commit `ffad4b0` **before** any experiment ran.
- Grid: 10 chunking configs × 10 retrieval configs = 100 pipelines, all on the same questions and corpus.
- Selection rule (automatic): best **dev** nDCG@5 among pipelines whose mean latency during the sweep was ≤ 150 ms (half the 300 ms p95 budget). Test numbers were never used to choose.
- Baseline: LangChain-default-style recursive chunking 1000/200 + dense MiniLM + FAISS top-5.

**Result** (selected: `recursive-1000-200 | hybrid+rerank@20` = BM25+dense RRF fusion, overlap dedup, cross-encoder rerank of the top 20):

| Split | Metric | Baseline | Optimized | Relative | Absolute |
|---|---|---|---|---|---|
| **test (held out, n=31)** | **nDCG@5** | **0.578** | **0.831** | **+43.8%** (95% CI +16.6% … +90.6%) | +25.3 pts |
| test | Hit@5 | 0.677 | 1.000 | +47.6% | +32.3 pts |
| test | MRR | 0.574 | 0.802 | +39.8% | +22.8 pts |
| test | Precision@5 | 0.148 | 0.219 | +47.8% | +7.1 pts |
| dev (used for selection, n=32) | nDCG@5 | 0.622 | 0.811 | +30.3% (CI +9.6 … +61.3%) | +18.9 pts |
| all (n=63) | nDCG@5 | 0.601 | 0.821 | +36.7% (CI +19.1 … +61.7%) | +22.0 pts |
| all | Hit@5 | 0.730 | 0.968 | +32.6% | +23.8 pts |

**Interpretation — read this before quoting the number.**
- The pre-registered criterion (≥ 40% on the held-out test split) is met: +43.8%.
- The improvement is real (every CI excludes 0) but its size is uncertain: with 31 test questions the 95% CI spans +17% to +91%. On all 63 questions the gain is +36.7%, i.e. **below 40%**. The dev/test difference is sampling noise in a small benchmark, not evidence that the test split is "easier" for the optimized system (the baseline does worse on test).
- Recall@5 equals Hit@5 here because almost every question has a single evidence location.

**Retrieval-stage ablation at 1000/200 (nDCG@5, all 63; mean latency during the sweep, reranker on MPS):**

| Pipeline | dev | test | all | Hit@5 | MRR | mean ms |
|---|---|---|---|---|---|---|
| dense (baseline) | 0.622 | 0.578 | 0.601 | 0.730 | 0.589 | 4.9 |
| dense + dedup | 0.622 | 0.578 | 0.601 | 0.730 | 0.589 | 8.6 |
| dense + MMR | 0.573 | 0.582 | 0.578 | 0.683 | 0.582 | 9.2 |
| hybrid (BM25 + dense, RRF) | 0.629 | 0.724 | 0.675 | 0.857 | 0.649 | 16.2 |
| dense + rerank (all 30) | 0.782 | 0.837 | 0.809 | 0.952 | 0.798 | 139.1 |
| dense + rerank@20 | 0.800 | 0.804 | 0.802 | 0.937 | 0.799 | 78.6 |
| hybrid + rerank@10 | 0.787 | 0.791 | 0.789 | 0.889 | 0.786 | 47.3 |
| **hybrid + rerank@20 (selected)** | **0.811** | **0.831** | **0.821** | **0.968** | **0.817** | **86.5** |
| hybrid + rerank (all ≤ 60) | 0.813 | 0.831 | 0.822 | 0.968 | 0.809 | 192.8 |
| hybrid + MMR + rerank | 0.738 | 0.747 | 0.742 | 0.841 | 0.756 | 52.8 |

Conclusions: the cross-encoder is the dominant gain (+20 nDCG points); hybrid adds +7 points alone and +2 on top of reranking; capping reranking at 20 candidates loses 0.002 nDCG while halving rerank cost; MMR **hurts** in every configuration (questions usually have one evidence location, and diversification pushes it out); dedup is neutral at k=5 here.

## E2. Chunk size, overlap and strategy (`results/relevance/`, same questions)

nDCG@5 over all 63 questions:

| Chunking | chunks | dense | hybrid | dense+rerank@20 | hybrid+rerank@20 | hybrid+rerank (all) |
|---|---|---|---|---|---|---|
| **recursive 1000/200** | 1532 | 0.601 | **0.675** | **0.802** | **0.821** | **0.822** |
| recursive 1000/0 | 1425 | 0.539 | 0.590 | 0.707 | 0.759 | 0.755 |
| recursive 750/150 | 2089 | 0.602 | 0.618 | 0.743 | 0.760 | 0.774 |
| recursive 500/100 | 3213 | 0.575 | 0.615 | 0.740 | 0.739 | 0.761 |
| recursive 384/64 | 4227 | 0.525 | 0.505 | 0.652 | 0.681 | 0.715 |
| recursive 256/50 | 6505 | 0.515 | 0.459 | 0.632 | 0.657 | 0.650 |
| fixed 1000/200 | 1382 | 0.511 | 0.599 | 0.701 | 0.767 | 0.771 |
| fixed 500/100 | 2763 | 0.503 | 0.548 | 0.639 | 0.694 | 0.702 |
| sentence 1000/200 | 1398 | 0.535 | 0.570 | 0.710 | 0.747 | 0.761 |
| sentence 500/100 | 2888 | 0.559 | 0.641 | 0.726 | 0.738 | 0.747 |

Findings:
- **Smaller is not better here.** 256–384-character chunks lose 7–17 points: answers in these standards documents often need the surrounding sentence (e.g. a requirement and its AAL), and small chunks fill the top-5 with fragments. ~1,000 characters (≈ 250 MiniLM tokens, just under its 256-token window) was best.
- **Overlap matters:** 1000/200 beats 1000/0 by 6 points dense and 6 points with reranking — facts on chunk boundaries otherwise get split.
- **Recursive beats fixed** (boundaries at sentences vs mid-word) and **beats regex sentence packing** (abbreviations such as "e.g." and "SP 800-63" break the sentence regex).
- Question 35 had no chunk covering ≥ 50% of its evidence span at 750/384/256 sizes (span cut by a boundary) — a measurable cost of small chunks.

## E3. Embedding batch size and peak memory (`results/embeddings/`)

**Setup.** SP 800-37r2 (183 pages → 803 chunks at 1000/200), CPU, fresh subprocess per run, 3 repetitions, psutil RSS sampled every 5 ms. "Working set" = peak minus RSS after model load.

| Strategy | Peak RSS MB (mean ± sd) | Working set MB | chunks/s | seconds |
|---|---|---|---|---|
| single pass (no batching) | 4502 ± 85 | 3734 | 46 | 17.8 |
| batch 1 | 741 ± 58 | 33 | 106 | 7.6 |
| batch 8 | 865 ± 5 | 95 | 103 | 7.8 |
| batch 16 | 880 ± 46 | 118 | 97 | 8.3 |
| batch 32 (SentenceTransformers default) | 962 ± 29 | 205 | 85 | 9.5 |
| batch 64 | 1210 ± 89 | 441 | 93 | 8.7 |
| batch 128 | 1493 ± 153 | 724 | 88 | 9.3 |
| batch 256 | 2056 ± 157 | 1287 | 85 | 9.6 |
| QueryDoc streaming 16 | 938 ± 2 | 170 | 93 | 8.7 |
| **QueryDoc streaming 32 (default)** | **970 ± 1** | **203** | 81 | 10.0 |
| QueryDoc streaming 64 | 1234 ± 123 | 529 | 89 | 9.1 |

Peak-RSS reduction of the default (streaming 32):

| vs | Peak RSS reduction | Throughput change |
|---|---|---|
| unbatched single pass | **−78.5%** | +74.5% |
| batch 256 | −52.8% | −4.7% |
| batch 128 | −35.1% | −7.9% |
| batch 32 (library default) | +0.8% (no difference) | −5.2% |

Findings (honest attribution):
- The saving comes from **bounding the batch size**. Attention activations scale with batch × heads × seq², so one 803-sequence pass needs ~3.7 GB of activations; 32-sequence batches need ~0.2 GB.
- **Larger batches do not use less memory** — memory rises monotonically with batch size — and on this CPU they do not run faster either (throughput is flat at 85–106 chunks/s beyond batch 1, within noise).
- QueryDoc's streaming wrapper (preallocated output, duplicate skipping, cache) gives **no measurable memory benefit over calling `SentenceTransformer.encode(batch_size=32)`** for a single document. Its value is functional: duplicate texts are embedded once and re-uploads hit the cache (not exercised in this benchmark).
- Batch 1 has the lowest memory and, on this machine, the best throughput — a surprise; CPU attention over padded batches wastes work on padding. Batch 32 was kept as the default because it is the library default and within noise on throughput; this is a candidate for retuning.

## E4. Retrieval latency (`results/retrieval_latency/`, `results/retrieval_latency_cpu/`)

200 timed queries × 3 trials after 10 warm-up queries; LLM generation excluded.

Reranker on **MPS (Apple GPU)** — the application default (`reranker_device=auto`):

| Dataset | pages | chunks | baseline dense p50/p95 | optimized p50 | optimized p95 | p99 | cold first query |
|---|---|---|---|---|---|---|---|
| synthetic | 10 | 21 | 6.1 / 6.8 | 36.1 | 48.7 | 67.1 | 317 |
| synthetic | 50 | 103 | 6.0 / 6.6 | 48.7 | 89.9 | 107.5 | 127 |
| synthetic | 100 | 216 | 6.0 / 6.5 | 49.4 | 64.7 | 85.4 | 133 |
| synthetic | 200 | 431 | 6.5 / 7.0 | 49.6 | 54.7 | 74.3 | 131 |
| NIST SP 800-37r2 | 183 | 803 | 6.2 / 6.8 | 79.8 | **128.5** | 144.8 | 188 |
| NIST corpus (4 docs) | 391 | 1532 | 5.9 / 6.4 | 74.6 | **126.8** | 128.3 | 216 |

Reranker on **CPU only**:

| Dataset | pages | optimized p50 | optimized p95 | p99 |
|---|---|---|---|---|
| synthetic | 100 | 150.7 | 166.8 | 171.6 |
| synthetic | 200 | 147.4 | 158.5 | 163.5 |
| NIST SP 800-37r2 | 183 | 273.8 | **556.4** | 598.1 |
| NIST corpus | 391 | 245.0 | **540.5** | 554.4 |

Stage breakdown on the NIST corpus (mean ms): query embedding 5, FAISS search 0.2, BM25+RRF 1.8, dedup 7, rerank 71 (MPS) / 298 (CPU).

Findings:
- FAISS exact search is never the bottleneck (< 0.3 ms at 1.5 k vectors). Latency is the cross-encoder.
- With the GPU, every 100+ page dataset meets p95 < 300 ms with > 2× headroom.
- **CPU-only misses the target on real documents** (p95 ≈ 550 ms): real NIST chunks are longer and denser than synthetic ones (more tokens per rerank pair). CPU-only deployments should use `QUERYDOC_RERANK_K=10` or disable reranking (optimized_no_rerank: p95 ≈ 18 ms, nDCG 0.675).
- The cold first query includes lazy initialisation and is reported separately.

## E5. Ingestion throughput (`results/ingestion/`)

3 repetitions, cold embedding cache, CPU embeddings, 1000/200 chunking.

| Document | pages | chunks | total s | extract s | embed s | pages/s |
|---|---|---|---|---|---|---|
| synthetic | 10 | 21 | 0.17 | 0.04 | 0.13 | 59 |
| synthetic | 100 | 216 | 1.80 | 0.34 | 1.45 | 56 |
| synthetic | 200 | 431 | 3.51 | 0.67 | 2.82 | 57 |
| NIST AI 100-1 | 48 | 148 | 1.60 | 0.24 | 1.35 | 30 |
| NIST SP 800-61r2 | 80 | 321 | 3.84 | 0.53 | 3.24 | 21 |
| NIST SP 800-63B | 80 | 260 | 3.28 | 0.48 | 2.79 | 24 |
| NIST SP 800-37r2 | 183 | 803 | 10.76 | 1.51 | 9.23 | 17 |

Embedding is 80–86% of ingestion time; extraction scales linearly (~8 ms/page).

## E6. Concurrency and E7. Generation

See `docs/PERFORMANCE_REPORT.md` §5–6 (results in `results/concurrency/` and `results/generation/`).

---

## Unsuccessful or rejected approaches

| Approach | Outcome | Evidence |
|---|---|---|
| MMR diversification | −2 to −9 nDCG points in every config | E1/E2 tables |
| Small chunks (256–500 chars) | −6 to −17 points vs 1000/200 | E2 |
| Sentence-packing chunker | below recursive at equal size | E2 |
| Fixed-window chunker | below recursive at equal size | E2 |
| Hybrid + rerank over all candidates | +0.001 nDCG for 2.2× rerank cost | E1 |
| Reranking only top 10 | −3 points vs top 20 | E1 |
| Large embedding batches for speed | no throughput gain on CPU, +1–3.3 GB memory | E3 |
| Plain `get_text("text")` extraction | rotated watermark spliced into sentences | TROUBLESHOOTING #4 |
| `\n` ranked above `. ` in the splitter | facts split across chunks | TROUBLESHOOTING #5 |
| CPU reranking on real documents | p95 ≈ 550 ms (misses 300 ms) | E4 |

## Process notes (transparency)

- An exploratory sweep (`results/exploratory/relevance_sweep_v1_partial.log`) ran before the final one, with the reranker on CPU and an earlier text-cleaning version. It printed test-split numbers, so the author had seen test results before adding the latency-capped variants and the soft-wrap fix. The final selection was still made by the automatic dev-only rule, and the selected configuration (`recursive-1000-200 | hybrid+rerank`) was also the dev-best in the exploratory sweep before any capping.
- The evaluation set is small (63 questions, 4 documents) and was labelled with AI assistance; treat the relevance numbers as indicative, and see the confidence intervals.
