"""
Design system: colour, type, and the generated stylesheet.

Nothing visual is written inline anywhere else in the app, so retuning the whole
interface is a single-file change.

House rules encoded here:
  * ember accent on a warm near-black ground
  * Space Grotesk for voice, DM Mono for anything machine-produced
  * zero border-radius throughout
  * no glyph icons -- every mark is drawn with QPainter (see widgets.py)

Real typefaces are optional. Drop .ttf or .otf files into assets/fonts/ and they
are registered at startup; otherwise the fallback stacks take over silently.
"""

from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from .paths import bundle_dir

# --------------------------------------------------------------------------- #
# Colour
# --------------------------------------------------------------------------- #

C = {
    # ground: warm near-black, lifted in four steps
    "ink":         "#0f0e0c",
    "surface":     "#161412",
    "raised":      "#1c1917",
    "hover":       "#242019",
    # line work
    "line":        "#2b2621",
    "line_soft":   "#201c18",
    # type
    "text":        "#f2efe9",
    "text_dim":    "#a39d92",
    "text_faint":  "#6d675e",
    # ember
    "accent":      "#e07b39",
    "accent_hi":   "#f0904e",
    "accent_low":  "#7d451f",
    "on_accent":   "#140d07",
    # state
    "ok":          "#7fae5f",
    "warn":        "#d9a441",
    "bad":         "#d6564a",
    "track":       "#241f1b",
}


def c(name: str) -> QColor:
    """Token name to QColor."""
    return QColor(C[name])


# --------------------------------------------------------------------------- #
# Type
# --------------------------------------------------------------------------- #

DISPLAY_STACK = ["Space Grotesk", "Inter", "Segoe UI Variable Display",
                 "Segoe UI", "SF Pro Display", "Helvetica Neue", "Arial"]
MONO_STACK = ["DM Mono", "JetBrains Mono", "Cascadia Mono", "SF Mono",
              "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"]

DISPLAY = "Arial"
MONO = "Courier New"

SIZE = {"xs": 10, "sm": 11, "body": 13, "md": 14, "lg": 16, "xl": 19, "xxl": 24}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}


def load_fonts() -> tuple[str, str]:
    """Register bundled faces, then resolve the best available display/mono pair."""
    global DISPLAY, MONO

    font_dir = bundle_dir() / "assets" / "fonts"
    if font_dir.is_dir():
        for path in sorted(font_dir.iterdir()):
            if path.suffix.lower() in {".ttf", ".otf"}:
                QFontDatabase.addApplicationFont(str(path))

    families = set(QFontDatabase.families())
    DISPLAY = next((n for n in DISPLAY_STACK if n in families), DISPLAY_STACK[-1])
    MONO = next((n for n in MONO_STACK if n in families), MONO_STACK[-1])
    return DISPLAY, MONO


def font(size: int = 13, *, weight: QFont.Weight | int = QFont.Normal,
         mono: bool = False, tracking: float = 0.0,
         caps: bool = False) -> QFont:
    f = QFont(MONO if mono else DISPLAY, size)
    # PySide6 6.11 rejects a bare int here, but CSS-style numeric weights are
    # the natural thing to write at call sites. Coerce rather than making every
    # caller import the enum.
    f.setWeight(weight if isinstance(weight, QFont.Weight) else QFont.Weight(int(weight)))
    if tracking:
        f.setLetterSpacing(QFont.PercentageSpacing, 100 + tracking)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    return f


def label_font() -> QFont:
    """Small, wide-tracked, uppercase. Used for section labels."""
    return font(SIZE["xs"], weight=QFont.Medium, mono=True, tracking=12, caps=True)


