"""Visual themes: NVIDIA-green operator console (default) and ULTRA VENECO KEYGEN MODE."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

NVIDIA = {
    "bg": "#090A09", "bg2": "#0E100E", "panel": "#141614", "panel_hi": "#1B1E1B",
    "border": "#2A2E2A", "border_hi": "#3A403A",
    "accent": "#76B900", "accent_hi": "#8FD400", "accent_dim": "#3E6100", "accent_glow": "#76B90055",
    "text": "#E9ECE6", "muted": "#8D938A", "faint": "#5C625A",
    "warn": "#FFB000", "crit": "#FF3B4E", "info": "#5FD4E8",
    "on_accent": "#050505",
    "graph2": "#E9ECE6", "graph3": "#FFB000",
}

VENECO = {
    "bg": "#1A0033", "bg2": "#24004A", "panel": "#2B0057", "panel_hi": "#3A0075",
    "border": "#FFCC00", "border_hi": "#FF00FF",
    "accent": "#39FF14", "accent_hi": "#B6FF00", "accent_dim": "#1E8A0A", "accent_glow": "#39FF1488",
    "text": "#FFFFFF", "muted": "#FFD6FF", "faint": "#C080FF",
    "warn": "#FFCC00", "crit": "#FF2244", "info": "#00E5FF",
    "on_accent": "#1A0033",
    "graph2": "#FFCC00", "graph3": "#FF2244",
    "flag_y": "#FFCC00", "flag_b": "#00247D", "flag_r": "#CF142B",
}

C: dict[str, str] = dict(NVIDIA)
MODE = {"name": "nvidia"}


def qc(key: str) -> QColor:
    return QColor(C.get(key, key))


def set_mode(name: str) -> None:
    C.clear()
    C.update(VENECO if name == "veneco" else NVIDIA)
    MODE["name"] = name


def is_veneco() -> bool:
    return MODE["name"] == "veneco"


def _pick(families: list[str], fallback: str) -> str:
    have = set(QFontDatabase.families())
    for f in families:
        if f in have:
            return f
    return fallback


FONTS: dict[str, str] = {}


def init_fonts() -> None:
    FONTS["head"] = _pick(["Rajdhani", "Barlow Condensed", "Saira Condensed", "Roboto Condensed",
                           "Noto Sans Condensed", "DejaVu Sans Condensed", "Liberation Sans Narrow"], "Sans Serif")
    FONTS["body"] = _pick(["Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans"], "Sans Serif")
    FONTS["mono"] = _pick(["JetBrains Mono", "Fira Code", "Hack", "Noto Sans Mono", "DejaVu Sans Mono",
                           "Liberation Mono"], "Monospace")
    FONTS["veneco"] = _pick(["Comic Sans MS", "Comic Neue", "Impact", "Anton", "DejaVu Sans"], "Sans Serif")


def font(kind: str = "body", size: int = 10, bold: bool = False, spacing: float = 0.0) -> QFont:
    fam = FONTS.get("veneco") if is_veneco() and kind == "head" else FONTS.get(kind, "Sans Serif")
    f = QFont(fam, size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def stylesheet() -> str:
    c = C
    head = FONTS.get("veneco") if is_veneco() else FONTS.get("head")
    body = FONTS.get("body")
    mono = FONTS.get("mono")
    if is_veneco():
        btn_bg = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F4F4F4, stop:0.45 #A8A8B8, stop:0.5 #6E6E80, stop:1 #C8C8D8)"
        btn_fg = "#1A0033"
        win_bg = ("qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1A0033, stop:0.5 #3A0075, stop:1 #0A0018)")
        radius = "9px"
    else:
        btn_bg = c["panel_hi"]
        btn_fg = c["text"]
        win_bg = c["bg"]
        radius = "0px"
    return f"""
