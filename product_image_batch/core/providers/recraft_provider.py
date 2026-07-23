"""Recraft adapter (image-to-image).

Uses ``https://external.api.recraft.ai/v1/images/imageToImage`` with a multipart
body (``image``, ``prompt``, ``strength``) and optional ``mask``. Auth via a
Bearer token.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider

API_URL = "https://external.api.recraft.ai/v1/images/imageToImage"


class RecraftProvider(BaseProvider):
    provider_name = "recraft"
    supports_reference_images = True
    supports_masks = True
    supports_multiple_references = False
    supports_async_jobs = False
    default_cost_per_image = 0.04
    cost_is_known = False

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        key = self.require_key()
        headers = {"Authorization": f"Bearer {key}"}
        data = {
            "prompt": task.prompt_text,
            "strength": str(task.provider_params.get("strength", 0.4)),
            "model": self.model_name,
        }
        if task.negative_prompt:
            data["negative_prompt"] = task.negative_prompt
        style_id = task.provider_params.get("style_id")
        if style_id:
            data["style_id"] = str(style_id)
        for k, v in task.provider_params.items():
            if k not in ("strength", "style_id"):
                data[k] = str(v)

        files = {}
        if task.reference_images:
            ref = Path(task.reference_images[0])
            files["image"] = (ref.name, ref.read_bytes(), _mime(ref))
        if task.mask_path is not None:
            mp = Path(task.mask_path)
            files["mask"] = (mp.name, mp.read_bytes(), "image/png")

        resp = await client.post(
            API_URL, headers=headers, data=data, files=files or None, timeout=300.0
        )
        self.raise_for_status(resp)
        result = self._parse_result(resp.json())
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )

    def _parse_result(self, payload: dict) -> ProviderResult:
        images: list[RemoteImage] = []
        for item in payload.get("data", []) or payload.get("images", []):
            if isinstance(item, dict):
                if item.get("url"):
                    images.append(RemoteImage(url=item["url"], suggested_ext="png"))
                elif item.get("b64_json"):
                    images.append(RemoteImage(b64_data=item["b64_json"], suggested_ext="png"))
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
