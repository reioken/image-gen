"""GlobalScheduler — one shared scheduler for the whole app.

Why global? If every GUI tab had its own scheduler with its own per-provider
semaphores, opening N tabs would multiply the effective per-provider concurrency
by N and blow past documented rate limits (e.g. Stability's 150 req/10s,
Ideogram's 10 inflight). Instead there is exactly one scheduler with **one
semaphore set per provider**, shared no matter how many tabs submit work.

Responsibilities:
* one shared ``httpx.AsyncClient`` (connection pooling) for all providers;
* a global concurrency cap plus a per-provider semaphore and optional rate limiter;
* retry with exponential backoff + jitter, honoring ``Retry-After``;
* budget reservation before each task;
* incremental metadata/error logging;
* per-task progress callbacks that carry ``tab_id`` so the GUI can route results;
* per-tab cancellation (Stop button) without touching other tabs.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from .assets import prepare_assets
from .budget import BudgetManager
from .config import AppConfig
from .errors import ProviderError
from .metadata import (
    MetadataWriter,
    utc_now_iso,
    utc_timestamp_compact,
)
from .models import (
    ErrorRecord,
    GenerationTask,
    MetadataRecord,
    PreparedAssets,
    ProviderResult,
    SavedImage,
    TaskStatus,
)
from .providers.registry import create_provider, resolve_api_key
from .utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class SchedulerCallbacks:
    """Optional hooks the GUI/CLI can supply. All are best-effort and may be
    called from the scheduler's event-loop thread — GUI callers must marshal to
    the UI thread via Qt signals themselves.
    """

    on_task_started: Callable[[GenerationTask], None] | None = None
    on_task_succeeded: Callable[[GenerationTask, list[SavedImage], MetadataRecord], None] | None = None
    on_task_failed: Callable[[GenerationTask, ErrorRecord], None] | None = None
    on_task_skipped: Callable[[GenerationTask, str], None] | None = None
    on_progress: Callable[[str], None] | None = None

    def _safe(self, fn, *args) -> None:
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 — never let a UI callback crash a run
            log.exception("scheduler callback raised")


@dataclass
class BatchResult:
    tab_id: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    saved_images: list[SavedImage] = field(default_factory=list)


class GlobalScheduler:
    def __init__(
        self,
        config: AppConfig,
        *,
        budget: BudgetManager | None = None,
        env: dict[str, str] | None = None,
        callbacks: SchedulerCallbacks | None = None,
    ) -> None:
        self.config = config
        self.budget = budget or BudgetManager()
        self.env = env if env is not None else dict(__import__("os").environ)
        self.callbacks = callbacks or SchedulerCallbacks()

        self._global_sem = asyncio.Semaphore(max(1, config.global_max_concurrent))
        self._provider_sems: dict[str, asyncio.Semaphore] = {}
        self._provider_limiters: dict[str, object] = {}
        for name, prov in config.providers.items():
            self._provider_sems[name] = asyncio.Semaphore(max(1, prov.max_concurrent))
            self._provider_limiters[name] = _make_limiter(prov)

        self._client: httpx.AsyncClient | None = None
        self._disabled_providers: set[str] = set()
        # tab_id -> set of live asyncio.Tasks for that tab (for cancellation).
        self._tab_tasks: dict[str, set[asyncio.Task]] = {}
        # cache of PreparedAssets keyed by tab_id so refs are encoded once/tab.
        self._assets_cache: dict[str, PreparedAssets] = {}

    # --- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._client is None:
            limits = httpx.Limits(max_connections=100, max_keepalive_connections=40)
            self._client = httpx.AsyncClient(limits=limits, follow_redirects=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "GlobalScheduler":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GlobalScheduler.start() must be called first")
        return self._client

    # --- provider control --------------------------------------------------
    def update_concurrency(self, provider: str, max_concurrent: int) -> None:
        """Change a provider's semaphore at runtime (new tasks only)."""
        max_concurrent = max(1, int(max_concurrent))
        self._provider_sems[provider] = asyncio.Semaphore(max_concurrent)
        if provider in self.config.providers:
            self.config.providers[provider].max_concurrent = max_concurrent

    def reset_disabled(self) -> None:
        self._disabled_providers.clear()

    # --- assets ------------------------------------------------------------
    async def prepare_tab_assets(
        self, tab_id: str, references: list[Path], mask: Path | None
    ) -> PreparedAssets:
        assets = await prepare_assets(references, mask)
        self._assets_cache[tab_id] = assets
        return assets

    # --- cancellation ------------------------------------------------------
    def cancel_tab(self, tab_id: str) -> int:
        tasks = self._tab_tasks.get(tab_id, set())
        n = 0
        for t in list(tasks):
            if not t.done():
                t.cancel()
                n += 1
        return n

    def active_tabs(self) -> list[str]:
        return [tid for tid, ts in self._tab_tasks.items() if any(not t.done() for t in ts)]

    # --- batch execution ---------------------------------------------------
    async def run_batch(
        self,
        tab_id: str,
        tasks: list[GenerationTask],
        out_dir: Path,
        *,
        metadata_writer: MetadataWriter | None = None,
    ) -> BatchResult:
        """Run all ``tasks`` (from one tab) concurrently, respecting all limits."""
        await self.start()
        writer = metadata_writer or MetadataWriter(out_dir)
        result = BatchResult(tab_id=tab_id, total=len(tasks), succeeded=0, failed=0, skipped=0)

        tab_set = self._tab_tasks.setdefault(tab_id, set())
        coros = [
            self._run_one_task(task, out_dir, writer, result) for task in tasks
        ]
        atasks = [asyncio.ensure_future(c) for c in coros]
        tab_set.update(atasks)
        try:
            await asyncio.gather(*atasks, return_exceptions=True)
        finally:
            for t in atasks:
                tab_set.discard(t)
        return result

    async def _run_one_task(
        self,
        task: GenerationTask,
        out_dir: Path,
        writer: MetadataWriter,
        result: BatchResult,
    ) -> None:
        cb = self.callbacks
        provider_name = task.provider

        if provider_name in self._disabled_providers:
            await self._skip(task, "provider disabled after auth error", writer, result)
            return

        # Budget check up-front.
        prov_cfg = self.config.providers.get(provider_name)
        api_key = resolve_api_key(provider_name, self.env)
        try:
            adapter = create_provider(provider_name, prov_cfg, api_key=api_key, model=task.model)
        except Exception as exc:  # noqa: BLE001
            await self._fail(task, ProviderError(str(exc), provider=provider_name), writer, result, attempts=0)
            return

        estimate = await adapter.estimate_cost(task)
        reserved = await self.budget.reserve(estimate.amount_usd, known=estimate.known)
        if not reserved:
            await self._skip(
                task,
                f"budget cap reached (est ${estimate.amount_usd:.3f} would exceed cap)",
                writer,
                result,
            )
            return

        cb._safe(cb.on_task_started, task)
        started = utc_now_iso()
        t0 = asyncio.get_event_loop().time()

        try:
            saved, prov_result = await self._execute_with_retry(task, adapter, out_dir)
        except asyncio.CancelledError:
            self.budget.release(estimate.amount_usd)
            await self._cancelled(task, writer, result)
            raise
        except ProviderError as exc:
            self.budget.release(estimate.amount_usd)
            if exc.disables_provider:
                self._disabled_providers.add(provider_name)
                log.warning("Disabling provider %s for the rest of the run: %s", provider_name, exc)
            await self._fail(task, exc, writer, result, attempts=getattr(exc, "_attempts", 1))
            return
        except Exception as exc:  # noqa: BLE001
            self.budget.release(estimate.amount_usd)
            await self._fail(
                task, ProviderError(str(exc), provider=provider_name, model=task.model), writer, result
            )
            return

        latency = asyncio.get_event_loop().time() - t0
        if prov_result.actual_cost_usd is not None:
            self.budget.record_actual(prov_result.actual_cost_usd)

        record = MetadataRecord(
            task_id=task.task_id,
            status=TaskStatus.SUCCESS.value,
            provider=provider_name,
            model=task.model,
            prompt_id=task.prompt_id,
            prompt_text=task.prompt_text,
            rewritten_prompt=task.prompt_text,
            negative_prompt=task.negative_prompt,
            reference_images=[_rel(out_dir, p) for p in task.reference_images],
            mask=_rel(out_dir, task.mask_path) if task.mask_path else None,
            parameters={
                "size": task.size,
                "quality": task.quality,
                "seed": task.seed,
                "output_format": task.output_format,
                **task.provider_params,
            },
            output_files=[_rel(out_dir, s.path) for s in saved],
            provider_job_id=prov_result.provider_job_id,
            latency_seconds=round(latency, 2),
            estimated_cost_usd=round(estimate.amount_usd, 4),
            actual_cost_usd=prov_result.actual_cost_usd,
            tab_id=task.tab_id,
            created_at_utc=started,
        )
        await writer.write_record(record)
        result.succeeded += 1
        result.saved_images.extend(saved)
        cb._safe(cb.on_task_succeeded, task, saved, record)

    async def _execute_with_retry(
        self, task: GenerationTask, adapter, out_dir: Path
    ) -> tuple[list[SavedImage], ProviderResult]:
        retry_cfg = self.config.retry
        attempts = 0
        max_attempts = max(1, retry_cfg.max_retries + 1)
        last_exc: ProviderError | None = None

        while attempts < max_attempts:
            attempts += 1
            try:
                async with self._global_sem:
                    async with self._provider_sems[task.provider]:
                        limiter = self._provider_limiters.get(task.provider)
                        if limiter is not None:
                            await limiter.acquire()  # type: ignore[attr-defined]
                        prov_result = await adapter.generate(task, self.client)
                timestamp = utc_timestamp_compact()
                saved = await adapter.save_result(
                    prov_result, task, out_dir, timestamp, self.client
                )
                return saved, prov_result
            except ProviderError as exc:
                last_exc = exc
                exc._attempts = attempts  # type: ignore[attr-defined]
                if not exc.retryable or attempts >= max_attempts:
                    raise
                delay = self._backoff_delay(attempts, exc)
                self.callbacks._safe(
                    self.callbacks.on_progress,
                    f"{task.provider} retry {attempts}/{max_attempts - 1} in {delay:.1f}s ({exc.error_type})",
                )
                await asyncio.sleep(delay)
            except httpx.TimeoutException as exc:
                from .errors import ProviderTimeoutError

                last_exc = ProviderTimeoutError(str(exc), provider=task.provider, model=task.model)
                last_exc._attempts = attempts  # type: ignore[attr-defined]
                if attempts >= max_attempts:
                    raise last_exc
                await asyncio.sleep(self._backoff_delay(attempts, None))
            except httpx.HTTPError as exc:
                from .errors import ProviderTransientError

                last_exc = ProviderTransientError(str(exc), provider=task.provider, model=task.model)
                last_exc._attempts = attempts  # type: ignore[attr-defined]
                if attempts >= max_attempts:
                    raise last_exc
                await asyncio.sleep(self._backoff_delay(attempts, None))
        assert last_exc is not None
        raise last_exc

    def _backoff_delay(self, attempt: int, exc: ProviderError | None) -> float:
        retry_cfg = self.config.retry
        # Honor Retry-After when the provider supplied one.
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            return float(retry_after)
        base = retry_cfg.initial_backoff_seconds * (2 ** (attempt - 1))
        base = min(base, retry_cfg.max_backoff_seconds)
        if retry_cfg.jitter:
            base = base * (0.5 + random.random() * 0.5)
        return base

    # --- terminal outcomes -------------------------------------------------
    async def _skip(self, task, reason, writer: MetadataWriter, result: BatchResult) -> None:
        result.skipped += 1
        record = MetadataRecord(
            task_id=task.task_id,
            status=TaskStatus.SKIPPED.value,
            provider=task.provider,
            model=task.model,
            prompt_id=task.prompt_id,
            prompt_text=task.prompt_text,
            negative_prompt=task.negative_prompt,
            tab_id=task.tab_id,
            error=reason,
        )
        await writer.write_record(record)
        self.callbacks._safe(self.callbacks.on_task_skipped, task, reason)

    async def _fail(
        self, task, exc: ProviderError, writer: MetadataWriter, result: BatchResult, attempts: int = 1
    ) -> None:
        result.failed += 1
        err = ErrorRecord(
            task_id=task.task_id,
            provider=task.provider,
            model=task.model,
            prompt_id=task.prompt_id,
            error_type=exc.error_type,
            http_status=exc.http_status,
            message=str(exc),
            retryable=exc.retryable,
            attempts=attempts,
            tab_id=task.tab_id,
        )
        await writer.write_error(err)
        # Also record a failed metadata line so the run ledger is complete.
        await writer.write_record(
            MetadataRecord(
                task_id=task.task_id,
                status=TaskStatus.FAILED.value,
                provider=task.provider,
                model=task.model,
                prompt_id=task.prompt_id,
                prompt_text=task.prompt_text,
                negative_prompt=task.negative_prompt,
                tab_id=task.tab_id,
                error=f"{exc.error_type}: {exc}",
            )
        )
        self.callbacks._safe(self.callbacks.on_task_failed, task, err)

    async def _cancelled(self, task, writer: MetadataWriter, result: BatchResult) -> None:
        result.skipped += 1
        try:
            await writer.write_record(
                MetadataRecord(
                    task_id=task.task_id,
                    status=TaskStatus.CANCELLED.value,
                    provider=task.provider,
                    model=task.model,
                    prompt_id=task.prompt_id,
                    prompt_text=task.prompt_text,
                    tab_id=task.tab_id,
                    error="cancelled by user",
                )
            )
        except Exception:  # noqa: BLE001
            pass


