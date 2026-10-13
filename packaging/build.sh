#!/usr/bin/env bash
# packaging/build.sh
#
# Build a standalone Ambaar for macOS or Linux.
#
#   ./packaging/build.sh
#
# Output lands in dist/. Run from anywhere; the script locates the repo itself.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "No .venv found. Create one on Python 3.9+ first:"
  echo "    python3 -m venv .venv && source .venv/bin/activate"
  exit 1
fi
source .venv/bin/activate

# Call the interpreter by absolute path and reach every tool through "-m".
#
# Console scripts (pip, pyinstaller) embed the absolute path of the interpreter
# that created them. Move or rename the project folder and every shim keeps
# pointing at the old location while python itself still works -- so the failure
# reads as a missing package rather than a moved venv. Going through "-m"
# sidesteps the shims entirely.
PY="$PWD/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "No interpreter at $PY -- the venv is incomplete. Recreate it:"
  echo "    rm -rf .venv && python3 -m venv .venv"
  exit 1
fi

echo "Python $("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')  ($PY)"
"$PY" - <<'PY'
import sys
if sys.version_info[:2] < (3, 9):
    sys.exit("Python 3.9+ required. Below that pip installs an obsolete yt-dlp "
             "instead of refusing.")
PY

if [[ -n "${CONDA_DEFAULT_ENV:-}" ]]; then
  echo "Warning: conda environment '$CONDA_DEFAULT_ENV' is active."
  echo "         Run 'conda deactivate' first, or PyInstaller may bundle conda's Qt."
fi

if pgrep -x ambaar >/dev/null 2>&1; then
  echo "ambaar is running. Stopping it so the build can clear dist/."
  pkill -x ambaar || true
  sleep 2
fi

echo "Installing build dependencies"
# No -U here: requirements.txt pins a floor, not a ceiling, and "-U" would
# silently upgrade Qt on every build.
"$PY" -m pip install -q -r requirements.txt
"$PY" -m pip install -q -U pyinstaller pillow
echo "PyInstaller $("$PY" -c 'import PyInstaller;print(PyInstaller.__version__)')  /  Qt $("$PY" -c 'from PySide6 import QtCore;print(QtCore.qVersion())')"

echo "Generating icons"
"$PY" packaging/make_icons.py

echo "Building"
rm -rf build dist
"$PY" -m PyInstaller packaging/ambaar.spec --noconfirm --clean

echo
echo "Built:"
ls -la dist/
echo
echo "Launch it before shipping -- a build that compiles is not evidence that it runs."
echo
echo "Package it for release:"
if [[ "$OSTYPE" == "darwin"* ]]; then
  # -y preserves the symlinks inside the .app bundle; without it macOS refuses
  # to launch the extracted copy.
  echo "    cd dist && zip -r -y ambaar-macos.zip 'Ambaar.app'"
else
  echo "    cd dist && tar czf ambaar-linux.tar.gz ambaar"
fi