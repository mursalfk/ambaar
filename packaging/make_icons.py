#!/usr/bin/env python3
"""
Generate application icons.

The mark is drawn, not imported: an ember downward arrow meeting a baseline,
inside a near-black square. Same language as the in-app marks, and it means the
repository carries no binary art that can drift from the design.

    python packaging/make_icons.py

Writes assets/icons/generated/: PNGs at every size the platforms want, a
Windows .ico, and a macOS .icns when iconutil is available.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icons" / "generated"

INK = "#0f0e0c"
EMBER = "#e07b39"
SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]


def draw(size: int, path: Path) -> None:
    """Render the Ambaar mark at one size. Geometry comes from make_logo."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    from make_logo import svg_mark

    if QGuiApplication.instance() is None:
        QGuiApplication(["icons"])

    renderer = QSvgRenderer(QByteArray(svg_mark(512, background=True).encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(QColor(INK))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    pm.save(str(path))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    for size in SIZES:
        draw(size, OUT / f"icon_{size}.png")
    print(f"wrote {len(SIZES)} PNGs to {OUT}")

    # Windows .ico
    try:
        from PIL import Image
        frames = [Image.open(OUT / f"icon_{n}.png") for n in (16, 24, 32, 48, 64, 128, 256)]
        frames[0].save(OUT / "icon.ico", format="ICO",
                       sizes=[(f.width, f.height) for f in frames])
        print("wrote icon.ico")
    except ImportError:
        print("Pillow not installed; skipping .ico  (pip install pillow)")

    # macOS .icns
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        pairs = [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
                 (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
                 (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x")]
        for size, name in pairs:
            shutil.copy(OUT / f"icon_{size}.png", iconset / f"icon_{name}.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset),
                        "-o", str(OUT / "icon.icns")], check=False)
        print("wrote icon.icns")
    else:
        print("not macOS or iconutil missing; skipping .icns")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
