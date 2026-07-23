"""Enable ``python -m product_image_batch`` to run the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
