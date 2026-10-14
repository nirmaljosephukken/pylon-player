"""Colors and the global Qt stylesheet.

Design language from the redesign: orange cone accent, neutral grays and
black, rectangular shapes that are only slightly rounded.
"""

DEFAULT_ACCENT = "#FF8800"

BG = "#0E0E0E"          # window / video surround
PANEL = "#171717"       # sidebars
SURFACE = "#212121"     # inputs, cards
SURFACE_HI = "#2A2A2A"  # hover
BORDER = "#2F2F2F"
TEXT = "#EDEDED"
MUTED = "#9B9B9B"
FAINT = "#5E5E5E"
RADIUS = 4              # "rectangular but a little less sharp"

_accent = DEFAULT_ACCENT

# Background themes. Text and icons stay light on every theme, so they are always readable.
THEMES = {
    "dark":     {"name": "Dark",          "BG": "#0E0E0E", "PANEL": "#171717", "SURFACE": "#212121", "SURFACE_HI": "#2A2A2A", "BORDER": "#2F2F2F"},
    "black":    {"name": "Pitch black",   "BG": "#000000", "PANEL": "#0A0A0A", "SURFACE": "#151515", "SURFACE_HI": "#1E1E1E", "BORDER": "#262626"},
    "warm":     {"name": "Warm grey",     "BG": "#13110F", "PANEL": "#1C1916", "SURFACE": "#26221E", "SURFACE_HI": "#302B26", "BORDER": "#3A332C"},
    "midnight": {"name": "Midnight blue", "BG": "#0A0E16", "PANEL": "#101725", "SURFACE": "#182133", "SURFACE_HI": "#202B40", "BORDER": "#29354B"},
    # Neon themes: their own accent colours (a gradient plus a second accent) and a soft glow.
    # The video area stays black; only the controls, panels and highlights light up.
    "neon":      {"name": "Neon", "BG": "#000000", "PANEL": "#06060A", "SURFACE": "#101018", "SURFACE_HI": "#181826",
                  "BORDER": "#26263C", "vibe": {"stops": ["#00F0FF", "#FF2BD6"], "accent2": "#FF2BD6", "glow": True}},
    "sunset":    {"name": "Sunset", "BG": "#0E070F", "PANEL": "#170A17", "SURFACE": "#26101F", "SURFACE_HI": "#331628",
                  "BORDER": "#45203A", "panel_grad": ("#24102A", "#10070E"),
                  "vibe": {"stops": ["#FF9A1F", "#FF3D7F", "#A24DFF"], "accent2": "#FF3D7F", "glow": True}},
    "aurora":    {"name": "Aurora", "BG": "#040C0D", "PANEL": "#071214", "SURFACE": "#0E2125", "SURFACE_HI": "#132C30",
                  "BORDER": "#1B3B3F", "panel_grad": ("#0A1E21", "#060C12"),
                  "vibe": {"stops": ["#3DFFA0", "#22D3EE", "#A06BFF"], "accent2": "#22D3EE", "glow": True}},
    "synthwave": {"name": "Synthwave", "BG": "#0A0720", "PANEL": "#120C2E", "SURFACE": "#1D1545", "SURFACE_HI": "#271C57",
                  "BORDER": "#352868", "panel_grad": ("#1C1040", "#0C0822"),
                  "vibe": {"stops": ["#FF2E97", "#B84DFF", "#4D7CFF"], "accent2": "#2DE2E6", "glow": True}},
}
_theme = "dark"
_vibe = None          # the neon theme's colours while one is active
_panel_grad = None    # (top, bottom) for a gently graded side panel


def tint_palette(color: str) -> dict:
    """Dark shades of any colour, kept dark enough that light text stays readable."""
    from PySide6.QtGui import QColor
    c = QColor(color)
    if not c.isValid():
        return dict(THEMES["dark"])
    h = max(0, c.hslHueF())
    s = min(0.45, c.hslSaturationF())
    shade = lambda l: QColor.fromHslF(h, s, l).name().upper()
    return {"name": "Custom", "BG": shade(0.05), "PANEL": shade(0.08), "SURFACE": shade(0.12),
            "SURFACE_HI": shade(0.155), "BORDER": shade(0.19)}


def set_theme(name: str, tint: str = ""):
    """Switch the background palette ("dark", "black", "warm", "midnight" or "custom" with a tint colour)."""
    global BG, PANEL, SURFACE, SURFACE_HI, BORDER, _theme, _vibe, _panel_grad
    pal = tint_palette(tint) if name == "custom" and tint else THEMES.get(name, THEMES["dark"])
    _theme = name if (name in THEMES or (name == "custom" and tint)) else "dark"
    BG, PANEL, SURFACE, SURFACE_HI, BORDER = pal["BG"], pal["PANEL"], pal["SURFACE"], pal["SURFACE_HI"], pal["BORDER"]
    _vibe = pal.get("vibe")
    _panel_grad = pal.get("panel_grad")


def rgb(hex_color: str):
    c = hex_color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def accent() -> str:
    """Main highlight colour: the user's accent, or the neon theme's first colour."""
    return _vibe["stops"][0] if _vibe else _accent


def user_accent() -> str:
    return _accent


