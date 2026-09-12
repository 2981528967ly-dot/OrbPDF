"""Colour tokens and the generated Qt stylesheet (dark = Defect chassis, light = clean)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.paths import session_dir

DARK = {
    "bg": "#0A0F1C", "bg2": "#0D1424", "surface": "#121A2B", "surface2": "#182236", "surface3": "#1E2A42",
    "border": "#243149", "border2": "#2F3E5C",
    "text": "#E4ECF7", "text2": "#B4BFD2", "muted": "#7F8CA5",
    "accent": "#5AD8FF", "accent_hover": "#7FE3FF", "accent_ink": "#06202B",
    "accent_dim": "rgba(90,216,255,0.14)", "accent_line": "rgba(90,216,255,0.45)",
    "danger": "#FF6B7A", "danger_dim": "rgba(255,107,122,0.16)", "warn": "#FFB454", "warn_dim": "rgba(255,180,84,0.16)",
    "ok": "#6EF2A6", "ok_dim": "rgba(110,242,166,0.16)",
    "orb_blue": "#7FE3FF", "orb_gold": "#FFD166", "orb_green": "#6EF2A6", "orb_purple": "#A78BFA", "orb_white": "#E8EEF7",
    "sheet": "#FFFFFF", "shadow": "rgba(0,0,0,0.5)",
}
LIGHT = {
    "bg": "#EEF2F8", "bg2": "#E6ECF5", "surface": "#FFFFFF", "surface2": "#F3F6FB", "surface3": "#E9EEF6",
    "border": "#D5DDEA", "border2": "#BFCADB",
    "text": "#101B2E", "text2": "#3F4D66", "muted": "#6B788F",
    "accent": "#0891C7", "accent_hover": "#0EA5E9", "accent_ink": "#FFFFFF",
    "accent_dim": "rgba(8,145,199,0.12)", "accent_line": "rgba(8,145,199,0.5)",
    "danger": "#E0344A", "danger_dim": "rgba(224,52,74,0.12)", "warn": "#D97706", "warn_dim": "rgba(217,119,6,0.12)",
    "ok": "#12A85B", "ok_dim": "rgba(18,168,91,0.12)",
    "orb_blue": "#0EA5E9", "orb_gold": "#D69E00", "orb_green": "#12A85B", "orb_purple": "#7C5CE6", "orb_white": "#9AA8BF",
    "sheet": "#FFFFFF", "shadow": "rgba(30,50,90,0.18)",
}


@dataclass
class Theme:
    name: str
    tokens: dict[str, str]

    def c(self, key: str) -> str:
        return self.tokens[key]

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


_current = Theme("dark", DARK)


def current() -> Theme:
    return _current


def set_theme(name: str) -> Theme:
    global _current
    _current = Theme("light", LIGHT) if name == "light" else Theme("dark", DARK)
    return _current


def _icon_file(name: str, svg: str) -> str:
    d = session_dir() / "ui"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(svg, encoding="utf-8")
    return p.as_posix()


def build_qss(t: Theme) -> str:
    c = t.tokens
    check = _icon_file(f"check-{t.name}.svg",
                       f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-6.5" fill="none" stroke="{c["accent_ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    chevron = _icon_file(f"chevron-{t.name}.svg",
                         f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" fill="none" stroke="{c["muted"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    up = _icon_file(f"up-{t.name}.svg",
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 10l4-4 4 4" fill="none" stroke="{c["muted"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return f"""
* {{ outline: 0; }}
QWidget {{ color: {c['text']}; font-size: 13px; }}
QMainWindow, QDialog, QWidget#Root, QWidget#Page {{ background: {c['bg']}; }}
QWidget#Sidebar {{ background: {c['bg2']}; border-right: 1px solid {c['border']}; }}
QWidget#Footer {{ background: {c['bg2']}; border-top: 1px solid {c['border']}; }}
QLabel {{ background: transparent; }}
QLabel#ModuleTitle {{ font-size: 19px; font-weight: 600; }}
QLabel#ModuleHint {{ color: {c['muted']}; font-size: 12px; }}
QLabel#PanelTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#Muted {{ color: {c['muted']}; font-size: 12px; }}
QLabel#Small {{ color: {c['muted']}; font-size: 11px; }}
QLabel#Strong {{ font-weight: 600; }}
QLabel#Danger {{ color: {c['danger']}; }}
QLabel#Warn {{ color: {c['warn']}; }}
QLabel#Ok {{ color: {c['ok']}; }}
QLabel#Accent {{ color: {c['accent']}; }}
QLabel#Step {{ background: {c['accent']}; color: {c['accent_ink']}; border-radius: 10px; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; font-weight: 700; font-size: 12px; }}
QLabel#Tag {{ border: 1px solid {c['border2']}; border-radius: 4px; padding: 1px 6px; color: {c['text2']}; font-size: 11px; }}
QLabel#Kbd {{ border: 1px solid {c['border2']}; border-radius: 3px; padding: 0 4px; color: {c['muted']}; font-size: 10px; font-family: Consolas, "Courier New", monospace; }}
QFrame#Panel {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QFrame#PanelAccent {{ background: {c['surface']}; border: 1px solid {c['accent_line']}; border-radius: 8px; }}
QFrame#Card {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QFrame#Card:hover {{ border-color: {c['accent_line']}; }}
QFrame#CardDisabled {{ background: {c['surface2']}; border: 1px dashed {c['border']}; border-radius: 8px; }}
QFrame#Divider {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#Toast {{ background: {c['surface']}; border: 1px solid {c['accent_line']}; border-radius: 10px; }}
QFrame#DropZone {{ background: {c['bg']}; border: 1.5px dashed {c['border2']}; border-radius: 8px; }}
QFrame#DropZoneActive {{ background: {c['accent_dim']}; border: 1.5px dashed {c['accent']}; border-radius: 8px; }}
QFrame#Slots {{ background: {c['bg']}; border: 1px dashed {c['border']}; border-radius: 6px; }}

