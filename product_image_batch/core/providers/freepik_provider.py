"""Freepik / Magnific adapter — skeleton (off by default).

The public Mystic API request schema could not be verified during development,
so this adapter is intentionally a skeleton. It raises a clear, actionable error
until a user supplies the endpoint/schema for their account. Enable it in
``config/providers.yaml`` and fill in ``submit`` once you have the docs.
"""

from __future__ import annotations

import httpx

from ..errors import ProviderInvalidInputError
from ..models import GenerationTask, ProviderJob
from .base import BaseProvider


class FreepikProvider(BaseProvider):
    provider_name = "freepik"
    supports_reference_images = True
    supports_masks = False
    supports_multiple_references = True
    supports_async_jobs = True
    default_cost_per_image = 0.05
    cost_is_known = False

    async def submit(self, task: GenerationTask, client: httpx.AsyncClient) -> ProviderJob:
        raise ProviderInvalidInputError(
            "The Freepik/Magnific adapter is a skeleton. Provide the Mystic API "
            "endpoint and request schema for your account, then implement "
            "FreepikProvider.submit(). It is disabled by default for this reason.",
            provider=self.provider_name,
            model=self.model_name,
        )
