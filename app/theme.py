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


def accent() -> str:
    return _accent


def set_accent(color: str) -> None:
    global _accent
    _accent = color or DEFAULT_ACCENT


def stylesheet() -> str:
    a = _accent
    return f"""
    * {{ font-family: "Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
    QMainWindow, QDialog {{ background: {BG}; }}
    QWidget#Panel {{ background: {PANEL}; }}
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
    QPushButton:checked {{ border-color: {a}; color: {a}; }}
    QPushButton#Primary {{ background: {a}; border-color: {a}; color: #111; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {a}; }}
    QPushButton#Chip {{ background: transparent; border: 1px solid {BORDER}; padding: 3px 10px; color: {TEXT}; }}
    QPushButton#Chip:hover {{ border-color: {a}; color: {a}; }}
    QPushButton#ResumeChip {{ background: {a}; color: #111; border: none; font-weight: 600; padding: 4px 12px; }}

    QToolButton {{ background: transparent; border: none; border-radius: {RADIUS}px; padding: 4px; }}
    QToolButton:hover {{ background: rgba(255,255,255,0.08); }}
    QToolButton:checked {{ background: rgba(255,255,255,0.10); }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 5px 8px; selection-background-color: {a}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {a}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_HI}; selection-color: {a}; outline: 0; }}

    QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_HI}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; margin: -5px 0; border-radius: 2px; }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {FAINT}; border-radius: 3px; background: {SURFACE}; }}
    QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {FAINT}; border-radius: 7px; background: {SURFACE}; }}
    QRadioButton::indicator:checked {{ background: {a}; border-color: {a}; }}

    QListWidget, QTreeWidget, QTableWidget {{ background: transparent; border: none; outline: 0; }}
    QListWidget::item, QTreeWidget::item {{ padding: 6px 6px; border-radius: {RADIUS}px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {SURFACE}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {SURFACE_HI}; color: {a}; }}
    QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}
    QTableWidget {{ gridline-color: {BORDER}; }}

    QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 6px; border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {a}; }}
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
    """
