"""Admission control for expensive local generation."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from querydoc.exceptions import GenerationTimeoutError, QueueFullError


class GenerationGate:
    """Allows at most ``max_active`` concurrent generations and at most
    ``max_queue`` waiters; further requests fail fast with QueueFullError and
    waiters give up after ``timeout_s`` with GenerationTimeoutError."""

    def __init__(self, max_active: int = 1, max_queue: int = 8, timeout_s: float = 120.0) -> None:
        if max_active < 1:
            raise ValueError("max_active must be >= 1")
        self.max_active = max_active
        self.max_queue = max_queue
        self.timeout_s = timeout_s
        self._slots = threading.BoundedSemaphore(max_active)
        self._lock = threading.Lock()
        self._waiting = 0
        self.active = 0

    @property
    def waiting(self) -> int:
        return self._waiting

    @contextmanager
    def slot(self) -> Iterator[float]:
        """Yields the queue wait time in milliseconds."""
        with self._lock:
            if self._waiting >= self.max_queue:
                raise QueueFullError(
                    f"Generation queue is full ({self.max_queue} waiting). Try again shortly."
                )
            self._waiting += 1
        started = time.perf_counter()
        acquired = self._slots.acquire(timeout=self.timeout_s)
        with self._lock:
            self._waiting -= 1
            if acquired:
                self.active += 1
        if not acquired:
            raise GenerationTimeoutError(f"No generation slot became free within {self.timeout_s:.0f}s.")
        try:
            yield (time.perf_counter() - started) * 1000
        finally:
            with self._lock:
                self.active -= 1
            self._slots.release()