def apply_palette(app) -> None:
    """
    Set the QPalette as well as the stylesheet.

    The stylesheet covers widgets we style explicitly; the palette catches
    everything else -- native dialogs, tooltips, text cursors -- so a file
    picker does not open blinding white against the dark shell.
    """
    p = QPalette()
    p.setColor(QPalette.Window, c("ink"))
    p.setColor(QPalette.WindowText, c("text"))
    p.setColor(QPalette.Base, c("surface"))
    p.setColor(QPalette.AlternateBase, c("raised"))
    p.setColor(QPalette.Text, c("text"))
    p.setColor(QPalette.ToolTipBase, c("hover"))
    p.setColor(QPalette.ToolTipText, c("text"))
    p.setColor(QPalette.Button, c("raised"))
    p.setColor(QPalette.ButtonText, c("text"))
    p.setColor(QPalette.Highlight, c("accent"))
    p.setColor(QPalette.HighlightedText, c("on_accent"))
    p.setColor(QPalette.Link, c("accent"))
    p.setColor(QPalette.PlaceholderText, c("text_faint"))
    p.setColor(QPalette.Disabled, QPalette.Text, c("text_faint"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, c("text_faint"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, c("text_faint"))
    app.setPalette(p)


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #

_QSS = Template("""
QWidget {
    background: $ink;
    color: $text;
    font-family: "$display";
    font-size: ${body}px;
    border-radius: 0px;
}
QMainWindow, QDialog { background: $ink; }
QLabel { background: transparent; }

QLabel[role="title"]  { font-size: ${xl}px; font-weight: 600; }
QLabel[role="hint"]   { color: $text_faint; font-size: ${sm}px; }
QLabel[role="mono"]   { font-family: "$mono"; font-size: ${sm}px; color: $text_dim; }
QLabel[role="label"]  { font-family: "$mono"; font-size: ${xs}px;
                        color: $text_faint; letter-spacing: 1px; }
QLabel[state="ok"]    { color: $ok; }
QLabel[state="bad"]   { color: $bad; }
QLabel[state="warn"]  { color: $warn; }

/* ---- sidebar ---------------------------------------------------------- */
#Sidebar { background: $surface; border-right: 1px solid $line_soft; }
#Sidebar QPushButton {
    background: transparent; border: none;
    border-left: 2px solid transparent;
    color: $text_dim; text-align: left;
    padding: 10px 16px; font-size: ${body}px;
}
#Sidebar QPushButton:hover   { background: $raised; color: $text; }
#Sidebar QPushButton:checked {
    background: $raised; color: $text;
    border-left: 2px solid $accent; font-weight: 600;
}
#Wordmark    { font-size: ${lg}px; font-weight: 600; letter-spacing: 0.5px; }
#WordmarkSub { font-family: "$mono"; font-size: 9px; color: $text_faint;
               letter-spacing: 2px; }

/* ---- inputs ----------------------------------------------------------- */
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: $surface; border: 1px solid $line;
    padding: 8px 10px;
    selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: $text_faint; background: $surface;
}
QLineEdit#UrlBar { font-size: ${md}px; padding: 11px 13px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView {
    background: $raised; border: 1px solid $line; outline: none;
    selection-background-color: $accent; selection-color: $on_accent;
}
QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }

/* ---- buttons ---------------------------------------------------------- */
QPushButton {
    background: $raised; border: 1px solid $line;
    color: $text; padding: 8px 15px;
}
QPushButton:hover    { background: $hover; border-color: $text_faint; }
QPushButton:pressed  { background: $surface; }
QPushButton:disabled { color: $text_faint; background: $surface;
                       border-color: $line_soft; }

QPushButton[variant="primary"] {
    background: $accent; color: $on_accent;
    border: 1px solid $accent; font-weight: 600;
}
QPushButton[variant="primary"]:hover    { background: $accent_hi; border-color: $accent_hi; }
QPushButton[variant="primary"]:pressed  { background: $accent_low; }
QPushButton[variant="primary"]:disabled { background: $accent_low;
                                          border-color: $accent_low; color: $text_faint; }
QPushButton[variant="ghost"]       { background: transparent; border: 1px solid $line; }
QPushButton[variant="ghost"]:hover { background: $raised; }
QPushButton[variant="danger"]:hover { border-color: $bad; color: $bad; }

/* ---- checkbox --------------------------------------------------------- */
QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid $line; background: $surface;
}
QCheckBox::indicator:hover    { border-color: $text_faint; }
QCheckBox::indicator:checked  { background: $accent; border-color: $accent; }
QCheckBox:disabled            { color: $text_faint; }

/* ---- queue ------------------------------------------------------------ */
QListWidget {
    background: $ink; border: 1px solid $line_soft; outline: none;
    padding: 0px;
}
QListWidget::item { border: none; }
QListWidget::item:selected { background: transparent; }

/* ---- containers ------------------------------------------------------- */
#Panel  { background: $surface; border-left: 1px solid $line_soft; }
#Card   { background: $surface; border: 1px solid $line_soft; }
#Header { background: $surface; border-bottom: 1px solid $line_soft; }
#Rule   { background: $line_soft; max-height: 1px; min-height: 1px; border: none; }

/* ---- scrollbars ------------------------------------------------------- */
QScrollBar:vertical   { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $hover; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $text_faint; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: $hover; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $text_faint; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---- text areas ------------------------------------------------------- */
QTextEdit {
    font-family: "$mono"; font-size: ${sm}px;
    color: $text_dim; background: $surface; padding: 11px;
}

/* ---- chrome ----------------------------------------------------------- */
QMenuBar { background: $surface; border-bottom: 1px solid $line_soft; padding: 2px; }
QMenuBar::item { padding: 6px 12px; background: transparent; }
QMenuBar::item:selected { background: $hover; }
QMenu { background: $raised; border: 1px solid $line; padding: 4px; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected { background: $accent; color: $on_accent; }
QMenu::separator { height: 1px; background: $line_soft; margin: 4px 8px; }

QStatusBar { background: $surface; border-top: 1px solid $line_soft;
             color: $text_dim; font-size: ${sm}px; }
QStatusBar::item { border: none; }

QToolTip { background: $hover; color: $text; border: 1px solid $line;
           padding: 6px 9px; font-size: ${sm}px; }

QSplitter::handle { background: $line_soft; }
QSplitter::handle:horizontal { width: 1px; }
QProgressBar { background: $track; border: none; height: 2px; text-align: center; }
QProgressBar::chunk { background: $accent; }
""")


def stylesheet() -> str:
    values = dict(C)
    values["display"] = DISPLAY
    values["mono"] = MONO
    values.update({k: str(v) for k, v in SIZE.items()})
    return _QSS.substitute(values)
