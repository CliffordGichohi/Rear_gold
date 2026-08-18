from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class _Entry[V]:
    expires_at: float
    value: V


class AsyncTtlCache[K: Hashable, V]:
    """Small process-local cache that coalesces identical live calculations."""

    def __init__(self, *, ttl_seconds: float, max_entries: int = 32) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[K, _Entry[V]] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        key: K,
        factory: Callable[[], Awaitable[V]],
    ) -> V:
        now = monotonic()
        cached = self._entries.get(key)
        if cached is not None and cached.expires_at > now:
            return cached.value

        async with self._lock:
            now = monotonic()
            cached = self._entries.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value
            value = await factory()
            self._remove_expired(now)
            if len(self._entries) >= self._max_entries:
                oldest_key = min(
                    self._entries,
                    key=lambda candidate: self._entries[candidate].expires_at,
                )
                del self._entries[oldest_key]
            self._entries[key] = _Entry(
                expires_at=monotonic() + self._ttl_seconds,
                value=value,
            )
            return value

    def _remove_expired(self, now: float) -> None:
        expired = [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]
        for key in expired:
            del self._entries[key]
