"""OpenAI GPT Image adapter (Images Edit endpoint).

Uses the REST ``POST /v1/images/edits`` multipart endpoint so we need no extra
SDK dependency. GPT Image models accept up to 16 source images (png/webp/jpg,
each < 50 MB) plus a prompt and an optional PNG mask. The response is base64.

Docs: OpenAI Images Edit reference & image-generation guide.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..models import CostEstimate, GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider

API_URL = "https://api.openai.com/v1/images/edits"

# Rough per-image pricing (USD) for gpt-image-1 by quality — used for estimates.
# Real billing depends on model/size/quality; treated as an estimate.
_PRICE_TABLE = {
    ("low", "1024x1024"): 0.011,
    ("medium", "1024x1024"): 0.042,
    ("high", "1024x1024"): 0.167,
    ("low", "1536x1024"): 0.016,
    ("medium", "1536x1024"): 0.063,
    ("high", "1536x1024"): 0.25,
    ("low", "1024x1536"): 0.016,
    ("medium", "1024x1536"): 0.063,
    ("high", "1024x1536"): 0.25,
}


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    supports_reference_images = True
    supports_masks = True
    supports_multiple_references = True
    supports_async_jobs = False
    cost_is_known = True

    async def estimate_cost(self, task: GenerationTask) -> CostEstimate:
        price = _PRICE_TABLE.get((task.quality, task.size))
        if price is None:
            return CostEstimate(0.167, known=False, note="unknown size/quality pricing")
        return CostEstimate(price, known=True)

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        key = self.require_key()
        headers = {"Authorization": f"Bearer {key}"}

        # Build multipart file parts. GPT Image accepts multiple images via
        # repeated image[] fields.
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        open_handles: list = []
        try:
            for ref in task.reference_images[:16]:
                p = Path(ref)
                files.append(
                    ("image[]", (p.name, p.read_bytes(), _mime_for(p)))
                )
            if task.mask_path is not None:
                mp = Path(task.mask_path)
                files.append(("mask", (mp.name, mp.read_bytes(), "image/png")))

            data = {
                "model": self.model_name,
                "prompt": task.prompt_text,
                "size": task.size,
                "n": "1",
            }
            if task.quality:
                data["quality"] = task.quality
            if task.output_format:
                data["output_format"] = task.output_format
            data.update({k: str(v) for k, v in task.provider_params.items()})

            resp = await client.post(
                API_URL, headers=headers, data=data, files=files, timeout=300.0
            )
        finally:
            for h in open_handles:
                h.close()

        self.raise_for_status(resp)
        payload = resp.json()
        images = _parse_openai_images(payload, task.output_format)
        result = ProviderResult(
            provider=self.provider_name,
            model=self.model_name,
            provider_job_id=payload.get("id"),
            images=images,
            raw=payload,
        )
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )


def _mime_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")


def _parse_openai_images(payload: dict, out_fmt: str) -> list[RemoteImage]:
    ext = (out_fmt or "png").lower()
    if ext == "jpg":
        ext = "jpg"
    images: list[RemoteImage] = []
    for item in payload.get("data", []):
        if item.get("b64_json"):
            images.append(
                RemoteImage(b64_data=item["b64_json"], suggested_ext=ext, content_type=f"image/{ext}")
            )
        elif item.get("url"):
            images.append(RemoteImage(url=item["url"], suggested_ext=ext))
    return images
