"""Reference-image and mask preparation.

``prepare_assets`` runs once per reference-image set (per GUI tab / per CLI run)
and produces a :class:`PreparedAssets` bundle that every task reuses. Providers
pick whichever representation they need (local path, base64 data-URL, or an
uploaded URL/file-id they populate later).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from .models import PreparedAssets
from .utils import images as imgutil
from .utils.logging import get_logger

log = get_logger(__name__)


def collect_reference_paths(
    references: list[Path] | None = None,
    reference_dir: Path | None = None,
) -> list[Path]:
    """Gather reference image paths from explicit files and/or a directory."""
    paths: list[Path] = []
    for ref in references or []:
        paths.append(Path(ref))
    if reference_dir is not None:
        d = Path(reference_dir)
        if not d.is_dir():
            raise imgutil.ImageValidationError(f"--reference-dir is not a directory: {d}")
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in imgutil.ACCEPTED_SUFFIXES:
                paths.append(p)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def validate_assets(references: list[Path], mask: Path | None) -> None:
    """Validate all references and the mask up-front, raising on the first error."""
    if not references:
        raise imgutil.ImageValidationError("At least one reference image is required.")
    for ref in references:
        imgutil.validate_reference(ref)
    if mask is not None:
        imgutil.preflight_mask(mask, references[0] if references else None)


def copy_into_run(
    references: list[Path],
    mask: Path | None,
    out_dir: Path,
) -> tuple[list[Path], Path | None]:
    """Copy references/mask into the run's ``refs/`` and ``masks/`` folders.

    Returns the new (copied) paths so metadata references live next to outputs.
    """
    refs_dir = out_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for ref in references:
        dst = refs_dir / ref.name
        if ref.resolve() != dst.resolve():
            shutil.copy2(ref, dst)
        copied.append(dst)

    mask_copy: Path | None = None
    if mask is not None:
        masks_dir = out_dir / "masks"
        masks_dir.mkdir(parents=True, exist_ok=True)
        mask_copy = masks_dir / mask.name
        if mask.resolve() != mask_copy.resolve():
            shutil.copy2(mask, mask_copy)
    return copied, mask_copy


def _build_sync(references: list[Path], mask: Path | None) -> PreparedAssets:
    data_urls = [imgutil.to_data_url(p) for p in references]
    mask_data_url = imgutil.to_data_url(mask) if mask is not None else None
    return PreparedAssets(
        local_paths=list(references),
        base64_data_urls=data_urls,
        mask_local_path=mask,
        mask_base64_data_url=mask_data_url,
    )


async def prepare_assets(references: list[Path], mask: Path | None = None) -> PreparedAssets:
    """Validate and build a :class:`PreparedAssets` bundle (base64 done off-loop)."""
    validate_assets(references, mask)
    # base64 encoding of possibly-large images is CPU/IO bound; keep it off the
    # event loop so the GUI never stutters.
    return await asyncio.to_thread(_build_sync, references, mask)


def prepare_assets_sync(references: list[Path], mask: Path | None = None) -> PreparedAssets:
    """Synchronous variant for the CLI / tests."""
    validate_assets(references, mask)
    return _build_sync(references, mask)
