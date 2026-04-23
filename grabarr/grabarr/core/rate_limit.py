"""Async token-bucket rate limiter used by every adapter.

Per Constitution Article XII and spec FR-035, each external source has a
per-(adapter, kind) budget. ``acquire(adapter_id, kind)`` blocks the
calling coroutine until a token is available; ``try_acquire()`` is the
non-blocking variant.

The buckets persist only in memory — on restart the budget resets, which
is intentional (the spec does not require persistent rate limits).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class TokenBucket:
    """A single bucket: ``capacity`` tokens refilled at ``refill_rate``/sec."""

    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: float = 1.0) -> None:
        """Block until ``n`` tokens are available, then consume them."""
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= n:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.refill_rate
            # Release the lock while sleeping so other tasks can check.
            await asyncio.sleep(max(wait, 0.01))

    async def try_acquire(self, n: float = 1.0) -> bool:
        """Consume tokens if available; return False otherwise."""
        async with self._lock:
            self._refill()
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


class RateLimiter:
    """Registry of ``TokenBucket`` instances keyed by ``(adapter, kind)``.

    Buckets are created lazily on first ``acquire``; :meth:`configure`
    lets the caller provide capacity + refill rate up front (populated at
    startup from the ``settings`` table).
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._config: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    def configure(
        self,
        adapter_id: str,
        kind: str,
        *,
        per_minute: float | None = None,
        capacity: float | None = None,
    ) -> None:
        """Pre-declare a bucket's shape.

        ``per_minute`` is converted to tokens/sec; ``capacity`` defaults
        to ``per_minute`` (i.e. one-minute worth of burst).
        """
        rate = (per_minute or 60.0) / 60.0
        cap = capacity if capacity is not None else (per_minute or 60.0)
        self._config[(adapter_id, kind)] = (cap, rate)

    async def acquire(self, adapter_id: str, kind: str = "search", n: float = 1.0) -> None:
        bucket = await self._get_or_create(adapter_id, kind)
        await bucket.acquire(n)

    async def try_acquire(
        self, adapter_id: str, kind: str = "search", n: float = 1.0
    ) -> bool:
        bucket = await self._get_or_create(adapter_id, kind)
        return await bucket.try_acquire(n)

    async def _get_or_create(self, adapter_id: str, kind: str) -> TokenBucket:
        key = (adapter_id, kind)
        existing = self._buckets.get(key)
        if existing is not None:
            return existing
        async with self._lock:
            # Re-check under the lock to avoid double-create.
            existing = self._buckets.get(key)
            if existing is not None:
                return existing
            cap, rate = self._config.get(key, (60.0, 1.0))
            bucket = TokenBucket(capacity=cap, refill_rate=rate)
            self._buckets[key] = bucket
            return bucket


# Global registry — adapters import this and call
# ``await rate_limiter.acquire(self.id, "search")``.
rate_limiter = RateLimiter()
