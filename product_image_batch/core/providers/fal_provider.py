"""fal.ai adapter using the queue REST API.

Submits to ``https://queue.fal.run/<model>`` and polls the returned status URL.
Local reference images are passed as base64 data-URIs (fal accepts URL, data-URI
or an uploaded storage URL). The default model is the product-photography app,
which expects ``product_image_url``; other models map the reference to
``image_url`` / ``image_urls``.

Auth: ``Authorization: Key <FAL_KEY>``.
"""

from __future__ import annotations

import asyncio

import httpx

from ..errors import ProviderTimeoutError
from ..models import GenerationTask, PreparedAssets, ProviderJob, ProviderResult, RemoteImage
from ..utils import images as imgutil
from .base import BaseProvider

QUEUE_BASE = "https://queue.fal.run"


class FalProvider(BaseProvider):
    provider_name = "fal"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = True
    supports_async_jobs = True
    default_cost_per_image = 0.05
    cost_is_known = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.require_key()}", "Content-Type": "application/json"}

    def _build_input(self, task: GenerationTask) -> dict:
        refs = task.reference_images
        data_uris = [imgutil.to_data_url(r) for r in refs]
        model = self.model_name
        payload: dict = {"prompt": task.prompt_text}
        if "product-photography" in model:
            if data_uris:
                payload["product_image_url"] = data_uris[0]
        elif "kontext" in model or "flux" in model:
            # kontext/flux edit models take one or more image_urls.
            if len(data_uris) == 1:
                payload["image_url"] = data_uris[0]
            elif data_uris:
                payload["image_urls"] = data_uris
        else:
            if data_uris:
                payload["image_url"] = data_uris[0]
        if task.seed is not None:
            payload["seed"] = task.seed
        payload.update(task.provider_params)
        return payload

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        self.require_key()
        url = f"{QUEUE_BASE}/{self.model_name}"
        resp = await client.post(
            url, headers=self._headers(), json=self._build_input(task), timeout=120.0
        )
        self.raise_for_status(resp)
        data = resp.json()
        return ProviderJob(
            provider=self.provider_name,
            model=self.model_name,
            job_id=data.get("request_id"),
            poll_url=data.get("status_url"),
            raw=data,
        )

    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult:
        status_url = job.poll_url or f"{QUEUE_BASE}/{self.model_name}/requests/{job.job_id}/status"
        response_url = job.raw.get("response_url") or (
            f"{QUEUE_BASE}/{self.model_name}/requests/{job.job_id}"
        )
        headers = {"Authorization": f"Key {self.require_key()}"}
        deadline = 600.0
        waited = 0.0
        interval = 2.0
        while waited < deadline:
            resp = await client.get(status_url, headers=headers, timeout=60.0)
            self.raise_for_status(resp)
            status = resp.json().get("status")
            if status == "COMPLETED":
                out = await client.get(response_url, headers=headers, timeout=120.0)
                self.raise_for_status(out)
                return self._parse_result(out.json())
            if status in ("IN_QUEUE", "IN_PROGRESS"):
                await asyncio.sleep(interval)
                waited += interval
                interval = min(interval * 1.3, 10.0)
                continue
            # Unknown / error status.
            await asyncio.sleep(interval)
            waited += interval
        raise ProviderTimeoutError(
            f"fal job {job.job_id} did not complete within {deadline:.0f}s",
            provider=self.provider_name,
            model=self.model_name,
        )

    def _parse_result(self, payload: dict) -> ProviderResult:
        images: list[RemoteImage] = []
        img_list = payload.get("images") or payload.get("image") or []
        if isinstance(img_list, dict):
            img_list = [img_list]
        for item in img_list:
            if isinstance(item, str):
                images.append(RemoteImage(url=item, suggested_ext=_ext_from_url(item)))
            elif isinstance(item, dict) and item.get("url"):
                images.append(
                    RemoteImage(
                        url=item["url"],
                        content_type=item.get("content_type", "image/png"),
                        suggested_ext=imgutil.ext_for_content_type(
                            item.get("content_type", "image/png")
                        ),
                    )
                )
        return ProviderResult(
            provider=self.provider_name, model=self.model_name, images=images, raw=payload
        )


def _ext_from_url(url: str) -> str:
    lower = url.lower().split("?")[0]
    for ext in ("png", "jpg", "jpeg", "webp"):
        if lower.endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    return "png"
