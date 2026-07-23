"""Stability AI adapter (v2beta image-to-image).

Uses ``https://api.stability.ai/v2beta/stable-image/generate/<model>`` with a
``multipart/form-data`` body carrying ``image``, ``prompt``, ``strength`` and
``mode=image-to-image``. Requests ``image/*`` accept so the raw image bytes are
returned directly.

Auth: ``Authorization: Bearer <STABILITY_API_KEY>``.
Rate note: stay under 150 requests / 10s (handled by the configured limiter).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..models import CostEstimate, GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider

API_BASE = "https://api.stability.ai/v2beta/stable-image/generate"

# Rough credit->USD estimates per image by model (Stability bills in credits).
_COST = {
    "stable-image-ultra": 0.08,
    "sd3.5-large": 0.065,
    "core": 0.03,
}


class StabilityProvider(BaseProvider):
    provider_name = "stability"
    supports_reference_images = True
    supports_masks = True
    supports_multiple_references = False
    supports_async_jobs = False
    cost_is_known = False

    def _endpoint(self) -> str:
        model = self.model_name
        if model == "stable-image-ultra":
            return f"{API_BASE}/ultra"
        if model.startswith("sd3"):
            return f"{API_BASE}/sd3"
        if model == "core":
            return f"{API_BASE}/core"
        return f"{API_BASE}/sd3"

    async def estimate_cost(self, task: GenerationTask) -> CostEstimate:
        price = _COST.get(self.model_name)
        if price is None:
            return CostEstimate(0.065, known=False, note="credit pricing estimate")
        return CostEstimate(price, known=False, note="credit->usd estimate")

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        key = self.require_key()
        headers = {"Authorization": f"Bearer {key}", "Accept": "image/*"}

        files: dict = {}
        data: dict = {
            "prompt": task.prompt_text,
            "mode": "image-to-image",
            "output_format": task.output_format or "png",
        }
        if task.negative_prompt:
            data["negative_prompt"] = task.negative_prompt
        if task.seed is not None:
            data["seed"] = str(task.seed)
        # strength is required for image-to-image.
        data["strength"] = str(task.provider_params.get("strength", 0.55))
        if self.model_name.startswith("sd3"):
            data["model"] = self.model_name

        if task.reference_images:
            ref = Path(task.reference_images[0])
            files["image"] = (ref.name, ref.read_bytes(), _mime(ref))
        if task.mask_path is not None:
            mp = Path(task.mask_path)
            files["mask"] = (mp.name, mp.read_bytes(), "image/png")
        # multipart requires at least one file part; ensure form is multipart.
        for k, v in task.provider_params.items():
            if k != "strength":
                data[k] = str(v)

        resp = await client.post(
            self._endpoint(), headers=headers, data=data, files=files or None, timeout=300.0
        )
        # Stability returns image bytes on success, JSON on error.
        if resp.status_code >= 400:
            body = ""
            try:
                body = resp.json().get("errors", resp.text)  # type: ignore
            except Exception:  # noqa: BLE001
                body = resp.text
            self.raise_for_status(resp, body=str(body))

        content_type = resp.headers.get("content-type", "image/png")
        ext = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }.get(content_type.split(";")[0].strip(), task.output_format or "png")
        image = RemoteImage(
            b64_data=_b64(resp.content), content_type=content_type, suggested_ext=ext
        )
        result = ProviderResult(
            provider=self.provider_name,
            model=self.model_name,
            provider_job_id=resp.headers.get("x-request-id"),
            images=[image],
        )
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )


def _mime(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")
