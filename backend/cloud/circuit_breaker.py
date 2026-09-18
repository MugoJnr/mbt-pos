"""
Per-service circuit breaker for cloud / connectivity probes.

Prevents tight retry loops when DNS/HTTP fails offline or against dead hosts.
"""
from __future__ import annotations

import threading
import time
from typing import Optional


# attempt index → seconds to wait before next try
_DEFAULT_BACKOFF = (5, 15, 60, 300, 600)


class CircuitBreaker:
    """Thread-safe failure counter with exponential backoff."""

    def __init__(
        self,
        name: str,
        *,
        backoff: tuple[int, ...] = _DEFAULT_BACKOFF,
        open_after: int = 3,
    ):
        self.name = name
        self._backoff = tuple(int(x) for x in backoff) or (5,)
        self._open_after = max(1, int(open_after))
        self._lock = threading.Lock()
        self._failures = 0
        self._next_allowed = 0.0
        self._opened_at = 0.0

    def allow(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._next_allowed

    def seconds_until_retry(self) -> float:
        with self._lock:
            return max(0.0, self._next_allowed - time.monotonic())

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._next_allowed = 0.0
            self._opened_at = 0.0

    def record_failure(self) -> float:
        """Record a failure; return seconds until next allowed attempt."""
        with self._lock:
            self._failures += 1
            idx = min(self._failures - 1, len(self._backoff) - 1)
            wait = float(self._backoff[idx])
            if self._failures >= self._open_after and not self._opened_at:
                self._opened_at = time.monotonic()
            self._next_allowed = time.monotonic() + wait
            return wait

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._failures >= self._open_after

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'name': self.name,
                'failures': self._failures,
                'open': self._failures >= self._open_after,
                'retry_in': max(0.0, self._next_allowed - time.monotonic()),
            }


_REGISTRY: dict[str, CircuitBreaker] = {}
_REG_LOCK = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    with _REG_LOCK:
        br = _REGISTRY.get(name)
        if br is None:
            br = CircuitBreaker(name)
            _REGISTRY[name] = br
        return br
