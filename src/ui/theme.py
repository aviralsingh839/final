"""Centralized CHRONO-PCOS V8.2 theme system.

V8.2 design principle: "Simple outside, sophisticated inside."

The application ships two themes:

  LIGHT (default)  — clean clinical look: white/light surfaces, dark readable
                     text, restrained borders and a small accent family.
  DARK  (optional) — calm low-light variant of the same token set.

Everything is token based.  Widgets never hardcode hex values; they either

  * rely on the application stylesheet (built from the active token set by
    :func:`build_qss` and applied with :func:`apply_theme`), or
  * query the active tokens at paint time via :func:`color` / :func:`qcolor`
    so custom-painted widgets (gauges, radar, clock, fingerprint…) follow
    theme switches automatically.

Semantic status colors (GREEN/YELLOW/ORANGE/RED/ACCENT…) are deliberately
theme-neutral mid-tones chosen to stay readable on both white and dark
surfaces, because many modules bake them into small inline stylesheets at
construction time.

Font stack (Segoe UI → Inter → Helvetica Neue → Arial) renders well on
Windows, Linux and macOS.
"""
from __future__ import annotations

import weakref
from typing import Callable, Dict, List

from PySide6.QtGui import QColor, QFont

# Qt stylesheet font-family stack.
FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", "Helvetica", "Arial", sans-serif'
# QFont() family for custom-painted widgets (gauges, clocks, radars, twin flow).
PAINTER_FONT = "Segoe UI"

# ------------------------------------------------------------------ tokens --
# Theme-neutral semantic colors.  Chosen so bold status text/badges remain
# legible on both the light (default) and dark surfaces.
GREEN = "#1a9e57"
GREEN_BRIGHT = "#22b866"
YELLOW = "#b8860b"
ORANGE = "#d8611c"
RED = "#d64545"

ACCENT = "#20649c"          # headings / accent text (readable on white)
ACCENT_STRONG = "#2f7fd6"   # interactive highlight
ACCENT_DEEP = "#1e5aa8"     # button base blue
INDIGO = "#5b5bd6"
VIOLET = "#8b5cf6"
PINK = "#d6549c"

# Muted text used by both themes for secondary labels.
TEXT_MUTED = "#64748b"

LIGHT: Dict[str, str] = {
    "name": "light",
    # Surfaces.
    "bg": "#eef1f5",
    "bg_top": "#f6f8fa",
    "panel": "#ffffff",
    "panel_alt": "#f7f9fc",
    "panel_hover": "#eef3f9",
    "track": "#e4e9f0",
    "plot_bg": "#ffffff",
    "header": "#ffffff",
    # Borders.
    "border": "#d8dfe8",
    "border_light": "#c5cfdc",
    # Text.
    "text": "#1d2b3a",
    "text_muted": "#5a6b7d",
    "text_faint": "#8494a6",
    "value_strong": "#12202e",
    # Accent text on this surface.
    "accent_text": "#20649c",
    # Plot grid/axis.
    "axis": "#9fb0c2",
    "grid_alpha": "0.35",
    # Selection.
    "selection_bg": "#2f7fd6",
    # Painted-widget helpers.
    "gauge_track": "#dbe3ec",
    "tick": "#8ea2b8",
    "needle": "#33475c",
    "radar_ring": "#dbe3ec",
    "radar_spoke": "#c5cfdc",
    "radar_label": "#42556a",
}

DARK: Dict[str, str] = {
    "name": "dark",
    "bg": "#0f1522",
    "bg_top": "#121a2a",
    "panel": "#151e30",
    "panel_alt": "#1a2438",
    "panel_hover": "#213050",
    "track": "#101828",
    "plot_bg": "#121a2a",
    "header": "#131c2e",
    "border": "#263650",
    "border_light": "#33476a",
    "text": "#e8eef7",
    "text_muted": "#9cabc4",
    "text_faint": "#748296",
    "value_strong": "#ffffff",
    "accent_text": "#8ecbff",
    "axis": "#4e6284",
    "grid_alpha": "0.18",
    "selection_bg": "#2f6fd6",
    "gauge_track": "#232f47",
    "tick": "#5b7199",
    "needle": "#e8eef7",
    "radar_ring": "#1e2c46",
    "radar_spoke": "#2c3e63",
    "radar_label": "#c9d6e8",
}

