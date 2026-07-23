"""Black Forest Labs (FLUX.2 / FLUX.1 Kontext) adapter.

Submits JSON with base64 image fields (``input_image``, ``input_image_2`` …) to
``https://api.bfl.ai/v1/<model>`` and polls the returned ``polling_url`` until
the result is ready. FLUX.2 supports up to 8 reference images.

Auth: ``x-key: <BFL_API_KEY>``.
"""

from __future__ import annotations

import asyncio

import httpx

from ..errors import ProviderError, ProviderTimeoutError
from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from ..utils import images as imgutil
from .base import BaseProvider

API_BASE = "https://api.bfl.ai/v1"


class BFLProvider(BaseProvider):
    provider_name = "bfl"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = True
    supports_async_jobs = True
    default_cost_per_image = 0.05
    cost_is_known = False

    def _headers(self) -> dict[str, str]:
        return {"x-key": self.require_key(), "Content-Type": "application/json"}

    def _build_body(self, task: GenerationTask) -> dict:
        body: dict = {"prompt": task.prompt_text}
        refs = task.reference_images[:8]
        for i, ref in enumerate(refs):
            b64 = imgutil.to_base64(ref)
            key = "input_image" if i == 0 else f"input_image_{i + 1}"
            body[key] = b64
        if task.seed is not None:
            body["seed"] = task.seed
        if task.aspect_ratio:
            body["aspect_ratio"] = task.aspect_ratio
        if task.output_format:
            body["output_format"] = task.output_format
        body.update(task.provider_params)
        return body

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        self.require_key()
        url = f"{API_BASE}/{self.model_name}"
        resp = await client.post(
            url, headers=self._headers(), json=self._build_body(task), timeout=120.0
        )
        self.raise_for_status(resp)
        data = resp.json()
        return ProviderJob(
            provider=self.provider_name,
            model=self.model_name,
            job_id=data.get("id"),
            poll_url=data.get("polling_url"),
            raw=data,
        )

    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult:
        poll_url = job.poll_url
        if not poll_url:
            raise ProviderError(
                "BFL did not return a polling_url", provider=self.provider_name, model=self.model_name
            )
        headers = {"x-key": self.require_key()}
        deadline = 600.0
        waited = 0.0
        interval = 1.5
        while waited < deadline:
            resp = await client.get(poll_url, headers=headers, timeout=60.0)
            self.raise_for_status(resp)
            data = resp.json()
            status = data.get("status")
            if status == "Ready":
                return self._parse_result(data)
            if status in ("Error", "Failed", "Content Moderated", "Request Moderated"):
                from ..errors import ProviderContentPolicyError

                if "Moderated" in str(status):
                    raise ProviderContentPolicyError(
                        f"BFL moderated the request: {status}",
                        provider=self.provider_name,
                        model=self.model_name,
                    )
                raise ProviderError(
                    f"BFL job failed: {status}",
                    provider=self.provider_name,
                    model=self.model_name,
                )
            await asyncio.sleep(interval)
            waited += interval
            interval = min(interval * 1.3, 8.0)
        raise ProviderTimeoutError(
            f"BFL job {job.job_id} timed out", provider=self.provider_name, model=self.model_name
        )

    def _parse_result(self, data: dict) -> ProviderResult:
        result = data.get("result") or {}
        images: list[RemoteImage] = []
        sample = result.get("sample")
        if isinstance(sample, str):
            if sample.startswith("http"):
                images.append(RemoteImage(url=sample, suggested_ext="png"))
            else:
                images.append(RemoteImage(b64_data=sample, suggested_ext="png"))
        return ProviderResult(
            provider=self.provider_name,
            model=self.model_name,
            provider_job_id=data.get("id"),
            images=images,
            raw=data,
        )
