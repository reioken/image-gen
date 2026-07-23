"""Bridge between the Qt UI thread and the asyncio engine.

Threading model (the single most important GUI design point):

* Qt owns the **main/UI thread** and its own event loop.
* We start **one dedicated background thread** that runs a private asyncio event
  loop for the whole app's lifetime.
* Exactly **one** :class:`GlobalScheduler` lives in that loop and is shared by
  every tab, so per-provider rate limits are respected no matter how many tabs
  run at once.
* Work is submitted from the UI thread with
  ``asyncio.run_coroutine_threadsafe(coro, loop)``.
* Results flow back via **Qt signals**. The scheduler's callbacks run in the
  background thread and only ever ``emit`` signals — they never touch widgets.
  Because :class:`AsyncBridge` is a ``QObject`` created on the UI thread, those
  emits are delivered as queued slot calls on the UI thread (thread-safe).
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import Future
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.budget import BudgetManager
from ..core.config import AppConfig
from ..core.metadata import MetadataWriter
from ..core.models import GenerationTask
from ..core.scheduler import BatchResult, GlobalScheduler, SchedulerCallbacks
from ..core.utils.logging import get_logger

log = get_logger(__name__)


class AsyncBridge(QObject):
    """Owns the background loop + the shared scheduler and re-emits progress."""

    # task-level signals. ``object`` carries the GenerationTask (which has tab_id).
    sig_task_started = Signal(object)
    sig_task_succeeded = Signal(object, object, object)  # task, list[SavedImage], record
    sig_task_failed = Signal(object, object)  # task, ErrorRecord
    sig_task_skipped = Signal(object, str)  # task, reason
    sig_progress = Signal(str)
    sig_batch_finished = Signal(str, object)  # tab_id, BatchResult
    sig_budget_changed = Signal(object)  # budget summary dict

    def __init__(
        self,
        config: AppConfig,
        *,
        budget: BudgetManager | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.budget = budget or BudgetManager()
        self.env = env if env is not None else dict(os.environ)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="engine-loop", daemon=True
        )
        self._thread.start()

        callbacks = SchedulerCallbacks(
            on_task_started=self.sig_task_started.emit,
            on_task_succeeded=lambda t, s, r: (
                self.sig_task_succeeded.emit(t, s, r),
                self.sig_budget_changed.emit(self.budget.summary()),
            ),
            on_task_failed=self.sig_task_failed.emit,
            on_task_skipped=self.sig_task_skipped.emit,
            on_progress=self.sig_progress.emit,
        )
        self._scheduler = GlobalScheduler(
            config, budget=self.budget, env=self.env, callbacks=callbacks
        )
        # Bring the shared httpx client up on the loop.
        self.run_coro(self._scheduler.start()).result(timeout=10)

    # --- loop plumbing -----------------------------------------------------
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_coro(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # --- public API (called from the UI thread) ----------------------------
    def run_batch(self, tab_id: str, tasks: list[GenerationTask], out_dir: Path) -> Future:
        async def _go() -> BatchResult:
            writer = MetadataWriter(out_dir)
            try:
                res = await self._scheduler.run_batch(
                    tab_id, tasks, out_dir, metadata_writer=writer
                )
            except asyncio.CancelledError:
                res = BatchResult(tab_id, len(tasks), 0, 0, len(tasks))
            finally:
                try:
                    writer.finalize_csv()
                except Exception:  # noqa: BLE001
                    pass
            self.sig_batch_finished.emit(tab_id, res)
            self.sig_budget_changed.emit(self.budget.summary())
            return res

        return self.run_coro(_go())

    def cancel_tab(self, tab_id: str) -> None:
        self._loop.call_soon_threadsafe(self._scheduler.cancel_tab, tab_id)

    def update_provider_concurrency(self, provider: str, value: int) -> None:
        self._loop.call_soon_threadsafe(
            self._scheduler.update_concurrency, provider, value
        )

    def reset_disabled_providers(self) -> None:
        self._loop.call_soon_threadsafe(self._scheduler.reset_disabled)

    def active_tabs(self) -> list[str]:
        return self._scheduler.active_tabs()

    def shutdown(self) -> None:
        try:
            self.run_coro(self._scheduler.close()).result(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
