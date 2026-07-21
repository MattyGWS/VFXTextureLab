from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

DEFAULT_THEME_ID = "midnight"

# Themes are intentionally data rather than separate stylesheets.  This keeps
# every widget, graph colour and custom user theme on the same contract.
BUILTIN_THEMES: dict[str, dict[str, Any]] = {
    "midnight": {
        "id": "midnight",
        "name": "Midnight",
        "base": "midnight",
        "colors": {
            "window": "#17191d",
            "panel": "#20242a",
            "panel_alt": "#191c20",
            "panel_selected": "#292e36",
            "input": "#24282f",
            "button": "#292e36",
            "button_hover": "#343a45",
            "button_pressed": "#20242a",
            "border": "#343a43",
            "border_strong": "#505969",
            "text": "#e8eaf0",
            "text_muted": "#9aa2af",
            "text_inverse": "#ffffff",
            "accent": "#7b88ff",
            "accent_hover": "#94a0ff",
            "selection": "#394052",
            "progress": "#ff9d36",
            "error": "#ef6678",
            "success": "#83e39b",
            "graph_background": "#15171b",
            "grid_minor": "#1c1f24",
            "grid_major": "#24282e",
            "node_body": "#22262c",
            "node_body_bypassed": "#191c21",
            "node_border": "#383e48",
            "node_selected": "#d5dbff",
            "node_active": "#7786ff",
            "node_text": "#c5cad3",
            "node_text_muted": "#9097a3",
            "preview_background": "#111317",
            "checker_dark": "#292d34",
            "checker_light": "#3a3e46",
            "scrollbar_track": "#181b20",
            "scrollbar_handle": "#4b5360",
            "scrollbar_hover": "#667181",
        },
    },
    "graphite": {
        "id": "graphite",
        "name": "Graphite",
        "base": "graphite",
        "colors": {
            "window": "#202020",
            "panel": "#292929",
            "panel_alt": "#242424",
            "panel_selected": "#343434",
            "input": "#303030",
            "button": "#333333",
            "button_hover": "#404040",
            "button_pressed": "#282828",
            "border": "#454545",
            "border_strong": "#606060",
            "text": "#eeeeee",
            "text_muted": "#aaaaaa",
            "text_inverse": "#111111",
            "accent": "#49b6a8",
            "accent_hover": "#67cbbf",
            "selection": "#33524f",
            "progress": "#f2a33c",
            "error": "#e66b76",
            "success": "#79cf91",
            "graph_background": "#1b1b1b",
            "grid_minor": "#232323",
            "grid_major": "#303030",
            "node_body": "#2a2a2a",
            "node_body_bypassed": "#222222",
            "node_border": "#484848",
            "node_selected": "#d7f5f1",
            "node_active": "#49b6a8",
            "node_text": "#d8d8d8",
            "node_text_muted": "#9b9b9b",
            "preview_background": "#151515",
            "checker_dark": "#2e2e2e",
            "checker_light": "#414141",
            "scrollbar_track": "#202020",
            "scrollbar_handle": "#5b5b5b",
            "scrollbar_hover": "#777777",
        },
    },
    "daylight": {
        "id": "daylight",
        "name": "Daylight",
        "base": "daylight",
        "colors": {
            "window": "#e7e9ed",
            "panel": "#f2f3f5",
            "panel_alt": "#e9ebee",
            "panel_selected": "#ffffff",
            "input": "#ffffff",
            "button": "#f7f8fa",
            "button_hover": "#e5e9ef",
            "button_pressed": "#d9dee6",
            "border": "#b8bec8",
            "border_strong": "#8f98a6",
            "text": "#20242a",
            "text_muted": "#626b78",
            "text_inverse": "#ffffff",
            "accent": "#2f6fca",
            "accent_hover": "#4384df",
            "selection": "#c8dcf6",
            "progress": "#d97818",
            "error": "#c73e50",
            "success": "#2f8a4d",
            "graph_background": "#d7dbe1",
            "grid_minor": "#ccd1d8",
            "grid_major": "#bac1ca",
            "node_body": "#f4f5f7",
            "node_body_bypassed": "#e4e7eb",
            "node_border": "#9ba4b0",
            "node_selected": "#225ca9",
            "node_active": "#2f6fca",
            "node_text": "#252a31",
            "node_text_muted": "#6b7480",
            "preview_background": "#cdd2d9",
            "checker_dark": "#c2c7ce",
            "checker_light": "#e2e5e9",
            "scrollbar_track": "#d3d7dd",
            "scrollbar_handle": "#8f98a5",
            "scrollbar_hover": "#6f7987",
        },
    },
}

