from __future__ import annotations

"""Shareable and user-installed export templates.

`.vfxexport` files are versioned JSON documents containing one ExportTemplate.
Installed templates live in the application's data directory and are copied,
never linked, so removing the downloaded file cannot break graphs or profiles.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import re
import shutil
import tempfile
import uuid

from PySide6.QtCore import QStandardPaths

from .export_templates import ExportTemplate, validate_export_template

VFXEXPORT_FORMAT = "vfx-texture-lab-export-template"
VFXEXPORT_VERSION = 1
VFXEXPORT_EXTENSION = ".vfxexport"


class ExportTemplateLibraryError(ValueError):
    pass


def export_template_directory() -> Path:
    root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    path = root / "export_templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(value: str, fallback: str = "export-template") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text or fallback


def _normalised_template(template: ExportTemplate, *, preserve_id: bool = True) -> ExportTemplate:
    data = template.to_dict()
    template_id = str(data.get("template_id") or "").strip()
    if not preserve_id or not template_id or template_id in {"custom", "installed"}:
        template_id = f"template.{uuid.uuid4().hex}"
    data["template_id"] = template_id
    data["format"] = VFXEXPORT_FORMAT
    data["version"] = VFXEXPORT_VERSION
    return ExportTemplate.from_dict(data)


def write_vfxexport(path: str | Path, template: ExportTemplate) -> Path:
    target = Path(path).expanduser()
    if target.suffix.lower() != VFXEXPORT_EXTENSION:
        target = target.with_suffix(VFXEXPORT_EXTENSION)
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    template = _normalised_template(template)
    errors, _warnings = validate_export_template(template)
    if errors:
        raise ExportTemplateLibraryError("Template is invalid:\n" + "\n".join(errors))
    payload = template.to_dict()
    payload["format"] = VFXEXPORT_FORMAT
    payload["version"] = VFXEXPORT_VERSION
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # Read it back through the public parser before replacing the destination.
    read_vfxexport(temporary)
    temporary.replace(target)
    return target


def read_vfxexport(path: str | Path) -> ExportTemplate:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ExportTemplateLibraryError(f"Export template could not be found:\n{source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ExportTemplateLibraryError(f"Could not read export template: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ExportTemplateLibraryError("Export template must be a JSON object.")
    if str(raw.get("format") or "") != VFXEXPORT_FORMAT:
        raise ExportTemplateLibraryError("This file is not a VFX Texture Lab export template.")
    version = int(raw.get("version", 0) or 0)
    if version != VFXEXPORT_VERSION:
        raise ExportTemplateLibraryError(
            f"Unsupported export-template format version {version}; this build supports version {VFXEXPORT_VERSION}."
        )
    template = ExportTemplate.from_dict(raw)
    if not template.template_id or template.template_id in {"custom", "installed"}:
        data = template.to_dict()
        data["template_id"] = f"template.{uuid.uuid4().hex}"
        template = ExportTemplate.from_dict(data)
    errors, _warnings = validate_export_template(template)
    if errors:
        raise ExportTemplateLibraryError("Template is invalid:\n" + "\n".join(errors))
    return template


@dataclass(frozen=True, slots=True)
class InstalledExportTemplate:
    path: Path
    template: ExportTemplate


def installed_export_templates() -> tuple[InstalledExportTemplate, ...]:
    root = export_template_directory()
    result: list[InstalledExportTemplate] = []
    for path in sorted(root.glob(f"*{VFXEXPORT_EXTENSION}"), key=lambda p: p.name.casefold()):
        try:
            result.append(InstalledExportTemplate(path, read_vfxexport(path)))
        except ExportTemplateLibraryError:
            continue
    return tuple(result)


def installed_template_names() -> tuple[str, ...]:
    return tuple(entry.template.name for entry in installed_export_templates())


def installed_template(name_or_id: str) -> ExportTemplate | None:
    key = str(name_or_id or "").strip().casefold()
    for entry in installed_export_templates():
        if entry.template.name.casefold() == key or entry.template.template_id.casefold() == key:
            return entry.template
    return None


def install_vfxexport(
    source: str | Path,
    *,
    conflict: str = "ask",
) -> tuple[Path, ExportTemplate, str]:
    """Install a template. conflict is update, side-by-side, or reject/ask."""
    incoming = read_vfxexport(source)
    root = export_template_directory()
    same_id = [entry for entry in installed_export_templates() if entry.template.template_id == incoming.template_id]
    action = "installed"
    if same_id:
        if conflict == "update":
            target = same_id[0].path
            action = "updated"
        elif conflict == "side-by-side":
            data = incoming.to_dict()
            data["template_id"] = f"template.{uuid.uuid4().hex}"
            data["name"] = f"{incoming.name} ({incoming.asset_version})"
            incoming = ExportTemplate.from_dict(data)
            target = root / f"{_slug(incoming.name)}-{incoming.template_id[-8:]}{VFXEXPORT_EXTENSION}"
            action = "side-by-side"
        else:
            raise ExportTemplateLibraryError(
                f"An installed template with ID {incoming.template_id} already exists."
            )
    else:
        base = root / f"{_slug(incoming.name)}{VFXEXPORT_EXTENSION}"
        target = base
        index = 2
        while target.exists():
            try:
                existing = read_vfxexport(target)
                if existing.template_id == incoming.template_id:
                    break
            except ExportTemplateLibraryError:
                pass
            target = root / f"{_slug(incoming.name)}-{index}{VFXEXPORT_EXTENSION}"
            index += 1
    write_vfxexport(target, incoming)
    return target, incoming, action


def install_template_object(
    template: ExportTemplate,
    *,
    conflict: str = "reject",
) -> tuple[Path, ExportTemplate, str]:
    with tempfile.TemporaryDirectory(prefix="vfxtl-export-template-") as temp_dir:
        source = Path(temp_dir) / f"template{VFXEXPORT_EXTENSION}"
        write_vfxexport(source, template)
        return install_vfxexport(source, conflict=conflict)


def remove_installed_template(template_id: str) -> bool:
    for entry in installed_export_templates():
        if entry.template.template_id == template_id:
            entry.path.unlink(missing_ok=True)
            return True
    return False
