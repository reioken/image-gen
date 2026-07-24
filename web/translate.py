"""Auto-translation for the design editor's pack export.

Product-image captions are short marketing texts. This module translates a
batch of them from a source language into several targets using OpenAI's chat
completions API. It is intentionally tiny: one call per target language (each
returns a JSON array in input order), run concurrently. Results are always
editable in the UI, so a wrong or empty translation is never fatal.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx

# Language code -> (English name, German folder name for the pack export).
LANGUAGES: dict[str, tuple[str, str]] = {
    "de": ("German", "deutsch"),
    "en": ("English", "englisch"),
    "fr": ("French", "franzoesisch"),
    "it": ("Italian", "italienisch"),
    "es": ("Spanish", "spanisch"),
    "pl": ("Polish", "polnisch"),
}

_API_URL = "https://api.openai.com/v1/chat/completions"


def _model() -> str:
    return os.environ.get("WEB_TRANSLATE_MODEL", "").strip() or "gpt-4o-mini"


class TranslateError(RuntimeError):
    pass


async def _one_language(
    texts: list[str], source: str, target: str, *, api_key: str, client: httpx.AsyncClient
) -> list[str]:
    """Translate ``texts`` into a single ``target`` language, order preserved."""
    src_name = LANGUAGES.get(source, (source, source))[0]
    tgt_name = LANGUAGES.get(target, (target, target))[0]
    system = (
        "You are a professional product-marketing translator. You translate "
        "short product-image captions and headlines. Keep them punchy, "
        "idiomatic and roughly the same length as the source. Preserve line "
        "breaks and any product/brand names. Do not add quotes or commentary."
    )
    user = (
        f"Translate these {len(texts)} caption(s) from {src_name} into "
        f"{tgt_name}. Return ONLY a JSON object of the form "
        f'{{"items": ["...", ...]}} with exactly {len(texts)} strings in the '
        f"same order.\n\n" + json.dumps(texts, ensure_ascii=False)
    )
    payload = {
        "model": _model(),
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = await client.post(
        _API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60.0,
    )
    if r.status_code >= 400:
        raise TranslateError(f"OpenAI {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"]["content"]
    try:
        items = json.loads(content).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        raise TranslateError("model returned non-JSON")
    # Be forgiving: pad/truncate to the expected length so the UI stays aligned.
    items = [str(x) for x in items][: len(texts)]
    while len(items) < len(texts):
        items.append(texts[len(items)])
    return items


async def translate_batch(
    texts: list[str],
    *,
    source: str = "de",
    targets: list[str] | None = None,
    api_key: str,
) -> dict[str, list[str]]:
    """Return ``{lang: [translated...]}`` for every target (source echoed back)."""
    if not api_key:
        raise TranslateError("OPENAI_API_KEY is not set on the server")
    targets = targets or [c for c in LANGUAGES if c != source]
    out: dict[str, list[str]] = {source: list(texts)}
    if not texts:
        return {**out, **{t: [] for t in targets}}
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(_one_language(texts, source, t, api_key=api_key, client=client) for t in targets),
            return_exceptions=True,
        )
    for target, res in zip(targets, results):
        # On any per-language failure, fall back to the source text so the
        # editor still has editable rows instead of an aborted request.
        out[target] = list(texts) if isinstance(res, Exception) else res
    return out
