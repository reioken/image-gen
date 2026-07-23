"""Headless engine for product-image-batch.

Public API re-exports so callers (CLI, GUI, tests) can do::

    from product_image_batch.core import GlobalScheduler, GenerationTask, load_config
"""

from .config import AppConfig, ProviderConfig, RetryConfig, load_config
from .errors import (
    ProviderAuthError,
    ProviderContentPolicyError,
    ProviderError,
    ProviderInvalidInputError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from .models import (
    CostEstimate,
    ErrorRecord,
    GenerationTask,
    MetadataRecord,
    PreparedAssets,
    ProviderJob,
    ProviderResult,
    SavedImage,
    TaskStatus,
)

__all__ = [
    "AppConfig",
    "ProviderConfig",
    "RetryConfig",
    "load_config",
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderContentPolicyError",
    "ProviderInvalidInputError",
    "ProviderTimeoutError",
    "ProviderTransientError",
    "CostEstimate",
    "ErrorRecord",
    "GenerationTask",
    "MetadataRecord",
    "PreparedAssets",
    "ProviderJob",
    "ProviderResult",
    "SavedImage",
    "TaskStatus",
]
