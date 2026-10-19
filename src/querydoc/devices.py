"""Process-wide locks for accelerator devices.

Apple's MPS backend is not safe when two threads submit work at the same time:
running the cross-encoder in one thread while the LLM generates in another
aborts the process with a Metal command-buffer assertion (observed in
benchmarks/benchmark_concurrency.py). Every model wrapper therefore takes the
lock for its device around forward passes. CPU work is not serialised here.
"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, nullcontext

_LOCKS: dict[str, threading.RLock] = {}
_GUARD = threading.Lock()
SERIALISED_DEVICES = {"mps"}


def device_lock(device: str) -> AbstractContextManager[object]:
    """Shared re-entrant lock for ``device`` (a no-op context for CPU/CUDA)."""
    kind = device.split(":")[0]
    if kind not in SERIALISED_DEVICES:
        return nullcontext()
    with _GUARD:
        return _LOCKS.setdefault(kind, threading.RLock())
