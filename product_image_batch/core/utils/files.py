"""Filename sanitization and small filesystem helpers."""

from __future__ import annotations

import re
from pathlib import Path

_ALLOWED = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize_component(value: str) -> str:
    """Make a string safe for use as a single filename component.

    Only ``[a-zA-Z0-9._-]`` survive; everything else (including ``/`` and ``:``
    from model names like ``fal-ai/flux`` or ``openai:gpt-image-1``) becomes
    ``_``. Consecutive separators are collapsed and leading/trailing separators
    trimmed so names stay tidy.
    """
    if value is None:
        return "unknown"
    cleaned = _ALLOWED.sub("_", str(value))
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_")
    return cleaned or "unknown"


def unique_path(path: Path) -> Path:
    """Return ``path`` or, if it exists, ``stem_1``, ``stem_2`` … to avoid clobber."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
