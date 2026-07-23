from pathlib import Path

from product_image_batch.core.models import GenerationTask
from product_image_batch.core.utils.files import sanitize_component, unique_path


def test_sanitize_replaces_slashes_and_colons():
    assert sanitize_component("fal-ai/flux-pro/kontext") == "fal-ai_flux-pro_kontext"
    assert sanitize_component("openai:gpt-image-1.5") == "openai_gpt-image-1.5"


def test_sanitize_collapses_and_trims_separators():
    assert sanitize_component("a///b:::c") == "a_b_c"
    assert sanitize_component("//weird//") == "weird"
    assert sanitize_component("") == "unknown"


def test_sanitize_only_allows_safe_chars():
    out = sanitize_component("Ünïcødé name!@# 42")
    assert all(c.isalnum() or c in "._-" for c in out)


def test_output_basename_is_safe():
    task = GenerationTask(
        task_id="t", prompt_id="p004", prompt_text="x",
        provider="fal", model="fal-ai/product-photography",
    )
    name = task.output_basename("20260723T202101Z")
    assert name == "fal_fal-ai_product-photography_p004_20260723T202101Z_0001"
    assert "/" not in name and ":" not in name


def test_unique_path_avoids_collision(tmp_path: Path):
    p = tmp_path / "img.png"
    p.write_bytes(b"x")
    u = unique_path(p)
    assert u.name == "img_1.png"
    u.write_bytes(b"y")
    assert unique_path(p).name == "img_2.png"
