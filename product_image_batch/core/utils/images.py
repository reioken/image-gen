"""Image helpers: preflight, format conversion, base64 data-URLs, thumbnails.

Pillow is used everywhere. All functions are synchronous and fast; callers that
need them off the event loop should wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from PIL import Image

ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class ImageValidationError(ValueError):
    """Raised when a reference image or mask fails preflight."""


def validate_reference(path: Path, max_bytes: int = 50 * 1024 * 1024) -> None:
    """Validate an image path: exists, accepted format, under ``max_bytes``.

    Raises :class:`ImageValidationError` with a clear message on any problem.
    """
    if not path.exists():
        raise ImageValidationError(f"Reference image not found: {path}")
    if path.suffix.lower() not in ACCEPTED_SUFFIXES:
        raise ImageValidationError(
            f"Unsupported format '{path.suffix}' for {path.name}; "
            f"allowed: {sorted(ACCEPTED_SUFFIXES)}"
        )
    size = path.stat().st_size
    if size == 0:
        raise ImageValidationError(f"Reference image is empty: {path.name}")
    if size > max_bytes:
        raise ImageValidationError(
            f"Reference image {path.name} is {size / 1e6:.1f} MB, over the "
            f"{max_bytes / 1e6:.0f} MB limit."
        )
    # Confirm it actually decodes as an image.
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception as exc:  # noqa: BLE001 — surface a clean message
        raise ImageValidationError(f"Cannot read {path.name} as an image: {exc}") from exc


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def preflight_mask(mask: Path, first_reference: Path | None) -> None:
    """Validate a mask: must be PNG, have an alpha channel and (if a reference is
    given) match its dimensions. Raises :class:`ImageValidationError` on failure.
    """
    if not mask.exists():
        raise ImageValidationError(f"Mask not found: {mask}")
    if mask.suffix.lower() != ".png":
        raise ImageValidationError(f"Mask must be a PNG file, got {mask.suffix}")
    if mask.stat().st_size > 4 * 1024 * 1024:
        raise ImageValidationError("Mask must be under 4 MB.")
    with Image.open(mask) as im:
        mask_mode = im.mode
        mask_size = im.size
    if "A" not in mask_mode and mask_mode != "L":
        raise ImageValidationError(
            f"Mask should have an alpha channel (RGBA/LA) or be grayscale; got mode {mask_mode}."
        )
    if first_reference is not None:
        ref_size = image_size(first_reference)
        if mask_size != ref_size:
            raise ImageValidationError(
                f"Mask dimensions {mask_size} do not match the first reference "
                f"image {ref_size}."
            )


def to_data_url(path: Path) -> str:
    """Return a ``data:<mime>;base64,<...>`` URL for a local image."""
    mime = MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def to_base64(path: Path) -> str:
    """Return the raw base64 string (no data-URL prefix)."""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def convert_format(src: Path, dst: Path, fmt: str | None = None) -> Path:
    """Convert an image to another format (inferred from ``dst`` unless given)."""
    fmt = (fmt or dst.suffix.lstrip(".")).upper()
    if fmt in ("JPG",):
        fmt = "JPEG"
    with Image.open(src) as im:
        if fmt == "JPEG" and im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        im.save(dst, format=fmt)
    return dst


def make_thumbnail(src: Path, dst: Path, max_size: int = 256) -> Path:
    """Write a downscaled thumbnail; the original file is untouched."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_size, max_size))
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, format="JPEG", quality=85)
    return dst


def ext_for_content_type(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(ct, "png")