QPushButton {{ background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 6px; padding: 5px 12px; color: {c['text']}; min-height: 16px; }}
QPushButton:hover {{ border-color: {c['accent_line']}; background: {c['surface3']}; }}
QPushButton:pressed {{ background: {c['surface']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; border-color: {c['border']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['accent_ink']}; font-weight: 600; border: 1px solid transparent; }}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {c['surface3']}; color: {c['muted']}; }}
QPushButton#PrimaryBig {{ background: {c['accent']}; color: {c['accent_ink']}; font-weight: 600; font-size: 15px; border: 1px solid transparent; padding: 10px 16px; border-radius: 7px; }}
QPushButton#PrimaryBig:hover {{ background: {c['accent_hover']}; }}
QPushButton#PrimaryBig:disabled {{ background: {c['surface3']}; color: {c['muted']}; }}
QPushButton#Ghost {{ background: transparent; border-color: transparent; color: {c['muted']}; }}
QPushButton#Ghost:hover {{ color: {c['text']}; border-color: {c['border']}; background: {c['surface2']}; }}
QPushButton#Danger {{ color: {c['danger']}; border-color: {c['danger']}; background: transparent; }}
QPushButton#Danger:hover {{ background: {c['danger_dim']}; }}
QPushButton#Link {{ background: transparent; border: none; color: {c['accent']}; padding: 2px 4px; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QPushButton#Small {{ padding: 2px 8px; font-size: 12px; min-height: 14px; }}
QPushButton#Seg {{ background: transparent; border: none; border-radius: 5px; padding: 4px 12px; color: {c['muted']}; }}
QPushButton#Seg:checked {{ background: {c['accent_dim']}; color: {c['accent']}; font-weight: 600; }}
QPushButton#Seg:hover {{ color: {c['text']}; }}
QFrame#SegFrame {{ background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 6px; }}
QPushButton#IconBtn {{ background: transparent; border: 1px solid transparent; padding: 3px; border-radius: 5px; }}
QPushButton#IconBtn:hover {{ background: {c['surface3']}; border-color: {c['border2']}; }}
QPushButton#IconBtn:checked {{ background: {c['accent_dim']}; border-color: {c['accent_line']}; }}
QPushButton#ToolCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 14px; text-align: left; }}
QPushButton#ToolCard:hover {{ border-color: {c['accent_line']}; background: {c['surface2']}; }}
QPushButton#ToolCard:disabled {{ color: {c['muted']}; border-style: dashed; }}

