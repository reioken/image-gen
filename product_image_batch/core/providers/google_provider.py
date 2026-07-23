"""Google Gemini image adapter (Gemini API / generateContent).

Sends the prompt plus inline base64 image parts to
``https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent``
and reads inline image data back from the response candidates. Multiple
references are supported and numbered in the prompt by the rewriter.

Auth: ``x-goog-api-key: <GOOGLE_API_KEY>``.
"""

from __future__ import annotations

import httpx

from ..errors import ProviderError
from ..models import GenerationTask, ProviderJob, ProviderResult, RemoteImage
from ..utils import images as imgutil
from .base import BaseProvider

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GoogleProvider(BaseProvider):
    provider_name = "google"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = True
    supports_async_jobs = False
    default_cost_per_image = 0.039
    cost_is_known = False

    def _mime(self, path) -> str:
        return imgutil.MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        key = self.require_key()
        parts: list[dict] = [{"text": task.prompt_text}]
        for ref in task.reference_images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": self._mime(ref),
                        "data": imgutil.to_base64(ref),
                    }
                }
            )
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        url = f"{API_BASE}/{self.model_name}:generateContent"
        resp = await client.post(
            url,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=body,
            timeout=300.0,
        )
        self.raise_for_status(resp)
        result = self._parse_result(resp.json())
        return ProviderJob(
            provider=self.provider_name, model=self.model_name, inline_result=result
        )

    def _parse_result(self, data: dict) -> ProviderResult:
        images: list[RemoteImage] = []
        for cand in data.get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []):
                inline = part.get("inline_data") or part.get("inlineData")
                if inline and inline.get("data"):
                    ct = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                    images.append(
                        RemoteImage(
                            b64_data=inline["data"],
                            content_type=ct,
                            suggested_ext=imgutil.ext_for_content_type(ct),
                        )
                    )
        if not images:
            raise ProviderError(
                "Gemini returned no image data.",
                provider=self.provider_name,
                model=self.model_name,
            )
        return ProviderResult(
            provider=self.provider_name, model=self.model_name, images=images, raw=data
        )
