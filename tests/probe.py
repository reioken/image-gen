"""Shared in-memory test providers + helpers (no network)."""

from __future__ import annotations

import asyncio
import base64
import io

from PIL import Image

from product_image_batch.core.errors import ProviderRateLimitError
from product_image_batch.core.models import (
    GenerationTask,
    ProviderJob,
    ProviderResult,
    RemoteImage,
)
from product_image_batch.core.providers.base import BaseProvider


def png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class ProbeProvider(BaseProvider):
    """Counts concurrent in-flight generate() calls to prove semaphore limits."""

    provider_name = "probe"
    supports_reference_images = True
    cost_is_known = True
    default_cost_per_image = 0.01

    live = 0
    peak = 0
    _lock = asyncio.Lock()

    @classmethod
    def reset(cls) -> None:
        cls.live = 0
        cls.peak = 0

    async def submit(self, task, client) -> ProviderJob:
        async with ProbeProvider._lock:
            ProbeProvider.live += 1
            ProbeProvider.peak = max(ProbeProvider.peak, ProbeProvider.live)
        try:
            await asyncio.sleep(0.05)
        finally:
            async with ProbeProvider._lock:
                ProbeProvider.live -= 1
        result = ProviderResult(
            provider=self.provider_name, model=self.model_name,
            images=[RemoteImage(b64_data=png_b64(), suggested_ext="png")],
            actual_cost_usd=0.01,
        )
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )


class FlakyProvider(BaseProvider):
    """Always rate-limited, to test error isolation without aborting a batch."""

    provider_name = "flaky"
    cost_is_known = True
    default_cost_per_image = 0.0

    async def submit(self, task, client) -> ProviderJob:
        raise ProviderRateLimitError(
            "429", provider=self.provider_name, model=self.model_name,
            http_status=429, retry_after=0.01,
        )


def make_tasks(n: int, tab_id: str = "t", provider: str = "probe") -> list[GenerationTask]:
    return [
        GenerationTask(
            task_id=f"{tab_id}-{i}", prompt_id=f"p{i:03d}", prompt_text="x",
            provider=provider, model="probe-v1", tab_id=tab_id,
        )
        for i in range(n)
    ]
