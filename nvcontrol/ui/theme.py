"""Visual themes: NVIDIA-green operator console (default) and ULTRA VENECO KEYGEN MODE.

Type: Barlow Semi Condensed (display), Inter (UI text), JetBrains Mono (numbers/data),
all SIL OFL, bundled in ui/fonts so the look doesn't depend on installed fonts.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

log = logging.getLogger(__name__)
FONT_DIR = Path(__file__).parent / "fonts"

NVIDIA = {
    "bg": "#0A0B0A", "bg2": "#0E100E", "panel": "#121412", "panel_hi": "#171A17",
    "border": "#222622", "border_hi": "#30352F",
    "accent": "#76B900", "accent_hi": "#8CD000", "accent_dim": "#36530A", "accent_glow": "#76B90040",
    "text": "#ECEEE8", "muted": "#9BA196", "faint": "#5E645A",
    "warn": "#F5A524", "crit": "#FF4D5E", "info": "#6CC8DA",
    "on_accent": "#071000",
    "graph2": "#D9DCD4", "graph3": "#F5A524",
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


def qc(key: str, alpha: int | None = None) -> QColor:
    c = QColor(C.get(key, key))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


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
    for f in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) < 0:
            log.warning("could not load bundled font %s", f.name)
    FONTS["head"] = _pick(["Barlow Semi Condensed", "Rajdhani", "Roboto Condensed", "DejaVu Sans Condensed"],
                          "Sans Serif")
    FONTS["body"] = _pick(["Inter", "Noto Sans", "Cantarell", "DejaVu Sans"], "Sans Serif")
    FONTS["mono"] = _pick(["JetBrains Mono", "Fira Code", "Noto Sans Mono", "DejaVu Sans Mono"], "Monospace")
    FONTS["veneco"] = _pick(["Comic Sans MS", "Comic Neue", "Impact", "Anton", "DejaVu Sans"], "Sans Serif")


def font(kind: str = "body", size: float = 10, bold: bool = False, spacing: float = 0.0,
         weight: QFont.Weight | None = None) -> QFont:
    fam = FONTS.get("veneco") if is_veneco() and kind == "head" else FONTS.get(kind, "Sans Serif")
    f = QFont(fam)
    f.setPointSizeF(size)
    if weight is not None:
        f.setWeight(weight)
    elif bold:
        f.setWeight(QFont.DemiBold if kind != "mono" else QFont.Bold)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def stylesheet() -> str:
    c = C
    head = FONTS.get("veneco") if is_veneco() else FONTS.get("head")
    body = FONTS.get("body")
    mono = FONTS.get("mono")
    v = is_veneco()
    if v:
        btn_bg = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F4F4F4, stop:0.45 #A8A8B8, stop:0.5 #6E6E80, stop:1 #C8C8D8)"
        btn_fg, btn_border = "#1A0033", c["border_hi"]
        win_bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1A0033, stop:0.5 #3A0075, stop:1 #0A0018)"
        radius, r_small = "9px", "9px"
    else:
        btn_bg = "rgba(255,255,255,0.035)"
        btn_fg, btn_border = c["text"], c["border_hi"]
        win_bg = c["bg"]
        radius, r_small = "6px", "4px"
    primary = (f"qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {c['accent_hi']}, stop:1 {c['accent']})"
               if not v else c["accent"])
    return f"""
* {{ font-family: "{body}"; font-size: 9.5pt; color: {c['text']}; }}
QMainWindow, QDialog, #Root {{ background: {win_bg}; }}
QWidget#Workspace, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {c['panel_hi']}; color: {c['text']}; border: 1px solid {c['border_hi']};
  border-radius: {r_small}; padding: 6px 8px; }}