QToolButton#NavButton {{ color: {c['muted']}; border: 1px solid transparent; border-radius: 8px; padding: 6px 2px 5px 2px; font-size: 12px; background: transparent; }}
QToolButton#NavButton:hover {{ color: {c['text']}; background: {c['surface']}; }}
QToolButton#NavButton:checked {{ color: {c['accent']}; background: {c['accent_dim']}; border-color: {c['accent_line']}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 3px; color: {c['text2']}; }}
QToolButton:hover {{ background: {c['surface3']}; border-color: {c['border2']}; }}
QToolButton:checked {{ background: {c['accent_dim']}; border-color: {c['accent_line']}; color: {c['accent']}; }}
QToolButton:disabled {{ color: {c['muted']}; }}
QToolButton::menu-indicator {{ image: none; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{ background: {c['bg']}; border: 1px solid {c['border2']}; border-radius: 6px; padding: 4px 8px; color: {c['text']}; selection-background-color: {c['accent']}; selection-color: {c['accent_ink']}; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
QLineEdit#Inline {{ background: {c['surface']}; border: 1px solid {c['accent']}; padding: 2px 6px; }}
QComboBox::drop-down {{ border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 6px; selection-background-color: {c['accent_dim']}; selection-color: {c['text']}; padding: 4px; outline: 0; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; image: url({up}); }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; image: url({chevron}); }}
QCheckBox {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1.5px solid {c['border2']}; border-radius: 4px; background: {c['bg']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({check}); }}
QCheckBox:disabled {{ color: {c['muted']}; }}
QRadioButton {{ spacing: 7px; background: transparent; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1.5px solid {c['border2']}; background: {c['bg']}; }}
QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
QRadioButton::indicator:checked {{ border: 4px solid {c['accent']}; background: {c['bg']}; width: 9px; height: 9px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border2']}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border2']}; border-radius: 3px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QToolTip {{ background: {c['surface3']}; color: {c['text']}; border: 1px solid {c['border2']}; padding: 5px 8px; border-radius: 4px; }}
QMenu {{ background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 6px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['accent_dim']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QMenu::icon {{ margin-left: 6px; }}

QProgressBar {{ background: {c['surface3']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['surface3']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {c['text']}; border: 2px solid {c['accent']}; }}

QListWidget, QTableWidget, QTreeWidget, QListView, QTableView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; outline: 0; alternate-background-color: {c['surface2']}; }}
QListWidget::item, QTreeWidget::item {{ padding: 4px; border-radius: 4px; }}
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {{ background: {c['accent_dim']}; color: {c['text']}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['surface2']}; }}
QTableWidget {{ gridline-color: {c['border']}; }}
QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {c['border']}; }}
QHeaderView::section {{ background: {c['surface2']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']}; padding: 5px 8px; font-size: 12px; }}
QTableCornerButton::section {{ background: {c['surface2']}; border: none; }}
QListWidget#SettingsNav {{ background: transparent; border: none; }}
QListWidget#SettingsNav::item {{ padding: 8px 10px; color: {c['muted']}; }}
QListWidget#SettingsNav::item:selected {{ background: {c['accent_dim']}; color: {c['accent']}; }}
QListWidget#PageGrid {{ background: {c['bg']}; }}
QListWidget#PageGrid::item {{ padding: 6px; border: 2px solid transparent; border-radius: 6px; color: {c['muted']}; }}
QListWidget#PageGrid::item:selected {{ border-color: {c['accent']}; background: {c['accent_dim']}; color: {c['text']}; }}
QListWidget#PageGrid::item:hover {{ background: {c['surface2']}; }}
QSplitter::handle {{ background: transparent; }}
QTabWidget::pane {{ border: none; }}
QGraphicsView {{ background: {c['bg']}; border: none; }}
QGraphicsView#Chain {{ background: {c['bg']}; border: 1px solid {c['border']}; border-radius: 6px; }}
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; }}
QStatusBar {{ background: {c['bg2']}; }}
"""
