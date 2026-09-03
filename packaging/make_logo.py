#!/usr/bin/env python3
"""
Generate the Ambaar logo set.

Nothing here is imported art. The mark is drawn from primitives, which means the
logo can never drift from the design language and there is no binary asset in
version control that someone has to open Illustrator to change.

The mark: three stacked bars of increasing width -- the anbaar, the heap -- with
an ember arrow descending into them. Read one way it is a stack growing; read
the other it is a download landing. Zero radius, square caps, no glyphs.

    python packaging/make_logo.py

Writes to assets/brand/: SVG (the source of truth) plus PNG renders of the mark,
the horizontal lockup, and a social banner.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"

INK = "#0f0e0c"
EMBER = "#e07b39"
BONE = "#f2efe9"
DIM = "#6d675e"


# --------------------------------------------------------------------------- #
# SVG construction
# --------------------------------------------------------------------------- #

def mark_paths(s: float = 100.0, ember: str = EMBER, bone: str = BONE) -> str:
    """
    The mark alone, on a 100x100 grid.

    Bars widen downward so the silhouette reads as accumulation rather than a
    plain download tray. The arrow stops short of the top bar; the gap is what
    keeps it from looking like a single glued shape at 16px.
    """
    w = s / 100.0
    stroke = 9 * w
    return f"""
  <g stroke-linecap="square" stroke-linejoin="miter" fill="none">
    <!-- descending arrow -->
    <path d="M{50*w} {14*w} L{50*w} {45*w}" stroke="{ember}" stroke-width="{stroke}"/>
    <path d="M{33*w} {32*w} L{50*w} {50*w} L{67*w} {32*w}"
          stroke="{ember}" stroke-width="{stroke}"/>
    <!-- the heap: three bars, widening -->
    <path d="M{38*w} {66*w} L{62*w} {66*w}" stroke="{bone}" stroke-width="{stroke}"/>
    <path d="M{30*w} {80*w} L{70*w} {80*w}" stroke="{bone}" stroke-width="{stroke}"/>
    <path d="M{22*w} {94*w} L{78*w} {94*w}" stroke="{ember}" stroke-width="{stroke}"/>
  </g>"""


def svg_mark(size: int = 512, background: bool = True) -> str:
    bg = f'<rect width="{size}" height="{size}" fill="{INK}"/>' if background else ""
    inner = size * 0.68
    off = (size - inner) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"
     viewBox="0 0 {size} {size}">
  {bg}
  <g transform="translate({off},{off * 0.82})">{mark_paths(inner)}
  </g>
</svg>"""


def svg_lockup(width: int = 1200, dark: bool = True) -> str:
    """Horizontal lockup: mark, then wordmark and descriptor."""
    h = width * 0.28
    ink = INK if dark else BONE
    text = BONE if dark else INK
    dim = DIM if dark else "#8a8377"
    bone = BONE if dark else INK

    mark_size = h * 0.56
    mx, my = h * 0.30, (h - mark_size) / 2
    tx = mx + mark_size + h * 0.26

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h:.0f}"
     viewBox="0 0 {width} {h:.0f}">
  <rect width="{width}" height="{h:.0f}" fill="{ink}"/>
  <g transform="translate({mx:.1f},{my:.1f})">{mark_paths(mark_size, EMBER, bone)}
  </g>
  <text x="{tx:.1f}" y="{h * 0.50:.1f}"
        font-family="Space Grotesk, Inter, Segoe UI, Helvetica, sans-serif"
        font-size="{h * 0.30:.1f}" font-weight="600" fill="{text}"
        dominant-baseline="middle" letter-spacing="{h * 0.004:.2f}">Ambaar</text>
  <text x="{tx:.1f}" y="{h * 0.72:.1f}"
        font-family="DM Mono, JetBrains Mono, Consolas, monospace"
        font-size="{h * 0.105:.1f}" fill="{dim}"
        dominant-baseline="middle" letter-spacing="{h * 0.026:.2f}">DOWNLOAD MANAGER</text>
</svg>"""


def svg_banner(width: int = 1280, height: int = 640) -> str:
    """Repository / website banner."""
    mark_size = height * 0.30
    mx = (width - mark_size) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="{INK}"/>
  <g transform="translate({mx:.1f},{height * 0.24:.1f})">{mark_paths(mark_size)}
  </g>
  <text x="{width/2}" y="{height * 0.66:.0f}" text-anchor="middle"
        font-family="Space Grotesk, Inter, Segoe UI, Helvetica, sans-serif"
        font-size="{height * 0.115:.0f}" font-weight="600" fill="{BONE}">Ambaar</text>
  <text x="{width/2}" y="{height * 0.755:.0f}" text-anchor="middle"
        font-family="DM Mono, JetBrains Mono, Consolas, monospace"
        font-size="{height * 0.034:.0f}" fill="{DIM}"
        letter-spacing="{height * 0.009:.1f}">THE ENGINE VERIFIES ITSELF</text>
  <rect x="{width/2 - 30}" y="{height * 0.84:.0f}" width="60" height="3" fill="{EMBER}"/>
</svg>"""


# --------------------------------------------------------------------------- #

def rasterise(svg: str, path: Path, width: int, height: int) -> bool:
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return False

    if QGuiApplication.instance() is None:
        QGuiApplication(["logo"])

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(width, height)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    pm.save(str(path))
    return True


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    files = {
        "mark.svg": svg_mark(512, background=True),
        "mark-transparent.svg": svg_mark(512, background=False),
        "lockup-dark.svg": svg_lockup(1200, dark=True),
        "lockup-light.svg": svg_lockup(1200, dark=False),
        "banner.svg": svg_banner(),
    }
    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    print(f"wrote {len(files)} SVGs to {OUT}")

    renders = [
        ("mark.svg", "mark-512.png", 512, 512),
        ("mark.svg", "mark-256.png", 256, 256),
        ("mark-transparent.svg", "mark-transparent-512.png", 512, 512),
        ("lockup-dark.svg", "lockup-dark.png", 1200, 336),
        ("lockup-light.svg", "lockup-light.png", 1200, 336),
        ("banner.svg", "banner.png", 1280, 640),
    ]
    ok = 0
    for src, dst, w, h in renders:
        if rasterise((OUT / src).read_text(encoding="utf-8"), OUT / dst, w, h):
            ok += 1
    print(f"rendered {ok} PNGs" if ok else "PySide6 missing; SVGs only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
