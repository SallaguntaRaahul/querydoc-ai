"""QueryDoc AI — Local PDF Retrieval-Augmented Generation System.

Author: Raahul Sallagunta
"""

import os as _os
import sys as _sys

# FAISS and PyTorch wheels for macOS each bundle their own libomp. Loading both
# with multi-threaded OpenMP segfaults (faiss first) or deadlocks (torch first).
# Pinning OpenMP to one thread at import time avoids the clash; torch's
# intra-op thread pool is re-enlarged afterwards via torch.set_num_threads()
# (see querydoc.embeddings.embedder.configure_torch_threads).
if _sys.platform == "darwin":
    _os.environ.setdefault("OMP_NUM_THREADS", "1")
_os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

__version__ = "0.1.0"
__author__ = "Raahul Sallagunta"
