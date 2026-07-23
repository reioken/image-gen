"""Ideogram adapter (Remix endpoint).

Uses the Remix endpoint with a multipart body carrying the reference image plus
prompt. Auth via the ``Api-Key`` header. Default concurrency stays under
Ideogram's 10 inflight-request limit (enforced by config).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider

REMIX_URL = "https://api.ideogram.ai/remix"


class IdeogramProvider(BaseProvider):
    provider_name = "ideogram"
    supports_reference_images = True
    supports_masks = True
    supports_multiple_references = False
    supports_async_jobs = False
    default_cost_per_image = 0.08
    cost_is_known = False

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        key = self.require_key()
        headers = {"Api-Key": key}
        image_request = {
            "prompt": task.prompt_text,
            "model": self.model_name,
            "image_weight": int(task.provider_params.get("image_weight", 50)),
        }
        if task.aspect_ratio:
            image_request["aspect_ratio"] = task.aspect_ratio
        if task.negative_prompt:
            image_request["negative_prompt"] = task.negative_prompt
        if task.seed is not None:
            image_request["seed"] = task.seed

        files = {}
        if task.reference_images:
            ref = Path(task.reference_images[0])
            files["image_file"] = (ref.name, ref.read_bytes(), _mime(ref))
        import json as _json

        data = {"image_request": _json.dumps(image_request)}
        resp = await client.post(
            REMIX_URL, headers=headers, data=data, files=files or None, timeout=300.0
        )
        self.raise_for_status(resp)
        result = self._parse_result(resp.json())
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )

    def _parse_result(self, payload: dict) -> ProviderResult:
        images = [
            RemoteImage(url=item["url"], suggested_ext="png")
            for item in payload.get("data", [])
            if item.get("url")
        ]
        return ProviderResult(
            provider=self.provider_name, model=self.model_name, images=images, raw=payload
        )


def _mime(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
