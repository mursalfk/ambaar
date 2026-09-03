"""Entry point for `python -m ambaar`."""

import sys

from .bootstrap import prepare_engine_path

prepare_engine_path()

from .app import main  # noqa: E402  -- must follow prepare_engine_path()

if __name__ == "__main__":
    sys.exit(main())
