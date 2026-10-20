"""In-process sliding-window rate limiter (single server process)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import APIError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float, what: str = "requests") -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window_s - (now - hits[0])) + 1
                raise APIError(429, "rate_limited", f"Too many {what}. Try again in {retry} s.", {"retry_after_s": retry})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
