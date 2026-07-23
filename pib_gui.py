"""Top-level launcher for the desktop GUI (PyInstaller entry point).

Kept OUTSIDE the ``product_image_batch`` package on purpose: when PyInstaller
freezes the app it runs this file as the top-level ``__main__`` script. Because
it is not inside the package, it uses a normal absolute import and there is no
"relative import with no known parent package" problem.

You can also run it directly from source:  ``python pib_gui.py``
"""

from product_image_batch.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
