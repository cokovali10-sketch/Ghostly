from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
# --- константы вынесены FORGE refactor ---
CONST_60 = 60.0
CONST_3600 = 3600.0



@dataclass
class TokenBucket:
    capacity: float
    rate: float
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def consume(self, now: float | None = None) -> tuple[bool, float]:
        now = now or time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, self.tokens
        return False, self.tokens

    def refill(self, now: float | None = None) -> None:
        now = now or time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now


@dataclass
class SlidingWindowCounter:
    window_size: float
    max_requests: int
    _requests: list[float] = field(default_factory=list)

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.window_size
        self._requests = [t for t in self._requests if t > cutoff]

    def allow(self, now: float | None = None) -> tuple[bool, int]:
        now = now or time.monotonic()
        self._cleanup(now)
        remaining = self.max_requests - len(self._requests)
        if remaining > 0:
            self._requests.append(now)
            return True, remaining - 1
        return False, 0

    @property
    def reset_time(self) -> float:
        if self._requests:
            return self._requests[0] + self.window_size
        return time.monotonic()


class RateLimiter:
    """Token bucket and sliding window rate limiter with per-IP and per-user limits."""

    WINDOW_SECONDS: dict[str, float] = {
        "1s": 1.0,
        "1m": CONST_60,
        "1h": CONST_3600,
    }

    def __init__(
        self,
        requests_per_minute: int = CONST_60,
        requests_per_hour: int = 1000,
        burst_size: int = 10,
    ) -> None:
        self._requests_per_minute = requests_per_minute
        self._requests_per_hour = requests_per_hour
        self._burst_size = burst_size
        self._buckets: dict[str, TokenBucket] = {}
        self._sliding_windows: dict[str, SlidingWindowCounter] = {}
        self._lock = asyncio.Lock()

    def _get_bucket(self, key: str, capacity: float, rate: float) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(capacity=capacity, rate=rate)
        return self._buckets[key]

    def _get_sliding_window(
        self, key: str, window_size: float, max_requests: int
    ) -> SlidingWindowCounter:
        if key not in self._sliding_windows:
            self._sliding_windows[key] = SlidingWindowCounter(
                window_size=window_size, max_requests=max_requests
            )
        return self._sliding_windows[key]

    async def check(
        self,
        identifier: str,
        scope: str = "global",
        window: str = "1m",
    ) -> dict[str, Any]:
        key = f"{scope}:{identifier}"
        window_seconds = self.WINDOW_SECONDS.get(window, CONST_60)

        if window == "1s":
            capacity = self._burst_size
            rate = self._burst_size
        elif window == "1h":
            capacity = self._requests_per_hour
            rate = self._requests_per_hour / CONST_3600
        else:
            capacity = self._requests_per_minute
            rate = self._requests_per_minute / CONST_60

        async with self._lock:
            bucket = self._get_bucket(key, capacity, rate)
            allowed, remaining = bucket.consume()

            reset_time = time.monotonic() + (1.0 / rate if rate > 0 else CONST_60)

            return {
                "allowed": allowed,
                "remaining": max(0, int(remaining)),
                "limit": int(capacity),
                "reset": int(reset_time),
                "window": window,
            }

    async def check_sliding_window(
        self,
        identifier: str,
        scope: str = "global",
        window: str = "1m",
    ) -> dict[str, Any]:
        key = f"{scope}:{identifier}"
        window_seconds = self.WINDOW_SECONDS.get(window, CONST_60)

        if window == "1s":
            max_requests = self._burst_size
        elif window == "1h":
            max_requests = self._requests_per_hour
        else:
            max_requests = self._requests_per_minute

        async with self._lock:
            counter = self._get_sliding_window(key, window_seconds, max_requests)
            allowed, remaining = counter.allow()

            return {
                "allowed": allowed,
                "remaining": remaining,
                "limit": max_requests,
                "reset": int(counter.reset_time),
                "window": window,
            }

    def get_rate_limit_headers(self, result: dict[str, Any]) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(result.get("limit", 0)),
            "X-RateLimit-Remaining": str(result.get("remaining", 0)),
            "X-RateLimit-Reset": str(result.get("reset", 0)),
        }

    async def cleanup_expired(self, max_age: float = 7200.0) -> int:
        async with self._lock:
            now = time.monotonic()
            expired_buckets = [
                k for k, v in self._buckets.items()
                if now - v.last_refill > max_age
            ]
            for k in expired_buckets:
                del self._buckets[k]
            return len(expired_buckets)
