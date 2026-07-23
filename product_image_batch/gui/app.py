"""Desktop app entry point.

Run from source::

    python -m product_image_batch.gui.app

Or via the packaged .exe (see build/ and README). On first launch it ensures a
per-user ``.env`` and ``settings.json`` exist under the app-data dir so the user
can enter API keys through the settings dialog — no command line required.
"""

from __future__ import annotations

import sys


def _bootstrap_user_files() -> None:
    """Create per-user .env / settings.json from templates and load the .env."""
    from ..core.config import ensure_user_env, ensure_user_settings
    from ..core.utils.logging import setup_logging

    setup_logging(verbose=False, to_file=True)
    env_path = ensure_user_env()
    ensure_user_settings()
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _bootstrap_user_files()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PySide6 is not installed. Install it with:\n"
            "    pip install PySide6\n"
            "or install the GUI extras:  pip install .[gui]\n"
        )
        return 1

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Product Image Batch")
    app.setOrganizationName("ProductImageBatch")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
