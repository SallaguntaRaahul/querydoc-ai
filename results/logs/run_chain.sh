#!/bin/zsh
cd /Users/raahul/Desktop/Projects/querydoc-ai
source .venv/bin/activate
export HF_HUB_OFFLINE=1 QUERYDOC_LOG_LEVEL=WARNING
F='Loading weights|Redirects|resource_tracker|warnings.warn'
python benchmarks/benchmark_ingestion.py 2>&1 | grep -v -E "$F" > results/logs/ingestion.log
python benchmarks/benchmark_retrieval.py 2>&1 | grep -v -E "$F" > results/logs/retrieval_mps.log
python benchmarks/benchmark_retrieval.py --reranker-device cpu --name retrieval_latency_cpu 2>&1 | grep -v -E "$F" > results/logs/retrieval_cpu.log
python benchmarks/benchmark_embeddings.py 2>&1 | grep -v -E "$F" > results/logs/embeddings.log
echo CHAIN_DONE