* {{ font-family: "{body}"; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QDialog, #Root {{ background: {win_bg}; }}
QWidget#Workspace, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {c['panel_hi']}; color: {c['text']}; border: 1px solid {c['accent']}; padding: 6px; }}
QLabel#H1 {{ font-family: "{head}"; font-size: 22pt; font-weight: 700; letter-spacing: 2px; color: {c['text']}; }}
QLabel#H2 {{ font-family: "{head}"; font-size: 13pt; font-weight: 700; letter-spacing: 1.5px; color: {c['text']}; }}
QLabel#H3 {{ font-family: "{head}"; font-size: 11pt; font-weight: 700; letter-spacing: 1px; color: {c['accent']}; }}
QLabel#Kicker {{ font-family: "{mono}"; font-size: 8pt; letter-spacing: 2px; color: {c['accent']}; }}
QLabel#Mono, QPlainTextEdit#Mono, QTextEdit#Mono {{ font-family: "{mono}"; font-size: 9pt; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Faint {{ color: {c['faint']}; font-size: 9pt; }}
QLabel#Warn {{ color: {c['warn']}; }}
QLabel#Crit {{ color: {c['crit']}; font-weight: 700; }}
QLabel#Big {{ font-family: "{head}"; font-size: 24pt; font-weight: 700; }}
QPushButton {{
  background: {btn_bg}; color: {btn_fg}; border: 1px solid {c['border_hi']};
  border-radius: {radius}; padding: 7px 14px; font-family: "{head}"; font-weight: 700;
  letter-spacing: 1px; font-size: 10pt;
}}
QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent_hi'] if not is_veneco() else '#000'}; }}
QPushButton:pressed {{ background: {c['accent_dim']}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: {c['border']}; background: {c['panel']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['on_accent']}; border: 1px solid {c['accent_hi']}; }}
QPushButton#Primary:hover {{ background: {c['accent_hi']}; color: {c['on_accent']}; }}
QPushButton#Primary:disabled {{ background: {c['accent_dim']}; color: {c['bg']}; }}
QPushButton#Danger {{ border-color: {c['crit']}; color: {c['crit']}; }}
QPushButton#Danger:hover {{ background: {c['crit']}; color: #000; }}
QPushButton#Nav {{
  background: transparent; border: none; border-left: 3px solid transparent; text-align: left;
  padding: 11px 14px; color: {c['muted']}; font-size: 10pt; letter-spacing: 1.5px; border-radius: 0px;
}}
QPushButton#Nav:hover {{ color: {c['text']}; background: {c['panel']}; }}
QPushButton#Nav:checked {{ color: {c['accent']}; border-left: 3px solid {c['accent']}; background: {c['panel_hi']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
  background: {c['bg2']}; border: 1px solid {c['border']}; padding: 5px 7px; border-radius: {radius};
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['accent']};
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; }}
QSlider::handle:horizontal {{ width: 12px; height: 18px; margin: -7px 0; background: {c['text']};
  border: 2px solid {c['accent']}; }}
QSlider::handle:horizontal:disabled {{ background: {c['faint']}; border-color: {c['border']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {c['faint']}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {c['border_hi']}; background: {c['bg2']}; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent_hi']}; }}
QCheckBox::indicator:disabled {{ background: {c['panel']}; border-color: {c['border']}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['faint']}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {c['bg2']}; border: 1px solid {c['border']};
  gridline-color: {c['border']}; alternate-background-color: {c['panel']}; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
  background: {c['accent_dim']}; color: {c['text']}; }}
QListWidget::item {{ padding: 6px; }}
QHeaderView::section {{ background: {c['panel_hi']}; color: {c['accent']}; border: none;
  border-bottom: 1px solid {c['accent_dim']}; padding: 6px; font-family: "{mono}"; font-size: 8pt; letter-spacing: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border_hi']}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {c['border_hi']}; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; top: -1px; background: {c['panel']}; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 16px; border-bottom: 2px solid transparent;
  font-family: "{head}"; font-weight: 700; letter-spacing: 1px; }}
QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
QProgressBar {{ background: {c['bg2']}; border: 1px solid {c['border']}; height: 10px; text-align: center;
  font-family: "{mono}"; font-size: 8pt; border-radius: {radius}; }}
QProgressBar::chunk {{ background: {c['accent']}; }}
QGroupBox {{ border: 1px solid {c['border']}; margin-top: 14px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {c['accent']}; font-family: "{mono}"; font-size: 8pt; letter-spacing: 2px; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['accent']}; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['on_accent']}; }}
QStatusBar {{ background: {c['bg2']}; color: {c['muted']}; border-top: 1px solid {c['border']}; font-family: "{mono}"; font-size: 8pt; }}
"""
