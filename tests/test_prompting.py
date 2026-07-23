from pathlib import Path

from product_image_batch.core.prompting import (
    PromptRewriter,
    PromptVariant,
    load_prompts,
    resolved_prompts_to_json,
)


def test_load_txt_prompts_skips_comments(tmp_path: Path):
    f = tmp_path / "p.txt"
    f.write_text("# header\nStudio shot\n\nOutdoor shot\n", encoding="utf-8")
    variants = load_prompts(prompts_path=f)
    assert [v.text for v in variants] == ["Studio shot", "Outdoor shot"]
    assert variants[0].prompt_id == "p001"
    assert variants[1].prompt_id == "p002"


def test_load_json_prompts(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text(
        '[{"text": "a", "negative_prompt": "bad", "provider_overrides": {"openai": "A!"}}]',
        encoding="utf-8",
    )
    variants = load_prompts(prompts_path=f)
    assert variants[0].negative_prompt == "bad"
    assert variants[0].text_for("openai") == "A!"


def test_rewriter_adds_preservation_and_negative():
    rw = PromptRewriter()
    v = PromptVariant("p001", "hero", "Studio shot")
    out = rw.rewrite_variant(v, ["openai", "bfl"], with_mask=False)
    assert "openai" in out.provider_overrides and "bfl" in out.provider_overrides
    assert "Preserve" in out.provider_overrides["openai"]
    assert out.negative_prompt  # a default negative prompt is attached


def test_rewriter_respects_explicit_override():
    rw = PromptRewriter()
    v = PromptVariant("p001", "hero", "Studio shot", provider_overrides={"openai": "CUSTOM"})
    out = rw.rewrite_variant(v, ["openai"], with_mask=False)
    assert out.provider_overrides["openai"] == "CUSTOM"


def test_mask_instruction_added_when_masked():
    rw = PromptRewriter()
    v = PromptVariant("p001", "hero", "Studio shot")
    out = rw.rewrite_variant(v, ["openai"], with_mask=True)
    assert "masked" in out.provider_overrides["openai"].lower()


def test_generate_from_brief_produces_n_variants():
    rw = PromptRewriter()
    variants = rw.generate_from_brief("A luxury perfume bottle", 5, ["openai"])
    assert len(variants) == 5
    assert all(v.provider_overrides.get("openai") for v in variants)
    # ids are unique
    assert len({v.prompt_id for v in variants}) == 5


def test_resolved_prompts_json_roundtrip():
    rw = PromptRewriter()
    variants = rw.generate_from_brief("brief", 2, ["openai"])
    data = resolved_prompts_to_json(variants)
    assert data[0]["provider_overrides"]["openai"]
    assert "negative_prompt" in data[0]
