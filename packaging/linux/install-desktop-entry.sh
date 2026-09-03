#!/usr/bin/env bash
# Register Ambaar with the desktop environment so it appears in the launcher
# with the right icon. Run after extracting the Linux build.
#
#   ./install-desktop-entry.sh /path/to/ambaar
set -euo pipefail

BIN="${1:-$(pwd)/ambaar}"
if [[ ! -x "$BIN" ]]; then
  echo "Executable not found: $BIN"
  echo "Usage: $0 /path/to/ambaar"
  exit 1
fi

APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor"
mkdir -p "$APPS"

HERE="$(cd "$(dirname "$0")" && pwd)"
for size in 16 24 32 48 64 128 256 512; do
  src="$HERE/../../assets/icons/generated/icon_${size}.png"
  if [[ -f "$src" ]]; then
    mkdir -p "$ICONS/${size}x${size}/apps"
    cp "$src" "$ICONS/${size}x${size}/apps/ambaar.png"
  fi
done

sed "s|^Exec=.*|Exec=$BIN %U|" "$HERE/ambaar.desktop" > "$APPS/ambaar.desktop"
chmod +x "$APPS/ambaar.desktop"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache  >/dev/null && gtk-update-icon-cache -f -t "$ICONS" || true

echo "Installed. Ambaar should now appear in your application launcher."
