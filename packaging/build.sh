#!/usr/bin/env bash
# Build a standalone Ambaar for macOS or Linux.
#
#   ./packaging/build.sh
#
# Output lands in dist/. Run from the repository root.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "No .venv found. Create one on Python 3.9+ first:"
  echo "    python3 -m venv .venv && source .venv/bin/activate"
  exit 1
fi
source .venv/bin/activate

PYV=$(python -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo "Python $PYV"
python - <<'PY'
import sys
if sys.version_info[:2] < (3, 9):
    sys.exit("Python 3.9+ required; yt-dlp will not install correctly below that.")
PY

echo "Installing build dependencies"
pip install -q -U -r requirements.txt
pip install -q -U pyinstaller pillow
echo "PyInstaller $(python -c 'import PyInstaller;print(PyInstaller.__version__)')  /  Qt $(python -c 'from PySide6 import QtCore;print(QtCore.qVersion())')"

echo "Generating icons"
python packaging/make_icons.py

echo "Building"
rm -rf build dist
pyinstaller packaging/ambaar.spec --noconfirm --clean

echo
echo "Built:"
ls -la dist/
echo
echo "Package it for release:"
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "    cd dist && zip -r ambaar-macos.zip 'Ambaar.app'"
else
  echo "    cd dist && tar czf ambaar-linux.tar.gz ambaar"
fi