THEMES = {"light": LIGHT, "dark": DARK}

# LIGHT MODE is the V8.2 default.
_active: Dict[str, str] = LIGHT

# Live registries so theme switches propagate without rebuilding widgets.
_plot_registry: "weakref.WeakSet" = weakref.WeakSet()
_listeners: List[Callable[[], None]] = []


# --------------------------------------------------------------- accessors --
def active_theme() -> Dict[str, str]:
    """The token dictionary of the currently active theme."""
    return _active


def theme_name() -> str:
    return _active["name"]


def color(token: str) -> str:
    """Hex string for a token of the ACTIVE theme (falls back to text color)."""
    return _active.get(token, _active["text"])


def qcolor(token: str) -> QColor:
    """QColor for a token of the ACTIVE theme (for custom painting)."""
    return QColor(color(token))


def painter_font(size: int, bold: bool = False) -> QFont:
    font = QFont(PAINTER_FONT, size)
    font.setBold(bold)
    return font


def tint(hex_color: str, alpha: float = 0.12) -> str:
    """rgba() string for a soft tinted background of a semantic color.

    Qt stylesheets parse 8-digit hex as #AARRGGBB, which silently produces the
    wrong color — always use rgba() for translucency.
    """
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.2f})"


def status_color(state: str) -> str:
    """Map a semantic state name to its hex color (theme-neutral)."""
    return {
        "green": GREEN,
        "yellow": YELLOW,
        "orange": ORANGE,
        "red": RED,
        "blue": ACCENT_STRONG,
        "gray": TEXT_MUTED,
        "pink": PINK,
        "violet": VIOLET,
        "indigo": INDIGO,
    }.get(state, TEXT_MUTED)


def progress_state_qss(value: float) -> str:
    """Stylesheet for a QProgressBar whose chunk color tracks the value."""
    if value < 35:
        chunk = GREEN
    elif value < 65:
        chunk = YELLOW
    elif value < 80:
        chunk = ORANGE
    else:
        chunk = RED
    t = _active
    return (
        f"QProgressBar {{ background: {t['track']}; border: 1px solid {t['border']}; "
        f"border-radius: 7px; text-align: center; font-size: 10pt; color: {t['text_muted']}; }}"
        f"QProgressBar::chunk {{ background: {chunk}; border-radius: 7px; }}"
    )


def style_plot(plot, y_label: str = "", x_label: str = "") -> None:
    """Apply the active theme to a pyqtgraph PlotWidget and register it so it
    is restyled automatically when the theme changes."""
    import pyqtgraph as pg

    t = _active
    plot.setBackground(t["plot_bg"])
    plot.showGrid(x=True, y=True, alpha=float(t["grid_alpha"]))
    for axis_name, label in (("left", y_label), ("bottom", x_label)):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen(t["axis"]))
        axis.setTextPen(pg.mkPen(t["text_muted"]))
        axis.setTickFont(painter_font(9))
        if label:
            axis.setLabel(label)
        else:
            axis.setLabel("")
    plot.getViewBox().setDefaultPadding(0.02)
    _plot_registry.add(plot)


def add_theme_listener(callback: Callable[[], None]) -> None:
    """Register a callback fired after every theme switch (weak usage: keep
    references small; callbacks should only restyle, never rebuild)."""
    _listeners.append(callback)