def _make_limiter(prov) -> object:
    from .utils.rate_limit import NULL_LIMITER, AsyncRateLimiter

    spec = prov.rate_per_second()
    if spec is None:
        return NULL_LIMITER
    max_rate, period = spec
    # Prefer aiolimiter if installed (token-bucket), else our sliding window.
    try:
        from aiolimiter import AsyncLimiter  # type: ignore

        return AsyncLimiter(max_rate, period)
    except Exception:  # noqa: BLE001
        return AsyncRateLimiter(max_rate, period)


def _rel(out_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).relative_to(out_dir))
    except ValueError:
        return str(path)


# --- task planning ---------------------------------------------------------

def build_generation_tasks(
    *,
    prompts,
    provider_models: list[tuple[str, str]],
    reference_images: list[Path],
    mask: Path | None = None,
    images_per_prompt: int = 1,
    size: str = "1024x1024",
    quality: str = "high",
    output_format: str = "png",
    seed: int | None = None,
    tab_id: str = "",
) -> list[GenerationTask]:
    """Cartesian product: (provider,model) × prompt × images_per_prompt.

    ``prompts`` is a list of PromptVariant (from prompting.py).
    """
    tasks: list[GenerationTask] = []
    for provider, model in provider_models:
        for variant in prompts:
            text = variant.text_for(provider)
            for i in range(1, images_per_prompt + 1):
                task_id = f"{provider}_{model}_{variant.prompt_id}_{i:04d}".replace("/", "_")
                tasks.append(
                    GenerationTask(
                        task_id=task_id,
                        prompt_id=variant.prompt_id,
                        prompt_text=text,
                        provider=provider,
                        model=model,
                        reference_images=list(reference_images),
                        mask_path=mask,
                        negative_prompt=variant.negative_prompt,
                        seed=(seed + i - 1) if seed is not None else None,
                        size=size,
                        quality=quality,
                        output_format=output_format,
                        image_index=i,
                        tab_id=tab_id,
                    )
                )
    return tasks
