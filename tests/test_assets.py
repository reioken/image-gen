from pathlib import Path

import pytest
from PIL import Image

from product_image_batch.core.assets import (
    collect_reference_paths,
    prepare_assets_sync,
    validate_assets,
)
from product_image_batch.core.utils import images as imgutil


def test_validate_accepts_png(ref_image: Path):
    validate_assets([ref_image], None)  # no exception


def test_validate_rejects_missing(tmp_path: Path):
    with pytest.raises(imgutil.ImageValidationError):
        validate_assets([tmp_path / "nope.png"], None)


def test_validate_rejects_unsupported_format(tmp_path: Path):
    bad = tmp_path / "x.gif"
    Image.new("RGB", (10, 10)).save(bad)
    with pytest.raises(imgutil.ImageValidationError):
        imgutil.validate_reference(bad)


def test_validate_requires_at_least_one_reference():
    with pytest.raises(imgutil.ImageValidationError):
        validate_assets([], None)


def test_mask_must_match_dimensions(ref_image: Path, tmp_path: Path):
    wrong = tmp_path / "mask.png"
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(wrong)
    with pytest.raises(imgutil.ImageValidationError):
        validate_assets([ref_image], wrong)


def test_mask_must_be_png(ref_image: Path, tmp_path: Path):
    j = tmp_path / "mask.jpg"
    Image.new("RGB", (128, 128)).save(j)
    with pytest.raises(imgutil.ImageValidationError):
        imgutil.preflight_mask(j, ref_image)


def test_valid_mask_passes(ref_image: Path, mask_image: Path):
    validate_assets([ref_image], mask_image)


def test_prepare_assets_builds_data_urls(ref_image: Path, mask_image: Path):
    assets = prepare_assets_sync([ref_image], mask_image)
    assert len(assets.base64_data_urls) == 1
    assert assets.base64_data_urls[0].startswith("data:image/png;base64,")
    assert assets.mask_base64_data_url is not None


def test_collect_reference_paths_dedupes_and_reads_dir(tmp_path: Path):
    d = tmp_path / "refs"
    d.mkdir()
    a = d / "a.png"
    b = d / "b.jpg"
    Image.new("RGB", (10, 10)).save(a)
    Image.new("RGB", (10, 10)).save(b)
    paths = collect_reference_paths([a], d)
    # a appears once despite being both explicit and in the dir.
    assert sorted(p.name for p in paths) == ["a.png", "b.jpg"]
