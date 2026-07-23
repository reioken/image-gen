# Architecture

This document explains the internal design. For usage, see the
[README](../README.md).

## Layers

```
┌──────────────────────────────┐   ┌──────────────────────────────┐
│  cli.py (argparse front-end) │   │  gui/ (PySide6 front-end)    │
└───────────────┬──────────────┘   └───────────────┬──────────────┘
                │  builds tasks, calls the engine   │
                ▼                                    ▼
        ┌───────────────────────────────────────────────────┐
        │  core/  — the engine (async, no GUI imports)       │
        │  config · models · assets · prompting · budget ·   │
        │  metadata · scheduler · providers/*                │
        └───────────────────────────────────────────────────┘
```

`core/` never imports from `cli.py` or `gui/`. This keeps the engine testable in
isolation and means the CLI and GUI cannot drift apart — they share one code
path for building and running tasks.

## Data flow of a run

1. **Inputs** — reference images + mask are validated (`assets.validate_assets`,
   `utils.images.preflight_mask`) and copied into the run folder.
2. **Prompts** — loaded from `--prompt`/`--prompts` or generated from a brief
   (`prompting`), then optionally rewritten per-provider with product-preservation
   instructions.
3. **Task planning** — `scheduler.build_generation_tasks` produces the cartesian
   product `(provider, model) × prompt × images_per_prompt`, each a
   `GenerationTask` carrying the shared reference set and a `tab_id`.
4. **Budget** — `BudgetManager.reserve` is consulted before each task; a task
   that would exceed the cap is skipped (logged), not started.
5. **Execution** — `GlobalScheduler.run_batch` runs the tasks concurrently under
   the semaphores/limiters, retrying transient failures.
6. **Download** — each provider result's images are written under `images/` with
   sanitized, deterministic names.
7. **Metadata** — one `metadata.jsonl` line per output/error is written
   incrementally; a `metadata.csv` is produced at the end.

## The provider adapter pattern

Every provider implements a small interface (`providers/base.py`):

```python
class ImageProviderAdapter(Protocol):
    provider_name: str
    model_name: str
    supports_reference_images: bool
    supports_masks: bool
    supports_multiple_references: bool
    supports_async_jobs: bool

    async def prepare_assets(...) -> PreparedAssets
    async def estimate_cost(task) -> CostEstimate
    async def submit(task, client) -> ProviderJob
    async def poll(job, client) -> ProviderResult
    async def download_outputs(...) -> list[SavedImage]
```

`BaseProvider` supplies the shared behavior (key lookup, generic download/decode,
HTTP status → normalized error). A concrete adapter typically only implements
`submit` (synchronous providers return an inline result) and `poll` (async/queued
providers). Errors are normalized into a small hierarchy
(`ProviderAuthError`, `ProviderRateLimitError`, `ProviderContentPolicyError`,
`ProviderInvalidInputError`, `ProviderTimeoutError`, `ProviderTransientError`) so
the scheduler can make uniform retry/disable decisions.

Reference images are exposed to adapters in several representations via
`PreparedAssets` (local path, base64 data-URL, uploaded URL, provider file-id);
each adapter picks what its API needs.

## Why one global scheduler

If each GUI tab had its own scheduler with its own per-provider semaphores,
opening N tabs would multiply the effective per-provider concurrency by N and
quickly trip rate limits or bans (e.g. Stability's 150 req/10s, Ideogram's 10
inflight). Instead:

- There is exactly **one** `GlobalScheduler` per app instance with **one
  semaphore set per provider**, regardless of how many tabs submit work.
- A **global cap** (`global_max_concurrent`) bounds total in-flight requests
  across all providers.
- A **per-provider rate limiter** (sliding-window, or `aiolimiter` if installed)
  enforces requests-per-period on top of the semaphore.
- Every task carries a `tab_id`; progress callbacks echo it so the GUI routes
  results to the right tab, and `cancel_tab(tab_id)` cancels only that tab's
  in-flight `asyncio.Task`s.

Retries use exponential backoff with jitter and honor `Retry-After`. Auth errors
disable that provider for the rest of the run (retrying a bad key is pointless).
Content-policy refusals are never retried.

## The async bridge (GUI)

Qt owns the UI thread and its own event loop; asyncio needs its own. They must
not block each other.

- On app start, `AsyncBridge` spins up **one dedicated background thread** running
  a private asyncio event loop for the app's lifetime, and constructs the single
  `GlobalScheduler` in it.
- Work is submitted from the UI thread via
  `asyncio.run_coroutine_threadsafe(coro, loop)`.
- Results flow back **only** through Qt signals. The scheduler's callbacks run in
  the background thread and just `emit`; because `AsyncBridge` is a `QObject`
  created on the UI thread, those emits are delivered as queued slot calls on the
  UI thread — so widgets are only ever touched from the UI thread.

```
UI thread                         background thread (asyncio loop)
─────────                         ────────────────────────────────
click "Start" ──run_coroutine_threadsafe──▶ GlobalScheduler.run_batch
                                             │ per task: submit/poll/download
   thumbnails ◀───Qt queued signal─── emit(sig_task_succeeded)
```

## Performance choices

- One app-wide `httpx.AsyncClient` with connection pooling
  (`max_connections`, `max_keepalive_connections`) shared by all adapters.
- Reference images validated once per tab/run; base64 encoding is done off the
  event loop (`asyncio.to_thread`) so the GUI never stutters.
- Image writes use `aiofiles` when available (thread fallback otherwise).
- GUI thumbnails are downscaled with Pillow; originals on disk are untouched.

## Packaging

`build/product_image_batch.spec` builds a **one-dir** app (faster startup than
one-file). Config templates and `.env.example` are bundled as data; real keys and
settings live outside the executable under `%APPDATA%\ProductImageBatch\`.
`config.resource_root()` resolves bundled resources from `sys._MEIPASS` when
frozen and from the repo root otherwise.
