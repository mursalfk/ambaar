# tests/conftest.py
"""
Point the app's data directory at a throwaway folder before anything imports it.

Several modules compute paths at import time (the queue database, the thumbnail
cache), so this must run before the first `import ambaar`. Without it a test
that builds the main window would open the developer's real queue and history.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_home = tempfile.mkdtemp(prefix="ambaar-tests-")
os.environ["AMBAAR_HOME"] = _home
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
atexit.register(shutil.rmtree, _home, ignore_errors=True)
