"""Logging setup that works both from the CLI and the packaged GUI (.exe).

The GUI is built with ``console=False`` so there is no console to print to; we
always also write to a rotating file under the per-user app data directory so
failures remain diagnosable.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def app_data_dir() -> Path:
    """Per-user writable directory for settings, .env and logs.

    Windows: ``%APPDATA%\\ProductImageBatch``
    macOS:   ``~/Library/Application Support/ProductImageBatch``
    Linux:   ``$XDG_CONFIG_HOME/ProductImageBatch`` or ``~/.product_image_batch``
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ProductImageBatch"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ProductImageBatch"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ProductImageBatch"
    return Path.home() / ".product_image_batch"


def setup_logging(verbose: bool = False, to_file: bool = True) -> logging.Logger:
    """Configure the root package logger once and return it."""
    global _CONFIGURED
    logger = logging.getLogger("product_image_batch")
    if _CONFIGURED:
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    if to_file:
        try:
            log_dir = app_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fileh = RotatingFileHandler(
                log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            fileh.setFormatter(fmt)
            logger.addHandler(fileh)
        except OSError:
            # Read-only filesystem etc. — the stream handler still works.
            pass

    _CONFIGURED = True
    return logger


def get_logger(name: str = "product_image_batch") -> logging.Logger:
    return logging.getLogger(name)
