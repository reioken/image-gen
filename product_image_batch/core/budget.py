"""Budget tracking and hard spend caps.

The :class:`BudgetManager` is consulted **before** each task is submitted. If a
task's estimated cost would push the running total over the cap, the task is
refused (and logged as skipped) rather than started. Estimated cost accrues on
submit; actual cost (when a provider reports it) can be reconciled later.
"""

from __future__ import annotations

import asyncio


class BudgetExceeded(Exception):
    """Raised/returned when a task would exceed the configured budget cap."""


class BudgetManager:
    """Tracks estimated + actual spend against an optional total cap.

    A ``max_total_cost`` of ``None`` or ``<= 0`` means "no cap".
    ``require_confirmation_over`` is advisory: callers (CLI/GUI) decide whether
    to prompt; the manager just exposes the threshold and the estimate.
    """

    def __init__(
        self,
        max_total_cost: float | None = None,
        require_confirmation_over: float | None = None,
    ) -> None:
        self.max_total_cost = max_total_cost if (max_total_cost or 0) > 0 else None
        self.require_confirmation_over = require_confirmation_over
        self._estimated = 0.0
        self._actual = 0.0
        self._has_unknown = False
        self._lock = asyncio.Lock()

    @property
    def estimated_spend(self) -> float:
        return self._estimated

    @property
    def actual_spend(self) -> float:
        return self._actual

    @property
    def has_unknown_costs(self) -> bool:
        return self._has_unknown

    def can_afford(self, next_cost: float) -> bool:
        if self.max_total_cost is None:
            return True
        return (self._estimated + next_cost) <= self.max_total_cost + 1e-9

    def try_reserve(self, next_cost: float, *, known: bool = True) -> bool:
        """Reserve budget for a task synchronously. Returns False if unaffordable."""
        if not self.can_afford(next_cost):
            return False
        self._estimated += max(next_cost, 0.0)
        if not known:
            self._has_unknown = True
        return True

    async def reserve(self, next_cost: float, *, known: bool = True) -> bool:
        async with self._lock:
            return self.try_reserve(next_cost, known=known)

    def record_actual(self, cost: float | None) -> None:
        if cost is not None:
            self._actual += max(cost, 0.0)

    def release(self, cost: float) -> None:
        """Give back a reservation (e.g. a task that was skipped/failed free)."""
        self._estimated = max(0.0, self._estimated - max(cost, 0.0))

    def summary(self) -> dict:
        return {
            "estimated_spend_usd": round(self._estimated, 4),
            "actual_spend_usd": round(self._actual, 4),
            "max_total_cost_usd": self.max_total_cost,
            "has_unknown_costs": self._has_unknown,
        }
