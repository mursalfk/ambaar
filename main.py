#!/usr/bin/env python3
"""
Launcher.

    python main.py

The engine path is prepared before anything imports yt_dlp -- see
ambaar/bootstrap.py for why that ordering matters in packaged builds.
"""

import sys

from ambaar.bootstrap import prepare_engine_path

prepare_engine_path()

from ambaar.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