def accent2() -> str:
    """Second highlight colour (selected tabs, chips, list items) for mix-and-match neon themes."""
    return _vibe.get("accent2", accent()) if _vibe else _accent


def stops() -> list:
    return list(_vibe["stops"]) if _vibe else [_accent]


def glow() -> bool:
    return bool(_vibe and _vibe.get("glow"))


def is_vibe(name: str) -> bool:
    return "vibe" in THEMES.get(name, {})


def brush(x0: float, x1: float):
    """A QBrush/QColor for accent fills: a horizontal gradient on neon themes, else the flat accent."""
    from PySide6.QtGui import QColor, QLinearGradient
    st = stops()
    if len(st) == 1:
        return QColor(st[0])
    g = QLinearGradient(x0, 0, max(x0 + 1, x1), 0)
    for i, c in enumerate(st):
        g.setColorAt(i / (len(st) - 1), QColor(c))
    return g


def css_gradient(vertical=False) -> str:
    st = stops()
    if len(st) == 1:
        return st[0]
    end = "x2:0, y2:1" if vertical else "x2:1, y2:0"
    parts = ", ".join(f"stop:{i / (len(st) - 1):.2f} {c}" for i, c in enumerate(st))
    return f"qlineargradient(x1:0, y1:0, {end}, {parts})"


def on_accent() -> str:
    """Dark or white, whichever reads better on the accent colour."""
    c = _accent.lstrip("#")
    try:
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#111111"
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"


def set_accent(color: str) -> None:
    global _accent
    _accent = color or DEFAULT_ACCENT


def stylesheet() -> str:
    a = accent()
    a2 = accent2()
    ag = css_gradient()
    panel = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_panel_grad[0]}, stop:1 {_panel_grad[1]})"
             if _panel_grad else PANEL)
    return f"""
    * {{ font-family: "Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
    QMainWindow, QDialog {{ background: {BG}; }}
    QWidget#Panel {{ background: {panel}; }}
    QWidget#Home, QWidget#NowPlaying {{ background: {BG}; }}
    QLabel#H1 {{ font-size: 22px; font-weight: 600; }}
    QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
    QLabel#Section {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; padding-top: 6px; }}
    QLabel#Muted {{ color: {MUTED}; }}
    QLabel#Value {{ color: {a}; font-weight: 600; }}

    QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}

    QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 6px 12px; }}
    QPushButton:hover {{ background: {SURFACE_HI}; }}
    QPushButton:pressed {{ background: {BORDER}; }}
    QPushButton:checked {{ border-color: {a2}; color: {a2}; }}
    QPushButton#Primary {{ background: {ag}; border-color: {a}; color: #111; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {ag}; }}
    QPushButton#Chip {{ background: transparent; border: 1px solid {BORDER}; padding: 3px 10px; color: {TEXT}; }}
    QPushButton#Chip:hover {{ border-color: {a}; color: {a}; }}
    QPushButton#ResumeChip {{ background: {ag}; color: #111; border: none; font-weight: 600; padding: 4px 12px; }}

    QToolButton {{ background: transparent; border: none; border-radius: {RADIUS}px; padding: 4px; }}
    QToolButton:hover {{ background: rgba(255,255,255,0.08); }}
    QToolButton:checked {{ background: rgba(255,255,255,0.10); }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QListWidget#InsetList {{ background: {BG}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 4px; }}
    QToolButton#PlayButton {{ background: {ag}; border-radius: 9px; padding: 0; }}
    QToolButton#PlayButton:hover {{ background: {ag}; border: 2px solid rgba(255,255,255,0.35); }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 5px 8px; selection-background-color: {a}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {a}; }}
    QTextBrowser, QTextEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 8px; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_HI}; selection-color: {a}; outline: 0; }}

    QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_HI}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ag}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; margin: -5px 0; border-radius: 2px; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {FAINT}; border-radius: 3px; background: {SURFACE}; }}
    QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {FAINT}; border-radius: 7px; background: {SURFACE}; }}
    QRadioButton::indicator:checked {{ background: {a}; border-color: {a}; }}

    QListWidget, QTreeWidget, QTableWidget {{ background: transparent; border: none; outline: 0; }}
    QListWidget::item, QTreeWidget::item {{ padding: 6px 6px; border-radius: {RADIUS}px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {SURFACE}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {SURFACE_HI}; color: {a2}; }}
    QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}
    QTableWidget {{ gridline-color: {BORDER}; }}

    QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 6px; border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {a2}; }}
    QTabBar::tab:hover {{ color: {TEXT}; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 3px; min-width: 30px; }}

    QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 3px; }}
    QMenu::item:selected {{ background: {SURFACE_HI}; color: {a}; }}
    QMenu::item:disabled {{ color: {FAINT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
    QMenu::section {{ color: {MUTED}; padding: 6px 12px 2px 12px; font-size: 11px; font-weight: 600; }}
    QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
    QMenu::indicator:checked {{ background: {a}; border-radius: 3px; }}

    QSplitter::handle {{ background: {BORDER}; }}
    QFrame#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS + 2}px; }}
    QFrame#Card:hover {{ border-color: {a}; }}
    QToolButton#CardCorner {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 15px; padding: 0; }}
    QToolButton#CardCorner:hover {{ border-color: {a}; background: {PANEL}; }}
    """
