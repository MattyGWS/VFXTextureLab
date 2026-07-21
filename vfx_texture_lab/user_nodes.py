from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths


def user_node_directory() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base) / "user_nodes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify_node_name(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._")
    return text or "user_node"


def load_user_node_files() -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(user_node_directory().glob("*.vfxnode"), key=lambda p: p.name.lower()):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("format") != "vfx-texture-lab-user-node":
            continue
        result.append((path, data))
    return result