# ------------------------------------------------------------------- QSS ----
def build_qss(t: Dict[str, str]) -> str:
    """Build the full application stylesheet from a token set.

    Typography rules for V8.2: 11pt body minimum, clear title hierarchy,
    comfortable padding, no tiny labels.
    """
    return f"""
QWidget {{ background: {t['bg']}; color: {t['text']}; font-family: {FONT_FAMILY}; font-size: 11pt; }}
QMainWindow, QDialog {{ background: {t['bg']}; }}
QLabel {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QWidget#OverviewScrollContent, QWidget#PageScrollContent {{ background: transparent; }}
QWidget#CentralRoot {{ background: {t['bg']}; }}

/* ------------------------------------------------------------ typography */
QLabel#PageTitle {{ font-size: 20pt; font-weight: 700; color: {t['text']}; }}
QLabel#PageSubtitle {{ font-size: 11.5pt; color: {t['text_muted']}; }}
QLabel#SectionTitle {{ font-size: 13pt; font-weight: 700; color: {t['text']}; }}
QLabel#BigValue {{ font-size: 12.5pt; font-weight: 600; color: {t['text']}; }}
QLabel#HeadlineValue {{ font-size: 26pt; font-weight: 700; color: {t['value_strong']}; }}
QLabel#StatValue {{ font-size: 17pt; font-weight: 700; color: {t['value_strong']}; }}
QLabel#StatLabel {{ font-size: 10.5pt; color: {t['text_muted']}; }}
QLabel#SmallMuted {{ color: {t['text_muted']}; font-size: 10pt; }}
QLabel#WarningText {{ color: {YELLOW}; font-weight: 600; font-size: 10.5pt; }}
QLabel#SourceTag {{ color: {t['text_muted']}; font-size: 9.5pt; border: 1px solid {t['border']};
                    border-radius: 8px; padding: 1px 8px; background: {t['panel_alt']}; }}
QLabel#EmptyState {{ color: {t['text_muted']}; font-size: 11pt; padding: 18px;
                     border: 1px dashed {t['border_light']}; border-radius: 10px;
                     background: {t['panel_alt']}; }}

/* ---------------------------------------------------------------- header */
QFrame#AppHeader {{ background: {t['header']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame#HeaderDivider {{ background: {t['border']}; border: none; border-radius: 1px; }}
QLabel#AppTitle {{ font-size: 19pt; font-weight: 700; color: {t['text']}; }}
QLabel#AppSubtitle {{ font-size: 10.5pt; color: {t['text_muted']}; }}
QLabel#StatusPill {{ font-size: 10.5pt; font-weight: 600; padding: 5px 14px; border-radius: 12px;
                     background: {t['panel_alt']}; border: 1px solid {t['border_light']};
                     color: {t['text_muted']}; }}

/* ------------------------------------------------------------- panels */
QGroupBox {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 12px;
             margin-top: 12px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 8px; color: {t['accent_text']};
                    font-weight: 700; font-size: 10.5pt; background: {t['panel']};
                    border: 1px solid {t['border']}; border-bottom: none;
                    border-top-left-radius: 6px; border-top-right-radius: 6px; }}

QFrame#Card, QFrame#StatCard {{ background: {t['panel']}; border: 1px solid {t['border']};
                                border-radius: 12px; }}
QFrame#VitalCard, QFrame#HormoneCard {{
    background: {t['panel']};
    border: 1px solid {t['border']}; border-radius: 12px;
}}
QFrame#VitalCard:hover, QFrame#HormoneCard:hover {{ border-color: {t['border_light']}; }}
QFrame#VitalCard[state="green"]   {{ border-left: 4px solid {GREEN}; }}
QFrame#VitalCard[state="yellow"]  {{ border-left: 4px solid {YELLOW}; }}
QFrame#VitalCard[state="orange"]  {{ border-left: 4px solid {ORANGE}; }}
QFrame#VitalCard[state="red"]     {{ border-left: 4px solid {RED}; }}
QFrame#VitalCard[state="blue"]    {{ border-left: 4px solid {ACCENT_STRONG}; }}
QFrame#VitalCard[state="gray"]    {{ border-left: 4px solid {t['border_light']}; }}

QLabel#VitalValue {{ font-size: 20pt; font-weight: 700; color: {t['value_strong']}; }}
QLabel#HormoneValue {{ font-size: 11.5pt; font-weight: 700; color: {t['value_strong']}; }}
QLabel#HormoneTitle {{ color: {t['accent_text']}; font-weight: 700; font-size: 10.5pt; }}

/* ------------------------------------------------------------- buttons */
QPushButton {{
    background: {ACCENT_DEEP};
    border: 1px solid {ACCENT_DEEP}; border-radius: 8px; padding: 8px 14px;
    font-weight: 600; color: #ffffff; font-size: 10.5pt;
}}
QPushButton:hover {{ background: {ACCENT_STRONG}; border-color: {ACCENT_STRONG}; }}
QPushButton:pressed {{ background: #174a86; border-color: #174a86; }}
QPushButton:focus {{ border: 2px solid {ACCENT_STRONG}; }}
QPushButton:disabled {{ background: {t['track']}; border-color: {t['border']}; color: {t['text_faint']}; }}
QPushButton[flat="true"], QPushButton#SecondaryButton {{
    background: {t['panel']}; color: {t['accent_text']}; border: 1px solid {t['border_light']};
}}
QPushButton#SecondaryButton:hover {{ background: {t['panel_hover']}; }}
QToolButton {{ background: transparent; color: {t['accent_text']}; border: none;
               font-weight: 600; font-size: 10.5pt; padding: 4px 6px; }}
QToolButton:hover {{ color: {ACCENT_STRONG}; }}

/* -------------------------------------------------------------- inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {{
    background: {t['panel']}; border: 1px solid {t['border_light']}; border-radius: 8px;
    padding: 6px 8px; font-size: 10.5pt; color: {t['text']};
    selection-background-color: {t['selection_bg']}; selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover {{
    border-color: {ACCENT_STRONG}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
    border-color: {ACCENT_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent; border-right: 5px solid transparent;
                         border-top: 6px solid {t['text_muted']}; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border_light']};
                               border-radius: 8px; selection-background-color: {t['selection_bg']};
                               selection-color: white; outline: 0; padding: 4px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QSpinBox::down-button,
QDoubleSpinBox::down-button, QTimeEdit::down-button {{
    background: transparent; border: none; width: 18px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid {t['text_muted']}; margin: 2px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {t['text_muted']}; margin: 2px;
}}

/* ---------------------------------------------------------- progress */
QProgressBar {{ background: {t['track']}; border: 1px solid {t['border']}; border-radius: 7px;
                text-align: center; font-size: 10pt; color: {t['text_muted']}; }}
QProgressBar::chunk {{ background: {ACCENT_STRONG}; border-radius: 7px; }}

/* --------------------------------------------------------------- tabs */
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 10px; top: -1px;
                    background: {t['panel']}; }}
QTabBar::tab {{
    background: {t['bg']}; border: 1px solid {t['border']}; border-top-left-radius: 8px;
    border-top-right-radius: 8px; padding: 9px 16px; margin: 2px 2px 0 2px;
    font-size: 10.5pt; color: {t['text_muted']};
}}
QTabBar::tab:selected {{
    background: {t['panel']}; color: {t['accent_text']}; font-weight: 700;
    border-color: {t['border_light']}; border-bottom: 2px solid {ACCENT_STRONG};
}}
QTabBar::tab:hover:!selected {{ background: {t['panel_hover']}; color: {t['text']}; }}
QTabBar::tab:disabled {{ color: {t['text_faint']}; }}

/* Top-level navigation (PATIENT / CLINICIAN / RESEARCH / SETTINGS). */
QTabWidget#MainNav::pane {{ border: none; background: transparent; top: 4px; }}
QTabWidget#MainNav > QTabBar::tab {{
    background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 9px;
    padding: 10px 26px; margin: 2px 6px 6px 0; font-size: 12pt; font-weight: 600;
    color: {t['text_muted']};
}}
QTabWidget#MainNav > QTabBar::tab:selected {{
    background: {ACCENT_DEEP}; color: #ffffff; border-color: {ACCENT_DEEP};
}}
QTabWidget#MainNav > QTabBar::tab:hover:!selected {{
    background: {t['panel_hover']}; color: {t['text']};
}}

/* ------------------------------------------------------------- text */
QTextEdit, QPlainTextEdit {{
    background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 8px;
    font-size: 10.5pt; color: {t['text']};
    selection-background-color: {t['selection_bg']}; selection-color: #ffffff;
}}
QTextEdit:focus {{ border-color: {ACCENT_STRONG}; }}

/* ------------------------------------------------------------- tables */
QTableWidget, QTableView {{
    background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 9px;
    font-size: 10.5pt; gridline-color: {t['border']}; selection-background-color: {t['selection_bg']};
    alternate-background-color: {t['panel_alt']}; color: {t['text']};
}}
QTableWidget::item {{ padding: 5px 7px; }}
QTableWidget::item:selected {{ background: {t['selection_bg']}; color: white; }}
QHeaderView::section {{ background: {t['panel_alt']}; color: {t['text']}; font-weight: 700; padding: 8px;
                        border: none; border-bottom: 2px solid {t['border_light']}; font-size: 10.5pt; }}

QListWidget {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 10px;
               padding: 6px; outline: 0; font-size: 10.5pt; color: {t['text']}; }}
QListWidget::item {{ border: none; margin: 2px; background: transparent; }}
QListWidget::item:hover {{ background: {t['panel_hover']}; border-radius: 8px; }}
QListWidget::item:selected {{ background: {t['panel_hover']}; border-radius: 8px; color: {t['text']}; }}

/* ------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{ height: 6px; background: {t['track']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_STRONG}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: #ffffff; width: 18px; margin: -6px 0; border-radius: 9px;
                              border: 2px solid {ACCENT_STRONG}; }}

/* ---------------------------------------------------------- scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border_light']}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text_faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_light']}; border-radius: 5px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['text_faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --------------------------------------------------------------- menus */
QMenu {{ background: {t['panel']}; border: 1px solid {t['border_light']}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; color: {t['text']}; }}
QMenu::item:selected {{ background: {t['selection_bg']}; color: white; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 10px; }}

QCheckBox {{ spacing: 8px; color: {t['text']}; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px;
                        border: 1px solid {t['border_light']}; background: {t['panel']}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT_STRONG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT_STRONG}; border-color: {ACCENT_STRONG}; }}

QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border_light']};
            padding: 7px; border-radius: 7px; font-size: 10pt; }}
"""