QLabel#H1 {{ font-family: "{head}"; font-size: 24pt; font-weight: 600; letter-spacing: 0.3px; color: {c['text']}; }}
QLabel#H2 {{ font-family: "{head}"; font-size: 15pt; font-weight: 600; letter-spacing: 0.3px; color: {c['text']}; }}
QLabel#H3 {{ font-family: "{head}"; font-size: 12.5pt; font-weight: 600; letter-spacing: 0.2px; color: {c['text']}; }}
QLabel#Kicker {{ font-family: "{mono}"; font-size: 7.5pt; letter-spacing: 1.4px; color: {c['accent']}; }}
QLabel#Mono, QPlainTextEdit#Mono, QTextEdit#Mono {{ font-family: "{mono}"; font-size: 8.5pt; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Faint {{ color: {c['faint']}; font-size: 8.5pt; }}
QLabel#Warn {{ color: {c['warn']}; }}
QLabel#Crit {{ color: {c['crit']}; font-weight: 600; }}
QLabel#Big {{ font-family: "{head}"; font-size: 24pt; font-weight: 600; }}
QPushButton {{
  background: {btn_bg}; color: {btn_fg}; border: 1px solid {btn_border};
  border-radius: {radius}; padding: 7px 14px; font-family: "{body}"; font-weight: 600; font-size: 9pt;
}}
QPushButton:hover {{ border-color: {c['accent']}; background: {"rgba(118,185,0,0.08)" if not v else btn_bg}; }}
QPushButton:pressed {{ background: {c['accent_dim']}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: {c['border']}; background: transparent; }}
QPushButton#Primary {{ background: {primary}; color: {c['on_accent']}; border: 1px solid {c['accent_hi']}; }}
QPushButton#Primary:hover {{ background: {c['accent_hi']}; }}
QPushButton#Primary:disabled {{ background: {c['accent_dim']}; color: {c['bg']}; border-color: {c['accent_dim']}; }}
QPushButton#Danger {{ border-color: rgba(255,77,94,0.55); color: {c['crit']}; background: transparent; }}
QPushButton#Danger:hover {{ background: rgba(255,77,94,0.12); border-color: {c['crit']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
  background: {c['bg2']}; border: 1px solid {c['border']}; padding: 5px 8px; border-radius: {r_small};
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c['border_hi']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {c['faint']}; }}
QAbstractSpinBox {{ padding-right: 8px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['panel_hi']}; border: 1px solid {c['border_hi']}; padding: 4px;
  selection-background-color: rgba(118,185,0,0.18); selection-color: {c['text']}; outline: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['accent_dim']}, stop:1 {c['accent']});
  border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; background: {c['text']};
  border: 3px solid {c['accent']}; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {c['accent_hi']}; }}
QSlider::handle:horizontal:disabled {{ background: {c['faint']}; border-color: {c['border_hi']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {c['border_hi']}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {c['border_hi']};
  background: {c['bg2']}; border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent_hi']}; }}
QCheckBox::indicator:disabled {{ background: transparent; border-color: {c['border']}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['faint']}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {c['bg2']}; border: 1px solid {c['border']}; border-radius: {r_small};
  gridline-color: transparent; alternate-background-color: rgba(255,255,255,0.018); }}
QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {c['border']}; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
  background: rgba(118,185,0,0.16); color: {c['text']}; }}
QListWidget::item {{ padding: 7px 8px; border-radius: 4px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.03); }}
QHeaderView::section {{ background: transparent; color: {c['muted']}; border: none;
  border-bottom: 1px solid {c['border_hi']}; padding: 7px 6px; font-family: "{mono}"; font-size: 7.5pt; letter-spacing: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_hi']}; min-height: 36px; border-radius: 3px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent_dim']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border_hi']}; min-width: 36px; border-radius: 3px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; top: -1px; background: rgba(255,255,255,0.012);
  border-radius: {r_small}; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 9px 18px; border-bottom: 2px solid transparent;
  font-family: "{body}"; font-weight: 600; font-size: 9pt; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QProgressBar {{ background: {c['bg2']}; border: 1px solid {c['border']}; height: 8px; text-align: center;
  font-family: "{mono}"; font-size: 7.5pt; border-radius: 4px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QGroupBox {{ border: 1px solid {c['border']}; margin-top: 14px; padding-top: 10px; border-radius: {r_small}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {c['accent']}; font-family: "{mono}"; font-size: 7.5pt; }}
QMenu {{ background: {c['panel_hi']}; border: 1px solid {c['border_hi']}; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(118,185,0,0.18); }}
QStatusBar {{ background: {c['bg']}; color: {c['muted']}; border-top: 1px solid {c['border']};
  font-family: "{mono}"; font-size: 7.5pt; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: transparent; width: 10px; }}
"""
