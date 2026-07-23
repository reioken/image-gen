"""Registry mapping provider names to adapter classes."""

from __future__ import annotations

from ..config import PROVIDER_ENV_KEYS, AppConfig, ProviderConfig
from .base import BaseProvider
from .bfl_provider import BFLProvider
from .fal_provider import FalProvider
from .freepik_provider import FreepikProvider
from .google_provider import GoogleProvider
from .ideogram_provider import IdeogramProvider
from .leonardo_provider import LeonardoProvider
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider
from .recraft_provider import RecraftProvider
from .replicate_provider import ReplicateProvider
from .stability_provider import StabilityProvider

PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "bfl": BFLProvider,
    "stability": StabilityProvider,
    "fal": FalProvider,
    "replicate": ReplicateProvider,
    "ideogram": IdeogramProvider,
    "recraft": RecraftProvider,
    "leonardo": LeonardoProvider,
    "freepik": FreepikProvider,
    "mock": MockProvider,
}


def available_providers() -> list[str]:
    return list(PROVIDER_CLASSES.keys())


def provider_supports_reference_images(name: str) -> bool:
    cls = PROVIDER_CLASSES.get(name)
    return bool(cls and cls.supports_reference_images)


def create_provider(
    name: str,
    config: ProviderConfig,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseProvider:
    cls = PROVIDER_CLASSES.get(name)
    if cls is None:
        raise KeyError(f"No adapter registered for provider '{name}'")
    return cls(config=config, api_key=api_key, model=model)


def resolve_api_key(name: str, env: dict[str, str]) -> str | None:
    key_var = PROVIDER_ENV_KEYS.get(name)
    if not key_var:
        return None
    return env.get(key_var) or None


__all__ = [
    "PROVIDER_CLASSES",
    "available_providers",
    "provider_supports_reference_images",
    "create_provider",
    "resolve_api_key",
    "AppConfig",
]
