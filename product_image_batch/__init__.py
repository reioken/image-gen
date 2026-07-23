"""product_image_batch — parallel product-image generation from reference images.

The package is split into three layers with a strict dependency direction:

* ``core/``  — the engine (async, provider adapters, scheduler, models).
               It contains **no GUI imports** and can be used entirely headless.
* ``cli.py`` — an optional command-line front-end over the engine.
* ``gui/``   — a PySide6 desktop front-end over the engine.

The GUI and CLI are thin clients; all real work lives in ``core``.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
