"""Replicate adapter using the REST Predictions API.

Creates a prediction against ``https://api.replicate.com/v1/models/<owner>/<name>/predictions``
and polls until it succeeds/fails. Reference images are passed as base64
data-URIs (Replicate recommends data-URIs only for files < 1 MB; larger refs
should ideally be uploaded first — a TODO left for very large images).

Auth: ``Authorization: Bearer <REPLICATE_API_TOKEN>``.
"""

from __future__ import annotations

import asyncio

import httpx

from ..errors import ProviderTimeoutError
from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from ..utils import images as imgutil
from ..utils.logging import get_logger
from .base import BaseProvider

log = get_logger(__name__)
API_BASE = "https://api.replicate.com/v1"


class ReplicateProvider(BaseProvider):
    provider_name = "replicate"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = True
    supports_async_jobs = True
    default_cost_per_image = 0.04
    cost_is_known = False

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.require_key()}",
            "Content-Type": "application/json",
        }

    def _build_input(self, task: GenerationTask) -> dict:
        refs = task.reference_images
        data_uris = [imgutil.to_data_url(r) for r in refs]
        for r in refs:
            if r.stat().st_size > 1_000_000:
                log.warning(
                    "Replicate reference %s is >1MB; data-URI upload may be rejected. "
                    "Consider hosting it at a public URL.",
                    r.name,
                )
        payload: dict = {"prompt": task.prompt_text}
        if data_uris:
            # Common flux/kontext edit input keys.
            payload["input_image"] = data_uris[0]
            payload["image"] = data_uris[0]
            if len(data_uris) > 1:
                payload["input_images"] = data_uris
        if task.negative_prompt:
            payload["negative_prompt"] = task.negative_prompt
        if task.seed is not None:
            payload["seed"] = task.seed
        if task.aspect_ratio:
            payload["aspect_ratio"] = task.aspect_ratio
        payload["output_format"] = task.output_format or "png"
        payload.update(task.provider_params)
        return payload

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        self.require_key()
        # model_name is "owner/name" (optionally "owner/name:version").
        model = self.model_name
        if ":" in model:
            owner_name, version = model.split(":", 1)
            url = f"{API_BASE}/predictions"
            body = {"version": version, "input": self._build_input(task)}
        else:
            url = f"{API_BASE}/models/{model}/predictions"
            body = {"input": self._build_input(task)}
        resp = await client.post(url, headers=self._headers(), json=body, timeout=120.0)
        self.raise_for_status(resp)
        data = resp.json()
        poll_url = (data.get("urls") or {}).get("get")
        return ProviderJob(
            provider=self.provider_name,
            model=self.model_name,
            job_id=data.get("id"),
            poll_url=poll_url,
            raw=data,
        )

    async def poll(self, job: ProviderJob, client: httpx.AsyncClient) -> ProviderResult:
        poll_url = job.poll_url or f"{API_BASE}/predictions/{job.job_id}"
        deadline = 600.0
        waited = 0.0
        interval = 2.0
        while waited < deadline:
            resp = await client.get(poll_url, headers=self._headers(), timeout=60.0)
            self.raise_for_status(resp)
            data = resp.json()
            status = data.get("status")
            if status == "succeeded":
                return self._parse_result(data)
            if status in ("failed", "canceled"):
                from ..errors import ProviderError

                raise ProviderError(
                    f"Replicate prediction {status}: {data.get('error')}",
                    provider=self.provider_name,
                    model=self.model_name,
                )
            await asyncio.sleep(interval)
            waited += interval
            interval = min(interval * 1.3, 10.0)
        raise ProviderTimeoutError(
            f"Replicate prediction {job.job_id} timed out after {deadline:.0f}s",
            provider=self.provider_name,
            model=self.model_name,
        )

    def _parse_result(self, data: dict) -> ProviderResult:
        output = data.get("output")
        urls: list[str] = []
        if isinstance(output, str):
            urls = [output]
        elif isinstance(output, list):
            urls = [u for u in output if isinstance(u, str)]
        elif isinstance(output, dict) and output.get("image"):
            urls = [output["image"]]
        images = [RemoteImage(url=u, suggested_ext=_ext_from_url(u)) for u in urls]
        return ProviderResult(
            provider=self.provider_name,
            model=self.model_name,
            provider_job_id=data.get("id"),
            images=images,
            raw=data,
        )


def _ext_from_url(url: str) -> str:
    lower = url.lower().split("?")[0]
    for ext in ("png", "jpg", "jpeg", "webp"):
        if lower.endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    return "png"
