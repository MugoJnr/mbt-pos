"""Stops repeating a failed cloud call until the cool-down has passed."""
from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(self, failure_limit: int = 3, cool_down_s: float = 30.0):
        self.failure_limit = failure_limit
        self.cool_down_s = cool_down_s
        self.failures = 0
        self.opened_at = 0.0

    def allow(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.failures < self.failure_limit:
            return True
        if now - self.opened_at >= self.cool_down_s:
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = 0.0

    def record_failure(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.failures += 1
        if self.failures >= self.failure_limit:
            self.opened_at = now