# Pre-built stylesheets (kept for backwards compatibility with older imports).
LIGHT_QSS = build_qss(LIGHT)
DARK_QSS = build_qss(DARK)


def apply_theme(name: str) -> str:
    """Switch the ACTIVE theme, restyle the QApplication + registered plots and
    notify listeners.  Returns the stylesheet that was applied."""
    global _active
    _active = THEMES.get(name, LIGHT)
    qss = build_qss(_active)
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
    except Exception:
        pass
    # Restyle live pyqtgraph plots.
    for plot in list(_plot_registry):
        try:
            style_plot(plot)
        except Exception:
            pass
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            pass
    return qss


# ------------------------------------------------- backwards-compat aliases --
# Older widgets import these module constants directly.  They now resolve to
# the LIGHT (default) token values for construction-time styling; runtime
# styling should use color()/qcolor() instead.
BG = LIGHT["bg"]
BG_TOP = LIGHT["bg_top"]
PANEL = LIGHT["panel"]
PANEL_ALT = LIGHT["panel_alt"]
PANEL_HOVER = LIGHT["panel_hover"]
TRACK = LIGHT["track"]
PLOT_BG = LIGHT["plot_bg"]
BORDER = LIGHT["border"]
BORDER_LIGHT = LIGHT["border_light"]
TEXT = LIGHT["text"]
