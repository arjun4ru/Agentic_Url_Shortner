"""In-memory per-client rate limiting (token bucket).

Deliberately in-process/in-memory rather than Redis-backed: sufficient for a
single-process prototype and consistent with the no-external-dependency
scoping decision in docs/DESIGN.md. Documented limitation: does not
coordinate across multiple processes/instances -- a real production
deployment behind multiple workers would need a shared store (e.g. Redis).
"""

import threading
import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _Bucket(tokens=self.max_requests - 1, last_refill=now)
                return True

            elapsed = now - bucket.last_refill
            refill = (elapsed / self.window_seconds) * self.max_requests
            bucket.tokens = min(self.max_requests, bucket.tokens + refill)
            bucket.last_refill = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True
            return False