_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
_ACTIVE_THEME: dict[str, Any] = deepcopy(BUILTIN_THEMES[DEFAULT_THEME_ID])


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return cleaned or "custom-theme"


def normalise_theme(data: Mapping[str, Any], *, fallback_id: str = DEFAULT_THEME_ID) -> dict[str, Any]:
    if fallback_id not in BUILTIN_THEMES:
        fallback_id = DEFAULT_THEME_ID
    requested_base = str(data.get("base", fallback_id))
    base_id = requested_base if requested_base in BUILTIN_THEMES else fallback_id
    base = deepcopy(BUILTIN_THEMES[base_id])
    theme_id = _safe_identifier(str(data.get("id", data.get("name", "custom-theme"))))
    base["id"] = theme_id
    base["name"] = str(data.get("name", theme_id.replace("-", " ").title())).strip() or theme_id
    base["base"] = base_id
    provided = data.get("colors", {})
    if isinstance(provided, Mapping):
        for key, value in provided.items():
            colour = str(value).strip()
            if key in base["colors"] and _HEX_COLOUR.fullmatch(colour):
                base["colors"][str(key)] = colour
    return base


def load_custom_themes(directory: Path) -> dict[str, dict[str, Any]]:
    themes: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return themes
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                continue
            theme = normalise_theme(raw)
            theme["source_path"] = str(path)
            themes[theme["id"]] = theme
        except Exception:
            continue
    return themes


def resolve_theme(theme_id: str, custom_directory: Path | None = None) -> dict[str, Any]:
    theme_id = str(theme_id or DEFAULT_THEME_ID)
    if theme_id in BUILTIN_THEMES:
        return deepcopy(BUILTIN_THEMES[theme_id])
    if custom_directory is not None:
        custom = load_custom_themes(custom_directory)
        if theme_id in custom:
            return custom[theme_id]
    return deepcopy(BUILTIN_THEMES[DEFAULT_THEME_ID])


def set_active_theme(theme: Mapping[str, Any]) -> dict[str, Any]:
    global _ACTIVE_THEME
    _ACTIVE_THEME = normalise_theme(theme, fallback_id=str(theme.get("base", DEFAULT_THEME_ID)))
    _ACTIVE_THEME["id"] = str(theme.get("id", _ACTIVE_THEME["id"]))
    _ACTIVE_THEME["name"] = str(theme.get("name", _ACTIVE_THEME["name"]))
    if "source_path" in theme:
        _ACTIVE_THEME["source_path"] = str(theme["source_path"])
    return deepcopy(_ACTIVE_THEME)


def active_theme() -> dict[str, Any]:
    return deepcopy(_ACTIVE_THEME)


def theme_colour(name: str, fallback: str = "#ff00ff") -> str:
    return str(_ACTIVE_THEME.get("colors", {}).get(name, fallback))


def theme_to_json(theme: Mapping[str, Any]) -> dict[str, Any]:
    normalised = normalise_theme(theme, fallback_id=str(theme.get("base", DEFAULT_THEME_ID)))
    return {
        "id": normalised["id"],
        "name": normalised["name"],
        "base": normalised["base"],
        "colors": normalised["colors"],
    }


