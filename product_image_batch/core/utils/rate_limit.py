"""A small dependency-free async rate limiter (token-bucket style).

If ``aiolimiter`` is installed the scheduler can use it, but this fallback keeps
the engine working with zero optional dependencies. It enforces "at most
``max_rate`` acquisitions per ``time_period`` seconds".
"""

from __future__ import annotations

import asyncio
import collections
import time


class AsyncRateLimiter:
    """Sliding-window rate limiter usable as an async context manager.

    Example::

        limiter = AsyncRateLimiter(5, 60)   # 5 requests / 60s
        async with limiter:
            await do_request()
    """

    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        if max_rate <= 0:
            raise ValueError("max_rate must be > 0")
        self.max_rate = max_rate
        self.time_period = time_period
        self._timestamps: collections.deque[float] = collections.deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - self.time_period
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_rate:
                    self._timestamps.append(now)
                    return
                # Need to wait until the oldest timestamp exits the window.
                wait_for = self._timestamps[0] + self.time_period - now
            await asyncio.sleep(max(wait_for, 0.001))

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _NullLimiter:
    """No-op limiter for providers with no configured rate limit."""

    async def acquire(self) -> None:
        return None

    async def __aenter__(self) -> "_NullLimiter":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


NULL_LIMITER = _NullLimiter()
