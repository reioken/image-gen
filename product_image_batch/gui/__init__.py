"""PySide6 desktop front-end for product-image-batch.

The GUI is a thin client over ``core``: it drives a single shared
:class:`~product_image_batch.core.scheduler.GlobalScheduler` running on a
background asyncio event loop, and marshals results back to the Qt UI thread via
signals. See ``async_bridge.py`` for the threading model.
"""
