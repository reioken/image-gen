"""Midjourney: intentionally NOT implemented.

As of the current research there is no official public Midjourney API. Midjourney
supports image prompts inside its own product, but automating it requires
unofficial third-party bridges (Apiframe / PiAPI / TTAPI, etc.) that carry ToS
and reliability risk. This module documents that decision; it is not registered
as a usable provider.

If you accept the risk, write a third-party adapter that subclasses BaseProvider
and register it in ``registry.py`` yourself. This project ships it disabled.
"""

from __future__ import annotations

NOTE = (
    "Midjourney has no official public API. This tool leaves it disabled to "
    "avoid fragile, ToS-risky third-party automation. Use a provider with a "
    "documented reference-image API instead (OpenAI, Google, BFL, fal, "
    "Replicate, Stability, Ideogram, Recraft, Leonardo)."
)
