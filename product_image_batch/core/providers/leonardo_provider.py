"""Leonardo.Ai adapter (upload -> init image id -> generation -> poll).

Three-step flow:
1. ``POST /init-image`` to get a presigned upload, then PUT the image bytes.
2. ``POST /generations`` with ``init_image_id`` + ``init_strength``.
3. Poll ``GET /generations/<id>`` until complete.

Auth: ``Authorization: Bearer <LEONARDO_API_KEY>``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from ..errors import ProviderError, ProviderTimeoutError
from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from .base import BaseProvider
from ..utils import images as imgutil

API_BASE = "https://cloud.leonardo.ai/api/rest/v1"


class LeonardoProvider(BaseProvider):
    provider_name = "leonardo"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = False
    supports_async_jobs = True
    default_cost_per_image = 0.02
    cost_is_known = False

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.require_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _upload_init_image(self, ref: Path, client: httpx.AsyncClient) -> str:
        ext = ref.suffix.lstrip(".").lower() or "png"
        resp = await client.post(
            f"{API_BASE}/init-image",
            headers=self._headers(),
            json={"extension": "jpg" if ext == "jpeg" else ext},
            timeout=120.0,
        )
        self.raise_for_status(resp)
        upload = resp.json().get("uploadInitImage", {})
        image_id = upload.get("id")
        fields = json.loads(upload.get("fields", "{}"))
        url = upload.get("url")
        if not (image_id and url):
            raise ProviderError(
                "Leonardo did not return an upload target.",
                provider=self.provider_name,
                model=self.model_name,
            )
        # POST the file to the presigned S3 URL (no auth header).
        files = {"file": (ref.name, imgutil.read_bytes_cached(ref))}
        up = await client.post(url, data=fields, files=files, timeout=300.0)
        if up.status_code >= 400:
            self.raise_for_status(up, body="init-image upload failed")
        return image_id

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        self.require_key()
        init_image_id = None
        if task.reference_images:
            init_image_id = await self._upload_init_image(
                Path(task.reference_images[0]), client
            )
        width, height = _parse_size(task.size)
        body = {
            "prompt": task.prompt_text,
            "modelId": task.provider_params.get("model_id", "b24e16ff-06e3-43eb-8d33-4416c2d75876"),
            "width": width,
            "height": height,
            "num_images": 1,
        }
        if task.negative_prompt:
            body["negative_prompt"] = task.negative_prompt
        if task.seed is not None:
            body["seed"] = task.seed
        if init_image_id:
            body["init_image_id"] = init_image_id
            body["init_strength"] = float(task.provider_params.get("init_strength", 0.4))
        for k, v in task.provider_params.items():
            if k not in ("model_id", "init_strength"):
                body[k] = v

        resp = await client.post(
            f"{API_BASE}/generations", headers=self._headers(), json=body, timeout=120.0
        )
        self.raise_for_status(resp)
        gen_id = (resp.json().get("sdGenerationJob") or {}).get("generationId")
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, job_id=gen_id, raw=resp.json()
        )

    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult:
        url = f"{API_BASE}/generations/{job.job_id}"
        deadline, waited, interval = 600.0, 0.0, 3.0
        while waited < deadline:
            resp = await client.get(url, headers=self._headers(), timeout=60.0)
            self.raise_for_status(resp)
            gen = resp.json().get("generations_by_pk") or {}
            status = gen.get("status")
            if status == "COMPLETE":
                images = [
                    RemoteImage(url=img["url"], suggested_ext="jpg")
                    for img in gen.get("generated_images", [])
                    if img.get("url")
                ]
                return ProviderResult(
                    provider=self.provider_name,
                    model=self.model_name,
                    provider_job_id=job.job_id,
                    images=images,
                    raw=gen,
                )
            if status == "FAILED":
                raise ProviderError(
                    "Leonardo generation failed",
                    provider=self.provider_name,
                    model=self.model_name,
                )
            await asyncio.sleep(interval)
            waited += interval
        raise ProviderTimeoutError(
            f"Leonardo generation {job.job_id} timed out",
            provider=self.provider_name,
            model=self.model_name,
        )


def _parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1024, 1024
