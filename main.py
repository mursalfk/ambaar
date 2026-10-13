#!/usr/bin/env python3
# main.py
"""
Launcher.

    python main.py

Two things happen before the GUI is imported, and the order matters.

First, the probe flag is intercepted. In a frozen build the updater cannot run
"python -c" to verify an engine, because sys.executable is ambaar.exe -- so it
relaunches itself with this flag instead. If that were handled after the GUI
import, the probe child would build a window before doing its job.

Second, the engine path is prepared, so a managed yt-dlp sits ahead of the
bundled one on sys.path. See ambaar/bootstrap.py for why that ordering matters.
"""

import sys

from ambaar.bootstrap import prepare_engine_path

prepare_engine_path()

# Probe mode: run the check and exit without ever touching Qt. Must precede the
# app import, or every verification would spawn a second visible window.
if "--ambaar-probe" in sys.argv:
    from ambaar.updater import run_probe_child

    _i = sys.argv.index("--ambaar-probe")
    _url = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else ""
    raise SystemExit(run_probe_child(_url))

from ambaar.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())