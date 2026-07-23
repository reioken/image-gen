"""Configuration loading and merging.

Two layers of configuration exist:

* ``config/providers.yaml`` — engine defaults shipped with the app (concurrency,
  rate limits, model lists). Loaded into :class:`AppConfig`.
* ``settings.json`` — the user's runtime settings (API keys live in ``.env``,
  not here), stored per-user under the app-data dir and edited from the GUI
  settings dialog. Merged on top of the YAML via :meth:`AppConfig.apply_settings`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import sys

import yaml
from pydantic import BaseModel, Field

from .utils.logging import app_data_dir


def resource_root() -> Path:
    """Root that holds bundled resources (config/, .env.example).

    In a PyInstaller build the data files are unpacked to ``sys._MEIPASS``; from
    a source checkout they live at the repository root.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


_PKG_ROOT = resource_root()
DEFAULT_CONFIG_PATH = _PKG_ROOT / "config" / "providers.yaml"
DEFAULT_SETTINGS_TEMPLATE = _PKG_ROOT / "config" / "settings.default.json"

# Maps provider name -> the env var that carries its API key.
PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "bfl": "BFL_API_KEY",
    "stability": "STABILITY_API_KEY",
    "fal": "FAL_KEY",
    "replicate": "REPLICATE_API_TOKEN",
    "ideogram": "IDEOGRAM_API_KEY",
    "recraft": "RECRAFT_API_TOKEN",
    "leonardo": "LEONARDO_API_KEY",
    "freepik": "FREEPIK_API_KEY",
    "mock": "",  # never needs a key
}


class RetryConfig(BaseModel):
    max_retries: int = 3
    initial_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 60.0
    jitter: bool = True
    retry_statuses: list[int] = Field(
        default_factory=lambda: [408, 409, 425, 429, 500, 502, 503, 504]
    )


class ProviderConfig(BaseModel):
    name: str
    enabled: bool = False
    max_concurrent: int = 2
    rate_limit_per_minute: float | None = None
    rate_limit_per_10s: float | None = None
    supports_reference_images: bool = True
    supports_masks: bool = False
    default_model: str | None = None
    models: list[str] = Field(default_factory=list)

    def rate_per_second(self) -> tuple[float, float] | None:
        """Return ``(max_rate, period_seconds)`` or ``None`` if unlimited."""
        if self.rate_limit_per_10s is not None:
            return (float(self.rate_limit_per_10s), 10.0)
        if self.rate_limit_per_minute is not None:
            return (float(self.rate_limit_per_minute), 60.0)
        return None

    def resolve_model(self, model: str | None) -> str:
        if model:
            return model
        if self.default_model:
            return self.default_model
        if self.models:
            return self.models[0]
        return self.name


class AppConfig(BaseModel):
    global_max_concurrent: int = 20
    retry: RetryConfig = Field(default_factory=RetryConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # --- lookups -----------------------------------------------------------
    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown provider '{name}'") from exc

    def enabled_providers(self) -> list[str]:
        return [n for n, p in self.providers.items() if p.enabled]

    def has_api_key(self, name: str, env: dict[str, str] | None = None) -> bool:
        env = env if env is not None else os.environ
        key_var = PROVIDER_ENV_KEYS.get(name)
        if key_var == "":  # mock — no key needed
            return True
        if not key_var:
            return False
        return bool(env.get(key_var, "").strip())

    # --- settings overlay --------------------------------------------------
    def apply_settings(self, settings: dict[str, Any]) -> "AppConfig":
        """Overlay a user settings dict (from settings.json) onto this config."""
        if not settings:
            return self
        gmc = settings.get("global_max_concurrent")
        if gmc:
            self.global_max_concurrent = int(gmc)
        if settings.get("max_retries") is not None:
            self.retry.max_retries = int(settings["max_retries"])
        if settings.get("auto_retry") is False:
            self.retry.max_retries = 0

        per_prov = settings.get("per_provider_concurrency", {}) or {}
        enabled = settings.get("enabled_providers", {}) or {}
        for name, prov in self.providers.items():
            if name in per_prov:
                prov.max_concurrent = int(per_prov[name])
            if name in enabled:
                prov.enabled = bool(enabled[name])
        return self


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load provider config from YAML into an :class:`AppConfig`."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Provider config not found: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    providers: dict[str, ProviderConfig] = {}
    for name, pdata in (raw.get("providers") or {}).items():
        pdata = dict(pdata or {})
        pdata["name"] = name
        providers[name] = ProviderConfig(**pdata)

    retry = RetryConfig(**(raw.get("retry") or {}))
    return AppConfig(
        global_max_concurrent=int(raw.get("global_max_concurrent", 20)),
        retry=retry,
        providers=providers,
    )


# --- settings.json persistence --------------------------------------------

def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    """Load user settings, creating them from the template on first run."""
    path = settings_path()
    if not path.exists():
        return ensure_user_settings()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_settings()


def _default_settings() -> dict[str, Any]:
    if DEFAULT_SETTINGS_TEMPLATE.exists():
        try:
            return json.loads(DEFAULT_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"global_max_concurrent": 20, "auto_retry": True, "max_retries": 3}


def ensure_user_settings() -> dict[str, Any]:
    """Create the per-user settings.json from the template if it doesn't exist."""
    path = settings_path()
    data = _default_settings()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
    return data


def save_settings(settings: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def ensure_user_env() -> Path:
    """Ensure a per-user ``.env`` exists (created from ``.env.example``).

    Returns the path to the per-user ``.env`` so the GUI can point users at it.
    """
    env_path = app_data_dir() / ".env"
    if env_path.exists():
        return env_path
    template = _PKG_ROOT / ".env.example"
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        if template.exists():
            env_path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.write_text("", encoding="utf-8")
    except OSError:
        pass
    return env_path
