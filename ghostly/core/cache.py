from __future__ import annotations

import asyncio
import fnmatch
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class CacheEntry:
    value: Any
    expires_at: float | None = None
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total > 0 else 0.0


class LRUCache:
    """Thread-safe LRU cache with TTL support and cache-aside pattern."""

    def __init__(self, max_size: int = 1024, default_ttl: float | None = None) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._stats = CacheStats()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.expires_at and time.monotonic() > entry.expires_at:
                del self._store[key]
                self._stats.misses += 1
                return None
            self._store.move_to_end(key)
            self._stats.hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        async with self._lock:
            effective_ttl = ttl if ttl is not None else self._default_ttl
            expires_at = time.monotonic() + effective_ttl if effective_ttl else None
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = CacheEntry(value=value, expires_at=expires_at)
            self._evict_if_needed()
            self._stats.size = len(self._store)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                self._stats.size = len(self._store)
                return True
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        async with self._lock:
            keys_to_remove = [
                k for k in self._store
                if fnmatch.fnmatch(k, pattern)
            ]
            for k in keys_to_remove:
                del self._store[k]
            self._stats.size = len(self._store)
            return len(keys_to_remove)

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: float | None = None,
    ) -> Any:
        value = await self.get(key)
        if value is not None:
            return value
        value = await factory()
        await self.set(key, value, ttl=ttl)
        return value

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            self._stats.size = 0
            return count

    def stats(self) -> dict[str, Any]:
        return {
            "hits": self._stats.hits,
            "misses": self._stats.misses,
            "size": self._stats.size,
            "max_size": self._max_size,
            "hit_rate": self._stats.hit_rate,
        }

    def _evict_if_needed(self) -> None:
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    @property
    def size(self) -> int:
        return len(self._store)
