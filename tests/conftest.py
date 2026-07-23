"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

from product_image_batch.core.config import ProviderConfig, load_config
from product_image_batch.core.providers import registry

# Make the sibling ``probe`` helper importable as a top-level module.
sys.path.insert(0, str(Path(__file__).parent))
from probe import FlakyProvider, ProbeProvider  # noqa: E402


@pytest.fixture
def ref_image(tmp_path: Path) -> Path:
    p = tmp_path / "product.png"
    Image.new("RGB", (128, 128), (200, 100, 50)).save(p)
    return p


@pytest.fixture
def second_ref_image(tmp_path: Path) -> Path:
    p = tmp_path / "product_side.png"
    Image.new("RGB", (128, 128), (50, 100, 200)).save(p)
    return p


@pytest.fixture
def mask_image(tmp_path: Path) -> Path:
    p = tmp_path / "mask.png"
    Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(p)
    return p


@pytest.fixture
def config():
    cfg = load_config()
    cfg.providers["mock"].enabled = True
    return cfg


@pytest.fixture
def probe_config(monkeypatch):
    """Register the probe/flaky providers and return a config that enables them."""
    monkeypatch.setitem(registry.PROVIDER_CLASSES, "probe", ProbeProvider)
    monkeypatch.setitem(registry.PROVIDER_CLASSES, "flaky", FlakyProvider)
    cfg = load_config()
    cfg.providers["probe"] = ProviderConfig(
        name="probe", enabled=True, max_concurrent=3,
        default_model="probe-v1", models=["probe-v1"],
    )
    cfg.global_max_concurrent = 100
    ProbeProvider.reset()
    return cfg
