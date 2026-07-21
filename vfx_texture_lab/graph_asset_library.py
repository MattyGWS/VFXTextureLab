from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QStandardPaths

from .graph_assets import parse_graph_asset_interface


def default_graph_asset_directory() -> Path:
    root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    path = root / "graph_assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _custom_library_graph_asset_directories(settings: QSettings) -> list[Path]:
    """Return enabled Custom Library roots that may also contain .vfxgraph assets.

    Custom node packages and reusable graphs are both author libraries from the
    user's point of view.  Keeping the underlying package and graph scanners
    separate is useful, but a folder registered through Library -> Custom
    Libraries should be discoverable by both scanners.
    """
    raw = settings.value("custom_nodes/library_locations", "[]")
    try:
        entries = json.loads(str(raw)) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        entries = []
    result: list[Path] = []
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict) or not bool(entry.get("enabled", True)):
            continue
        value = str(entry.get("path", "")).strip()
        if value:
            result.append(Path(value).expanduser())
    return result


def graph_asset_directories(settings: QSettings | None = None) -> list[Path]:
    settings = settings or QSettings()
    raw = settings.value("graph_assets/directories", [], list) or []
    candidates = [
        default_graph_asset_directory(),
        *(Path(str(value)).expanduser() for value in raw if str(value)),
        *_custom_library_graph_asset_directories(settings),
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_dir():
            result.append(resolved)
    return result


def add_graph_asset_directory(path: str | Path, settings: QSettings | None = None) -> bool:
    settings = settings or QSettings()
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        return False
    existing = [str(item) for item in graph_asset_directories(settings) if item != default_graph_asset_directory()]
    if str(target) not in existing:
        existing.append(str(target))
        settings.setValue("graph_assets/directories", existing)
    return True


def remove_graph_asset_directory(path: str | Path, settings: QSettings | None = None) -> None:
    settings = settings or QSettings()
    target = str(Path(path).expanduser().resolve())
    existing = [
        str(item)
        for item in graph_asset_directories(settings)
        if item != default_graph_asset_directory() and str(item) != target
    ]
    settings.setValue("graph_assets/directories", existing)


def _metadata_fallback(data: Any, path: Path) -> dict[str, Any]:
    graph_asset = data.get("graph_asset", {}) if isinstance(data, dict) else {}
    graph_asset = graph_asset if isinstance(graph_asset, dict) else {}
    tags = graph_asset.get("tags", ())
    if isinstance(tags, str):
        tags = [value.strip() for value in tags.split(",") if value.strip()]
    return {
        "name": str(graph_asset.get("name") or path.stem),
        "description": str(graph_asset.get("description") or "Graph asset could not be validated."),
        "category": str(graph_asset.get("category") or "Graph Assets"),
        "tags": [str(value).strip() for value in tags or () if str(value).strip()],
        "author": str(graph_asset.get("author") or ""),
        "asset_version": str(graph_asset.get("version") or "1.0.0"),
        "created_with": str(graph_asset.get("created_with") or ""),
        "asset_id": str(graph_asset.get("asset_id") or path),
        "thumbnail_png": str(graph_asset.get("thumbnail_png") or ""),
        "thumbnail_source": str(graph_asset.get("thumbnail_source") or ""),
        "inputs": [],
        "outputs": [],
        "parameters": [],
        "warnings": [],
    }


def inspect_graph_asset_file(path: str | Path, registry) -> tuple[Path, dict[str, Any]]:
    source = Path(path).expanduser().resolve()
    data: Any = None
    problems: list[str] = []
    fatal = False
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        interface = _metadata_fallback(data, source)
        problems.append(f"Could not read graph JSON: {exc}")
        fatal = True
    else:
        try:
            interface = parse_graph_asset_interface(data, registry, source_path=source)
        except Exception as exc:
            interface = _metadata_fallback(data, source)
            problems.append(str(exc))
            fatal = True
        else:
            problems.extend(str(value) for value in interface.get("warnings", ()) if str(value))
            if not interface.get("outputs"):
                problems.append("No connected Graph Output nodes are available for use as a Graph Instance.")
                fatal = True

    interface = dict(interface)
    interface["valid"] = not fatal
    interface["has_warnings"] = bool(problems) and not fatal
    interface["problems"] = problems
    interface["source_path"] = str(source)
    return source, interface


def load_graph_asset_files(
    registry,
    settings: QSettings | None = None,
    *,
    include_invalid: bool = False,
) -> list[tuple[Path, dict[str, Any]]]:
    assets: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for directory in graph_asset_directories(settings):
        for path in sorted(directory.rglob("*.vfxgraph"), key=lambda item: str(item).casefold()):
            try:
                resolved = path.resolve()
            except Exception:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            resolved, interface = inspect_graph_asset_file(resolved, registry)
            if bool(interface.get("valid")) or include_invalid:
                assets.append((resolved, interface))
    return assets
