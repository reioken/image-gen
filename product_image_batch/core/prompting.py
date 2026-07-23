"""Prompt loading and the optional prompt-rewriting module.

Two responsibilities:

1. Load prompt variants from ``--prompt`` / ``--prompts`` (txt or json).
2. Optionally rewrite a base brief into many provider-specific prompt variants,
   each carrying product-preservation instructions. When no LLM key is present
   (or ``use_llm`` is false), a deterministic offline rewriter is used so the
   feature works fully offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import resource_root

_PKG_ROOT = resource_root()
DEFAULT_REWRITE_CONFIG = _PKG_ROOT / "config" / "prompt_rewrite.yaml"

# A strong default "master prompt": global consistency rules the user can edit,
# applied to EVERY agent/prompt in a tab so all variants share one identity,
# setting and quality baseline.
DEFAULT_MASTER_PROMPT = """\
PRODUCT CONSISTENCY (applies to every image):
- Keep the exact same product in every image: identical shape, proportions, size ratios, materials, colors, textures and finish.
- Preserve all branding exactly — logo, label text, typography, icons and their placement. Do not alter, translate, reflow, blur or invent any text.
- Do not add, remove, duplicate or swap any product part (cap, lid, nozzle, seams, labels).
- Only the scene may change: background, surface, lighting, camera angle, styling and props.

SETTING & STYLE:
- Photorealistic, high-end commercial product photography.
- Clean studio-grade lighting with soft, believable shadows and accurate reflections.
- Neutral, true-to-life color balance; product tack-sharp; realistic, shallow depth of field.
- Consistent camera height, distance and framing across shots unless a prompt explicitly says otherwise.

