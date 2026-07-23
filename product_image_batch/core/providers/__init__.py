"""Provider adapters and the adapter registry.

Each adapter encapsulates auth, request format, asset-upload strategy, job
polling, download and error normalization for one provider. The scheduler only
ever talks to the :class:`~product_image_batch.core.providers.base.BaseProvider`
interface, never to a provider's internals.
"""

from __future__ import annotations

from .base import BaseProvider, ImageProviderAdapter
from .registry import (
    PROVIDER_CLASSES,
    available_providers,
    create_provider,
    provider_supports_reference_images,
)

__all__ = [
    "BaseProvider",
    "ImageProviderAdapter",
    "PROVIDER_CLASSES",
    "available_providers",
    "create_provider",
    "provider_supports_reference_images",
]
