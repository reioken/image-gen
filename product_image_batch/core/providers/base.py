"""Provider adapter interface + shared base implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from ..config import PROVIDER_ENV_KEYS, ProviderConfig
from ..errors import ProviderError, classify_http_status
from ..models import (
    CostEstimate,
    GenerationTask,
    PreparedAssets,
    ProviderJob,
    ProviderResult,
    RemoteImage,
    SavedImage,
)
from ..utils import images as imgutil
from ..utils.files import unique_path
from ..utils.logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class ImageProviderAdapter(Protocol):
    """Structural interface every provider adapter satisfies."""

    provider_name: str
    model_name: str
    supports_reference_images: bool
    supports_masks: bool
    supports_multiple_references: bool
    supports_async_jobs: bool

    async def prepare_assets(self, refs: list[Path], mask: Path | None) -> PreparedAssets: ...
    async def estimate_cost(self, task: GenerationTask) -> CostEstimate: ...
    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob: ...
    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult: ...
    async def download_outputs(
        self, result: ProviderResult, out_dir: Path, client: httpx.AsyncClient
    ) -> list[SavedImage]: ...


class BaseProvider:
    """Common adapter behavior. Concrete providers override submit/poll/estimate.

    Subclasses set the class-level capability flags and implement ``submit``
    (and ``poll`` if the provider returns async job handles). Everything else —
    key lookup, asset prep, generic download — is provided here.
    """

    provider_name: str = "base"
    supports_reference_images: bool = True
    supports_masks: bool = False
    supports_multiple_references: bool = True
    supports_async_jobs: bool = False
    default_cost_per_image: float = 0.04  # rough placeholder, overridden per-provider
    cost_is_known: bool = False

    def __init__(
        self,
        config: ProviderConfig,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.model_name = config.resolve_model(model)

    # --- helpers -----------------------------------------------------------
    @property
    def env_key_name(self) -> str:
        return PROVIDER_ENV_KEYS.get(self.provider_name, "")

    def require_key(self) -> str:
        if not self.api_key:
            from ..errors import ProviderAuthError

            raise ProviderAuthError(
                f"No API key for provider '{self.provider_name}' "
                f"(set {self.env_key_name} in your .env).",
                provider=self.provider_name,
                model=self.model_name,
            )
        return self.api_key

    async def prepare_assets(
        self, refs: list[Path], mask: Path | None = None
    ) -> PreparedAssets:
        from ..assets import prepare_assets

        return await prepare_assets(refs, mask)

    async def estimate_cost(self, task: GenerationTask) -> CostEstimate:
        return CostEstimate(
            amount_usd=self.default_cost_per_image,
            known=self.cost_is_known,
            note="" if self.cost_is_known else "estimate uncertain",
        )

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        raise NotImplementedError

    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult:
        # Synchronous providers put the result on the job at submit time.
        if job.inline_result is not None:
            return job.inline_result
        raise NotImplementedError(
            f"{self.provider_name} declared async jobs but has no poll()"
        )

    async def generate(
        self, task: GenerationTask, client: httpx.AsyncClient
    ) -> ProviderResult:
        """Submit then (if needed) poll to completion."""
        job = await self.submit(task, client)
        if job.inline_result is not None:
            return job.inline_result
        return await self.poll(job, client)

    # --- shared download ---------------------------------------------------
    async def save_result(
        self,
        result: ProviderResult,
        task: GenerationTask,
        out_dir: Path,
        timestamp: str,
        client: httpx.AsyncClient,
    ) -> list[SavedImage]:
        """Download every image in ``result`` into ``out_dir/images/``.

        This is what the scheduler calls; it carries the ``task`` needed to build
        deterministic, sanitized filenames.
        """
        return await self._save_remote_images(
            result.images, task, out_dir / "images", timestamp, client
        )

    async def download_outputs(
        self, result: ProviderResult, out_dir: Path, client: httpx.AsyncClient
    ) -> list[SavedImage]:
        """Protocol-compatible download when no task context is available.

        Prefer :meth:`save_result`; this fallback names files from the result's
        provider/model only. The originating task can be threaded through
        ``result.raw['_task']`` for correct naming.
        """
        from ..metadata import utc_timestamp_compact

        task = result.raw.get("_task")
        if isinstance(task, GenerationTask):
            return await self.save_result(
                result, task, out_dir, utc_timestamp_compact(), client
            )
        # Minimal fallback naming.
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        saved: list[SavedImage] = []
        ts = utc_timestamp_compact()
        for i, remote in enumerate(result.images, start=1):
            ext = remote.suggested_ext or "png"
            path = unique_path(
                images_dir / f"{result.provider}_{result.model}_{ts}_{i:04d}.{ext}"
            )
            data = await self._fetch_bytes(remote, client)
            await _write_bytes(path, data)
            saved.append(
                SavedImage(
                    path=path,
                    provider=result.provider,
                    model=result.model,
                    prompt_id="",
                    task_id="",
                    index=i,
                )
            )
        return saved

    async def _save_remote_images(
        self,
        images: list[RemoteImage],
        task: GenerationTask,
        images_dir: Path,
        timestamp: str,
        client: httpx.AsyncClient,
    ) -> list[SavedImage]:
        """Download/decode each RemoteImage and write it next to the run."""
        images_dir.mkdir(parents=True, exist_ok=True)
        saved: list[SavedImage] = []
        for offset, remote in enumerate(images):
            ext = remote.suggested_ext or task.output_format or "png"
            index = task.image_index + offset
            stem = task.output_basename(timestamp)
            if offset:
                stem = f"{stem}-{offset}"
            path = unique_path(images_dir / f"{stem}.{ext}")
            data = await self._fetch_bytes(remote, client)
            await _write_bytes(path, data)
            saved.append(
                SavedImage(
                    path=path,
                    provider=task.provider,
                    model=task.model,
                    prompt_id=task.prompt_id,
                    task_id=task.task_id,
                    index=index,
                    tab_id=task.tab_id,
                )
            )
        return saved

    async def _fetch_bytes(self, remote: RemoteImage, client: httpx.AsyncClient) -> bytes:
        import base64

        if remote.b64_data:
            b64 = remote.b64_data
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[-1]
            return base64.b64decode(b64)
        if remote.url:
            resp = await client.get(remote.url, timeout=120.0)
            if resp.status_code >= 400:
                raise classify_http_status(
                    resp.status_code,
                    provider=self.provider_name,
                    model=self.model_name,
                    message=f"download failed: {resp.status_code}",
                )
            return resp.content
        raise ProviderError(
            "Provider returned an image with neither url nor base64 data.",
            provider=self.provider_name,
            model=self.model_name,
        )

    # --- HTTP helper -------------------------------------------------------
    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        val = resp.headers.get("retry-after")
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    def raise_for_status(self, resp: httpx.Response, *, body: str = "") -> None:
        if resp.status_code < 400:
            return
        raise classify_http_status(
            resp.status_code,
            provider=self.provider_name,
            model=self.model_name,
            message=body or _safe_text(resp),
            retry_after=self._retry_after(resp),
        )


def _safe_text(resp: httpx.Response) -> str:
    try:
        return resp.text[:500]
    except Exception:  # noqa: BLE001
        return ""


async def _write_bytes(path: Path, data: bytes) -> None:
    """Write bytes without blocking the event loop (aiofiles if available)."""
    try:
        import aiofiles  # type: ignore

        async with aiofiles.open(path, "wb") as fh:
            await fh.write(data)
    except Exception:  # noqa: BLE001 — fall back to a thread
        await asyncio.to_thread(path.write_bytes, data)