QUALITY:
- High resolution, crisp detail. No artifacts, no watermarks, no extra text, no warped geometry, no distortions."""


@dataclass
class PromptVariant:
    prompt_id: str
    base_intent: str
    text: str
    negative_prompt: str | None = None
    provider_overrides: dict[str, str] = field(default_factory=dict)

    def text_for(self, provider: str) -> str:
        return self.provider_overrides.get(provider, self.text)


def load_prompts(
    prompt: str | None = None,
    prompts_path: str | Path | None = None,
) -> list[PromptVariant]:
    """Load prompt variants from a single ``--prompt`` and/or a ``--prompts`` file.

    ``.txt``: one prompt per non-empty, non-``#`` line.
    ``.json``: either a list of strings, or a list of objects with keys
    ``prompt``/``text``/``base_intent``/``negative_prompt``/``provider_overrides``.
    """
    variants: list[PromptVariant] = []

    if prompt:
        variants.append(
            PromptVariant(prompt_id="p001", base_intent=prompt[:60], text=prompt)
        )

    if prompts_path:
        path = Path(prompts_path)
        if not path.exists():
            raise FileNotFoundError(f"Prompts file not found: {path}")
        if path.suffix.lower() == ".json":
            variants.extend(_load_json_prompts(path))
        else:
            variants.extend(_load_txt_prompts(path))

    # Re-index ids so they are unique and stable (p001, p002, …).
    for i, v in enumerate(variants, start=1):
        v.prompt_id = f"p{i:03d}"
    return variants


def _load_txt_prompts(path: Path) -> list[PromptVariant]:
    out: list[PromptVariant] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(PromptVariant(prompt_id="tmp", base_intent=line[:60], text=line))
    return out


def _load_json_prompts(path: Path) -> list[PromptVariant]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[PromptVariant] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                out.append(PromptVariant(prompt_id="tmp", base_intent=item[:60], text=item))
            elif isinstance(item, dict):
                text = item.get("text") or item.get("prompt") or ""
                out.append(
                    PromptVariant(
                        prompt_id=str(item.get("prompt_id", "tmp")),
                        base_intent=str(item.get("base_intent", text[:60])),
                        text=text,
                        negative_prompt=item.get("negative_prompt"),
                        provider_overrides=dict(item.get("provider_overrides", {})),
                    )
                )
    return out


def load_rewrite_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_REWRITE_CONFIG
    if not cfg_path.exists():
        return {}
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return raw.get("rewrite", raw)


class PromptRewriter:
    """Turns prompt variants (or a base brief) into provider-specific prompts.

    The offline path (default) is deterministic: it appends preservation
    instructions and a provider hint to each prompt, and attaches a negative
    prompt. An LLM path can be enabled via config, but is optional and never
    required for the tool to function.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_rewrite_config()
        self.preservation = self.config.get("preservation_instructions", [])
        self.mask_instruction = self.config.get("mask_instruction", "")
        self.default_negative = self.config.get("default_negative_prompt", "").strip() or None
        self.provider_hints: dict[str, str] = self.config.get("provider_hints", {})

    def _preservation_block(self, with_mask: bool) -> str:
        lines = list(self.preservation)
        if with_mask and self.mask_instruction:
            lines.append(self.mask_instruction)
        return " ".join(lines)

    def rewrite_variant(
        self,
        variant: PromptVariant,
        providers: list[str],
        *,
        with_mask: bool = False,
        master_prompt: str = "",
    ) -> PromptVariant:
        """Return a new variant with provider_overrides + negative_prompt filled.

        ``master_prompt`` is a tab-wide rule block prepended to every provider's
        prompt so all agents share the same consistency/setting requirements.
        """
        preservation = self._preservation_block(with_mask)
        master = (master_prompt or "").strip()
        overrides: dict[str, str] = dict(variant.provider_overrides)
        for provider in providers:
            if provider in overrides:
                continue  # respect explicit overrides from the prompts file
            hint = self.provider_hints.get(provider, "")
            # Order: global master rules → provider hint → this shot's prompt →
            # preservation reminders. The master rules lead so they anchor every image.
            parts = [p for p in (master, hint, variant.text, preservation) if p]
            overrides[provider] = "\n\n".join(parts).strip()
        negative = variant.negative_prompt or self.default_negative
        return PromptVariant(
            prompt_id=variant.prompt_id,
            base_intent=variant.base_intent,
            text=variant.text,
            negative_prompt=negative,
            provider_overrides=overrides,
        )

    def rewrite_all(
        self,
        variants: list[PromptVariant],
        providers: list[str],
        *,
        with_mask: bool = False,
        master_prompt: str = "",
    ) -> list[PromptVariant]:
        return [
            self.rewrite_variant(v, providers, with_mask=with_mask, master_prompt=master_prompt)
            for v in variants
        ]

    def generate_from_brief(
        self,
        brief: str,
        count: int,
        providers: list[str],
        *,
        with_mask: bool = False,
        master_prompt: str = "",
    ) -> list[PromptVariant]:
        """Offline brief expansion: create ``count`` scene variations of a brief.

        Deliberately simple and deterministic (no network). Each variant reuses
        the brief with a different scene/lighting angle so the batch explores a
        spread of looks while keeping the product identical.
        """
        scenes = [
            "premium studio packshot on a seamless warm-beige background, soft key light, hero angle",
            "e-commerce white-background catalog shot, 85mm lens, crisp even lighting",
            "outdoor lifestyle shot on wet stone after rain, cinematic dusk light",
            "reflective black acrylic surface, dramatic rim light, luxury feel",
            "minimal pastel studio scene, soft shadows, top-down flat-lay",
            "natural wood tabletop with morning window light and gentle bokeh",
            "moody dark studio with a single spotlight and long shadow",
            "bright airy scene with fresh greenery and diffused daylight",
            "marble surface with subtle gold accents, editorial styling",
            "concrete industrial backdrop, hard directional light, modern look",
        ]
        variants: list[PromptVariant] = []
        for i in range(count):
            scene = scenes[i % len(scenes)]
            text = f"{brief.strip()} — {scene}."
            variants.append(
                PromptVariant(
                    prompt_id=f"p{i + 1:03d}",
                    base_intent=scene,
                    text=text,
                )
            )
        return self.rewrite_all(
            variants, providers, with_mask=with_mask, master_prompt=master_prompt
        )


def resolved_prompts_to_json(variants: list[PromptVariant]) -> list[dict[str, Any]]:
    """Serialize variants for ``prompts.resolved.json``."""
    return [
        {
            "prompt_id": v.prompt_id,
            "base_intent": v.base_intent,
            "text": v.text,
            "negative_prompt": v.negative_prompt,
            "provider_overrides": v.provider_overrides,
        }
        for v in variants
    ]
