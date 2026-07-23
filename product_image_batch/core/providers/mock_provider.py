"""In-process mock provider — never makes a network call.

Used for tests, ``--dry-run`` demonstrations and offline GUI smoke-testing. It
generates a tiny solid-color PNG in-memory (deterministic from the task) so the
full pipeline (submit → result → download → metadata) can be exercised without
any API key or network access.
"""

from __future__ import annotations

import base64
import hashlib
import io

import httpx

from ..models import CostEstimate, GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider


def _tiny_png(seed: str) -> bytes:
    """Create a small solid-color PNG whose color is derived from ``seed``."""
    from PIL import Image

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    color = (digest[0], digest[1], digest[2])
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockProvider(BaseProvider):
    provider_name = "mock"
    supports_reference_images = True
    supports_masks = True
    supports_multiple_references = True
    supports_async_jobs = False
    default_cost_per_image = 0.01
    cost_is_known = True

    async def estimate_cost(self, task: GenerationTask) -> CostEstimate:
        return CostEstimate(amount_usd=self.default_cost_per_image, known=True, note="mock")

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        seed = f"{task.provider}:{task.model}:{task.prompt_id}:{task.image_index}:{task.seed}"
        png = _tiny_png(seed)
        b64 = base64.b64encode(png).decode("ascii")
        result = ProviderResult(
            provider=self.provider_name,
            model=self.model_name,
            provider_job_id=f"mock-{hashlib.md5(seed.encode()).hexdigest()[:8]}",
            actual_cost_usd=self.default_cost_per_image,
            images=[RemoteImage(b64_data=b64, content_type="image/png", suggested_ext="png")],
        )
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )
