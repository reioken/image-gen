"""OpenAI adapter tests using mocked HTTP (respx) — no real API calls."""

from __future__ import annotations

import base64
import io

import httpx
import pytest
import respx
from PIL import Image

from product_image_batch.core.config import load_config
from product_image_batch.core.errors import (
    ProviderInvalidInputError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from product_image_batch.core.models import GenerationTask
from product_image_batch.core.providers.openai_provider import API_URL, OpenAIProvider


def _b64_png() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _provider():
    cfg = load_config().provider("openai")
    return OpenAIProvider(cfg, api_key="sk-test", model="gpt-image-1")


def _task(ref):
    return GenerationTask(
        task_id="t", prompt_id="p001", prompt_text="studio shot",
        provider="openai", model="gpt-image-1", reference_images=[ref],
        size="1024x1024", quality="high",
    )


@respx.mock
async def test_openai_success(ref_image):
    respx.post(API_URL).mock(
        return_value=httpx.Response(200, json={"id": "img_1", "data": [{"b64_json": _b64_png()}]})
    )
    prov = _provider()
    async with httpx.AsyncClient() as client:
        result = await prov.generate(_task(ref_image), client)
    assert len(result.images) == 1
    assert result.images[0].b64_data


@respx.mock
async def test_openai_rate_limit_maps_to_error(ref_image):
    respx.post(API_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "1"}, json={"error": "slow"})
    )
    prov = _provider()
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderRateLimitError) as exc:
            await prov.generate(_task(ref_image), client)
    assert exc.value.retry_after == 1.0
    assert exc.value.retryable is True


@respx.mock
async def test_openai_500_is_transient(ref_image):
    respx.post(API_URL).mock(return_value=httpx.Response(500, text="boom"))
    prov = _provider()
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderTransientError):
            await prov.generate(_task(ref_image), client)


@respx.mock
async def test_openai_400_is_invalid_input(ref_image):
    respx.post(API_URL).mock(return_value=httpx.Response(400, json={"error": "bad prompt"}))
    prov = _provider()
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderInvalidInputError):
            await prov.generate(_task(ref_image), client)


@respx.mock
async def test_openai_timeout_raises(ref_image):
    respx.post(API_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    prov = _provider()
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.TimeoutException):
            await prov.generate(_task(ref_image), client)


async def test_openai_missing_key_raises(ref_image):
    from product_image_batch.core.errors import ProviderAuthError

    cfg = load_config().provider("openai")
    prov = OpenAIProvider(cfg, api_key=None, model="gpt-image-1")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderAuthError):
            await prov.generate(_task(ref_image), client)


async def test_openai_cost_estimate():
    prov = _provider()
    est = await prov.estimate_cost(_task(ref_image=None) if False else GenerationTask(
        task_id="t", prompt_id="p", prompt_text="x", provider="openai",
        model="gpt-image-1", size="1024x1024", quality="high",
    ))
    assert est.known is True
    assert est.amount_usd == 0.167
