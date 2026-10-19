"""Pre-download the local models into the Hugging Face cache (one time).

Usage: python scripts/download_models.py [--small]
"""

from __future__ import annotations

import sys

from huggingface_hub import snapshot_download

MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "Qwen/Qwen2.5-0.5B-Instruct" if "--small" in sys.argv else "Qwen/Qwen2.5-1.5B-Instruct",
]
PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "merges.txt", "vocab.json", "1_Pooling/*"]

for repo in MODELS:
    print(f"downloading {repo} ...", flush=True)
    path = snapshot_download(repo, allow_patterns=PATTERNS)
    print(f"  cached at {path}")