def build_stylesheet(theme: Mapping[str, Any]) -> str:
    colours = normalise_theme(theme, fallback_id=str(theme.get("base", DEFAULT_THEME_ID)))["colors"]
    return rf"""
* {{
    font-family: "Inter", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 10pt;
}}
QMainWindow, QWidget {{
    background: {colours['window']};
    color: {colours['text']};
}}
QMenuBar {{
    background: {colours['panel']};
    border-bottom: 1px solid {colours['border']};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background: {colours['selection']};
}}
QMenu {{
    background: {colours['panel']};
    border: 1px solid {colours['border']};
    padding: 5px;
}}
QToolBar {{
    background: {colours['panel']};
    border: none;
    border-bottom: 1px solid {colours['border']};
    spacing: 7px;
    padding: 5px 8px;
}}
QDockWidget {{
    color: {colours['text']};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {colours['panel']};
    border-bottom: 1px solid {colours['border']};
    padding: 7px 9px;
    text-align: left;
    font-weight: 600;
}}
QTabBar::tab {{
    background: {colours['panel']};
    border: 1px solid {colours['border']};
    border-bottom: none;
    padding: 7px 12px;
    margin-right: 1px;
    color: {colours['text_muted']};
}}
QTabBar::tab:selected {{
    background: {colours['panel_selected']};
    color: {colours['text']};
    border-color: {colours['border_strong']};
}}
QTabBar::tab:hover:!selected {{
    background: {colours['button_hover']};
    color: {colours['text']};
}}
QTabBar::tab:first {{ border-top-left-radius: 4px; }}
QTabBar::tab:last {{ border-top-right-radius: 4px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {colours['input']};
    color: {colours['text']};
    border: 1px solid {colours['border']};
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: {colours['accent']};
    selection-color: {colours['text_inverse']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {colours['accent']};
}}
QComboBox QAbstractItemView {{
    background: {colours['panel']};
    color: {colours['text']};
    selection-background-color: {colours['selection']};
}}
QPushButton, QToolButton {{
    background: {colours['button']};
    color: {colours['text']};
    border: 1px solid {colours['border']};
    border-radius: 5px;
    padding: 5px 9px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {colours['button_hover']};
    border-color: {colours['border_strong']};
}}
QPushButton:pressed, QToolButton:pressed {{ background: {colours['button_pressed']}; }}
QToolButton:checked {{
    background: {colours['accent']};
    border-color: {colours['accent_hover']};
    color: {colours['text_inverse']};
}}
QToolButton#parameterGroupHeader {{
    background: {colours['panel']};
    border: 1px solid {colours['border']};
    border-radius: 4px;
    padding: 5px 8px;
    font-weight: 650;
    text-align: left;
    color: {colours['text']};
}}
QToolButton#parameterGroupHeader:hover {{
    background: {colours['button_hover']};
    border-color: {colours['border_strong']};
}}
QFrame#parameterGroupBody {{ background: transparent; border: none; }}
QTreeWidget, QListWidget, QScrollArea, QTableWidget {{
    background: {colours['panel_alt']};
    color: {colours['text']};
    border: none;
    outline: none;
    alternate-background-color: {colours['panel']};
}}
QTreeWidget::item, QListWidget::item {{ padding: 5px; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
    background: {colours['selection']};
    color: {colours['text']};
}}
QHeaderView::section {{
    background: {colours['panel']};
    color: {colours['text']};
    border: none;
    border-bottom: 1px solid {colours['border']};
    padding: 6px;
}}
QProgressBar {{
    background: {colours['panel_alt']};
    border: 1px solid {colours['border']};
    border-radius: 4px;
    min-height: 13px;
    text-align: center;
    color: {colours['text']};
}}
QProgressBar::chunk {{ background: {colours['progress']}; border-radius: 3px; }}
QSlider::groove:horizontal {{
    height: 4px;
    background: {colours['border']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 13px;
    margin: -5px 0;
    background: {colours['accent']};
    border-radius: 6px;
}}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 650; color: {colours['text']}; }}
QLabel#muted {{ color: {colours['text_muted']}; }}
QLabel#warningText {{ color: {colours['error']}; }}
QLabel#assetThumbnail {{ background: {colours['preview_background']}; border: 1px solid {colours['border']}; border-radius: 5px; color: {colours['text_muted']}; }}
QLabel#evaluationState {{ color: {colours['progress']}; font-weight: 700; }}
QStatusBar {{
    background: {colours['panel']};
    border-top: 1px solid {colours['border']};
    color: {colours['text_muted']};
}}
QSplitter::handle {{ background: {colours['border']}; }}
QScrollBar:vertical {{
    background: {colours['scrollbar_track']};
    width: 13px;
    margin: 1px;
}}
QScrollBar::handle:vertical {{
    background: {colours['scrollbar_handle']};
    min-height: 28px;
    border-radius: 5px;
    margin: 1px;
}}
QScrollBar::handle:vertical:hover {{ background: {colours['scrollbar_hover']}; }}
QScrollBar:horizontal {{
    background: {colours['scrollbar_track']};
    height: 13px;
    margin: 1px;
}}
QScrollBar::handle:horizontal {{
    background: {colours['scrollbar_handle']};
    min-width: 28px;
    border-radius: 5px;
    margin: 1px;
}}
QScrollBar::handle:horizontal:hover {{ background: {colours['scrollbar_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{
    background: {colours['panel_selected']};
    color: {colours['text']};
    border: 1px solid {colours['border_strong']};
    padding: 4px;
}}
"""


APP_STYLESHEET = build_stylesheet(BUILTIN_THEMES[DEFAULT_THEME_ID])
