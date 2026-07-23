from __future__ import annotations

import base64
import hashlib
import json
import posixpath
import re
import shutil
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .graph_assets import GRAPH_ASSET_FORMAT
from .export_templates import ExportTemplate, validate_export_template
from .portable_graph import (
    SelfContainedExportReport,
    SelfContainedGraphError,
    build_self_contained_graph,
    validate_self_contained_graph,
)

PACKAGE_FORMAT = "vfx-texture-lab-package"
PACKAGE_FORMAT_VERSION = 1
PACKAGE_MANIFEST = "package.vfxmanifest"
PACKAGE_EXTENSION = ".vfxpackage"
MAX_PACKAGE_MEMBERS = 4096
MAX_PACKAGE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_PACKAGE_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


class VFXPackageError(ValueError):
    """Raised when a .vfxpackage is malformed, unsafe, or incomplete."""


@dataclass(slots=True, frozen=True)
class PackageFile:
    path: str
    kind: str
    size: int
    sha256: str


@dataclass(slots=True)
class VFXPackageInfo:
    source_path: Path
    package_id: str
    asset_id: str
    name: str
    description: str
    category: str
    tags: list[str]
    author: str
    asset_version: str
    created_with: str
    created_at: str
    entry_graph: str
    thumbnail_path: str
    files: list[PackageFile] = field(default_factory=list)
    custom_nodes: list[dict[str, Any]] = field(default_factory=list)
    image_sources: list[dict[str, Any]] = field(default_factory=list)
    mesh_sources: list[dict[str, Any]] = field(default_factory=list)
    export_templates: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def total_size(self) -> int:
        return sum(int(entry.size) for entry in self.files)

    def summary_lines(self) -> list[str]:
        lines = [
            f"Name: {self.name}",
            f"Version: {self.asset_version}",
            f"Author: {self.author or 'Unknown'}",
            f"Asset ID: {self.asset_id}",
            f"Created with: {self.created_with or 'Unknown'}",
            f"Files: {len(self.files)} · {self.total_size / 1024.0:.1f} KiB",
        ]
        if self.custom_nodes:
            lines.append(f"Bundled custom nodes: {len(self.custom_nodes)}")
        if self.image_sources:
            lines.append(f"Included image source files: {len(self.image_sources)}")
        if self.mesh_sources:
            lines.append(f"Included mesh source files: {len(self.mesh_sources)}")
        if self.export_templates:
            lines.append(f"Included export templates: {len(self.export_templates)}")
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.tags:
            lines.append("Tags: " + ", ".join(self.tags))
        return lines


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_slug(value: str, fallback: str = "graph-asset") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text or fallback


def _safe_member_path(value: str) -> PurePosixPath:
    text = str(value or "")
    if not text or "\x00" in text or "\\" in text:
        raise VFXPackageError(f"Unsafe package path: {value!r}")
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts:
        raise VFXPackageError(f"Unsafe package path: {value!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise VFXPackageError(f"Package path escapes its root: {value!r}")
    if ":" in path.parts[0]:
        raise VFXPackageError(f"Drive-qualified package path is not allowed: {value!r}")
    return path


def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _normalise_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = ()
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _graph_metadata(graph: Mapping[str, Any]) -> dict[str, Any]:
    metadata = graph.get("graph_asset")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return {
        "asset_id": str(metadata.get("asset_id") or "").strip(),
        "name": str(metadata.get("name") or "Graph Asset").strip() or "Graph Asset",
        "description": str(metadata.get("description") or "").strip(),
        "category": str(metadata.get("category") or "Graph Assets").strip() or "Graph Assets",
        "tags": _normalise_tags(metadata.get("tags", ())),
        "author": str(metadata.get("author") or "").strip(),
        "version": str(metadata.get("version") or "1.0.0").strip() or "1.0.0",
        "created_with": str(metadata.get("created_with") or "").strip(),
        "thumbnail_png": str(metadata.get("thumbnail_png") or "").strip(),
    }


def _decode_thumbnail(encoded: str) -> bytes | None:
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise VFXPackageError("The graph thumbnail is damaged and cannot be packaged.") from exc
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VFXPackageError("The stored graph thumbnail is not a valid PNG.")
    return raw


def _image_suffix(name: str, payload: bytes) -> str:
    suffix = Path(str(name or "")).suffix.lower()
    if suffix in {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".tif", ".tiff",
    }:
        return suffix
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith(b"BM"):
        return ".bmp"
    if payload[:4] in {b"II*\x00", b"MM\x00*"}:
        return ".tif"
    return ".image"


def _mesh_suffix(_name: str, _payload: bytes) -> str:
    # Mesh Input currently supports Wavefront OBJ only.
    return ".obj"


def _collect_packaged_resource_sources(
    graph: dict[str, Any],
    *,
    entry_graph: str,
    node_type: str,
    resource_directory: str,
    file_kind: str,
    default_name: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    """Write exact embedded Image Input or Mesh Input bytes as package files."""

    records_by_hash: dict[str, dict[str, Any]] = {}
    archive_path_hashes: dict[str, str] = {}
    payloads: list[tuple[str, str, bytes]] = []
    entry_parent = str(PurePosixPath(entry_graph).parent)
    is_mesh = node_type == "input.mesh"

    def allocate_path(name: str, payload_hash: str, payload: bytes) -> str:
        suffix = _mesh_suffix(name, payload) if is_mesh else _image_suffix(name, payload)
        stem = _safe_slug(Path(str(name or default_name)).stem, default_name)
        candidate = f"resources/{resource_directory}/{stem}{suffix}"
        existing = archive_path_hashes.get(candidate)
        if existing is not None and existing != payload_hash:
            candidate = f"resources/{resource_directory}/{stem}_{payload_hash[:8]}{suffix}"
        counter = 2
        while candidate in archive_path_hashes and archive_path_hashes[candidate] != payload_hash:
            candidate = f"resources/{resource_directory}/{stem}_{payload_hash[:8]}_{counter}{suffix}"
            counter += 1
        archive_path_hashes[candidate] = payload_hash
        return candidate

    def walk(current: Mapping[str, Any], chain: list[str], depth: int) -> None:
        if depth > 64:
            raise VFXPackageError("Graph nesting exceeded the package safety limit.")
        graph_name = _graph_label_for_package(current, chain[-1] if chain else "Graph")
        resource_by_id: dict[str, Mapping[str, Any]] = {}
        resource_library = current.get("resources")
        if isinstance(resource_library, Mapping):
            resource_items = resource_library.get("items", resource_library.get("resources", ()))
            if isinstance(resource_items, (list, tuple)):
                resource_by_id = {
                    str(item.get("uid", "")): item
                    for item in resource_items
                    if isinstance(item, Mapping) and str(item.get("uid", ""))
                }
        for node in current.get("nodes", ()):
            if not isinstance(node, dict):
                continue
            parameters = node.get("parameters")
            if not isinstance(parameters, dict):
                continue
            type_id = str(node.get("type", ""))
            node_name = str(parameters.get("name") or type_id or "Node")
            if type_id == node_type:
                resource = resource_by_id.get(str(parameters.get("_resource_id", "") or ""))
                encoded = str(
                    parameters.get("_embedded_data", "")
                    or (resource.get("embedded_data", "") if resource else "")
                    or ""
                ).strip()
                label = "Mesh Input" if is_mesh else "Image Input"
                if not encoded:
                    raise VFXPackageError(
                        f"{label} '{node_name}' has no embedded bytes to preserve as a source file."
                    )
                try:
                    payload = base64.b64decode(encoded, validate=True)
                except Exception as exc:
                    raise VFXPackageError(
                        f"{label} '{node_name}' contains damaged embedded source data."
                    ) from exc
                payload_hash = _sha256(payload)
                original_name = str(
                    parameters.get("_embedded_original_name")
                    or parameters.get("_embedded_name")
                    or (resource.get("original_name") if resource else "")
                    or (resource.get("embedded_name") if resource else "")
                    or (resource.get("name") if resource else "")
                    or default_name
                ).strip() or default_name
                record = records_by_hash.get(payload_hash)
                if record is None:
                    member_path = allocate_path(original_name, payload_hash, payload)
                    record = {
                        "path": member_path,
                        "original_name": Path(original_name).name,
                        "size": len(payload),
                        "sha256": payload_hash,
                        "uses": [],
                    }
                    records_by_hash[payload_hash] = record
                    payloads.append((member_path, file_kind, payload))
                relative = posixpath.relpath(str(record["path"]), start=entry_parent)
                parameters["_packaged_source_path"] = relative
                parameters["_packaged_source_sha256"] = payload_hash
                record["uses"].append(
                    {
                        "graph": graph_name,
                        "node_uid": str(node.get("uid") or ""),
                        "node_name": node_name,
                    }
                )
            elif type_id == "graph.instance":
                child = parameters.get("_asset_embedded_graph")
                if isinstance(child, dict):
                    child_name = _graph_label_for_package(child, node_name)
                    walk(child, [*chain, child_name], depth + 1)

    walk(graph, [_graph_label_for_package(graph, "Graph")], 0)
    records = sorted(records_by_hash.values(), key=lambda item: str(item["path"]).casefold())
    payloads.sort(key=lambda item: item[0].casefold())
    return records, payloads


def _collect_packaged_image_sources(
    graph: dict[str, Any],
    *,
    entry_graph: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    """Write exact imported image bytes as package resources.

    The entry graph remains self-contained so it can be opened directly from
    the archive.  These files preserve artist-editable source images for
    extraction, inspection and later relinking.
    """

    return _collect_packaged_resource_sources(
        graph,
        entry_graph=entry_graph,
        node_type="input.image",
        resource_directory="images",
        file_kind="image-source",
        default_name="image",
    )


def _collect_packaged_mesh_sources(
    graph: dict[str, Any],
    *,
    entry_graph: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    return _collect_packaged_resource_sources(
        graph,
        entry_graph=entry_graph,
        node_type="input.mesh",
        resource_directory="meshes",
        file_kind="mesh-source",
        default_name="mesh.obj",
    )


def _graph_label_for_package(data: Mapping[str, Any], fallback: str) -> str:
    metadata = data.get("graph_asset")
    if isinstance(metadata, Mapping):
        name = str(metadata.get("name") or "").strip()
        if name:
            return name
    return str(fallback or "Graph")



def _walk_graph_nodes(graph: Mapping[str, Any], *, depth: int = 0):
    if depth > 64:
        raise VFXPackageError("Graph nesting exceeded the package safety limit.")
    for node in graph.get("nodes", ()):
        if not isinstance(node, Mapping):
            continue
        yield node
        if str(node.get("type", "")) == "graph.instance":
            parameters = node.get("parameters", {})
            child = parameters.get("_asset_embedded_graph") if isinstance(parameters, Mapping) else None
            if isinstance(child, Mapping):
                yield from _walk_graph_nodes(child, depth=depth + 1)


def _collect_custom_node_packages(graph: Mapping[str, Any], registry) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    records: dict[str, dict[str, Any]] = {}
    file_payloads: list[tuple[str, str, bytes]] = []
    seen_archive_paths: set[str] = set()
    for node in _walk_graph_nodes(graph):
        type_id = str(node.get("type", ""))
        snapshot = node.get("definition", {})
        package_version = str(snapshot.get("package_version") or "") if isinstance(snapshot, Mapping) else ""
        if not package_version:
            continue
        if registry is None:
            raise VFXPackageError(
                f"Node '{type_id}' belongs to a node package, but no registry was provided to collect it."
            )
        definition = registry.get_optional(type_id)
        if definition is None or definition.package is None:
            raise VFXPackageError(
                f"Custom node dependency '{type_id}' is not currently installed and cannot be packaged."
            )
        package = definition.package
        if package.source_kind == "bundled":
            continue
        existing = records.get(package.package_id)
        if existing is not None:
            if str(existing.get("revision")) != str(package.revision):
                raise VFXPackageError(
                    f"Two different revisions of custom node '{package.package_id}' are used by this graph."
                )
            continue
        root = Path(package.root).expanduser().resolve()
        if not root.is_dir():
            raise VFXPackageError(
                f"Custom node source folder is missing for '{package.package_id}':\n{root}"
            )
        archive_root = f"custom_nodes/{_safe_slug(package.package_id, 'custom-node')}-{hashlib.sha256(package.package_id.encode('utf-8')).hexdigest()[:8]}"
        package_files: list[str] = []
        for source_file in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
            if source_file.is_symlink():
                raise VFXPackageError(
                    f"Custom node package contains a symbolic link, which cannot be bundled: {source_file}"
                )
            if not source_file.is_file():
                continue
            relative = source_file.relative_to(root)
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise VFXPackageError(f"Unsafe custom node file path: {relative}")
            member = str(PurePosixPath(archive_root, *relative.parts))
            _safe_member_path(member)
            if member in seen_archive_paths:
                raise VFXPackageError(f"Duplicate packaged custom node file: {member}")
            payload = source_file.read_bytes()
            if len(payload) > MAX_PACKAGE_FILE_BYTES:
                raise VFXPackageError(f"Custom node file is too large to package: {source_file}")
            seen_archive_paths.add(member)
            package_files.append(member)
            file_payloads.append((member, "custom-node", payload))
        manifest_member = str(PurePosixPath(archive_root, "node.toml"))
        manifests = [path for path in package_files if PurePosixPath(path).name == "node.toml"]
        if manifest_member not in package_files or len(manifests) != 1:
            raise VFXPackageError(
                f"Custom node package '{package.package_id}' must contain exactly one root node.toml."
            )
        records[package.package_id] = {
            "package_id": package.package_id,
            "name": definition.name,
            "version": package.version,
            "api_version": package.api_version,
            "revision": package.revision,
            "root": archive_root,
            "files": package_files,
        }
    return list(records.values()), file_payloads



def _collect_graph_export_templates(graph: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    """Collect graph-local template snapshots as independently installable files."""
    found: dict[str, ExportTemplate] = {}

    def add(raw: Any) -> None:
        if not isinstance(raw, Mapping):
            return
        template = ExportTemplate.from_dict(raw)
        if not template.files:
            return
        errors, _warnings = validate_export_template(template)
        if errors:
            raise VFXPackageError(
                f"Export template '{template.name}' is invalid: " + "; ".join(errors)
            )
        key = template.template_id or _sha256(
            json.dumps(template.to_dict(), sort_keys=True).encode("utf-8")
        )
        found.setdefault(key, template)

    def walk(current: Mapping[str, Any], depth: int = 0) -> None:
        if depth > 64:
            raise VFXPackageError("Graph nesting exceeded the package safety limit.")
        for node in current.get("nodes", ()):
            if not isinstance(node, Mapping):
                continue
            parameters = node.get("parameters")
            if not isinstance(parameters, Mapping):
                continue
            add(parameters.get("_custom_export_template"))
            embedded = parameters.get("_embedded_graph")
            if isinstance(embedded, Mapping):
                walk(embedded, depth + 1)
        profiles = current.get("export_profiles")
        if isinstance(profiles, Mapping):
            for profile in profiles.get("profiles", ()):
                if not isinstance(profile, Mapping):
                    continue
                for target in profile.get("targets", ()):
                    if isinstance(target, Mapping):
                        add(target.get("custom_template"))

    walk(graph)
    records: list[dict[str, Any]] = []
    files: list[tuple[str, str, bytes]] = []
    used_paths: set[str] = set()
    for key, template in sorted(found.items(), key=lambda item: item[1].name.casefold()):
        stem = _safe_slug(template.name, "export-template")
        path = f"export_templates/{stem}.vfxexport"
        if path in used_paths:
            path = f"export_templates/{stem}-{_sha256(key.encode())[:8]}.vfxexport"
        used_paths.add(path)
        payload_dict = template.to_dict()
        payload_dict["format"] = "vfx-texture-lab-export-template"
        payload_dict["version"] = 1
        payload = json.dumps(payload_dict, indent=2, ensure_ascii=False).encode("utf-8")
        files.append((path, "export-template", payload))
        records.append({
            "path": path,
            "template_id": template.template_id,
            "name": template.name,
            "author": template.author,
            "version": template.asset_version,
            "target": template.target,
            "sha256": _sha256(payload),
        })
    return records, files

def create_vfxpackage(
    destination: str | Path,
    graph_data: Mapping[str, Any],
    *,
    owner_path: str | Path | None = None,
    app_version: str = "",
    registry=None,
    include_image_sources: bool = True,
    include_mesh_sources: bool = True,
    include_export_templates: bool = True,
) -> tuple[VFXPackageInfo, SelfContainedExportReport]:
    """Create and validate a .vfxpackage without modifying the source graph."""

    target = Path(destination).expanduser()
    if target.suffix.lower() != PACKAGE_EXTENSION:
        target = target.with_suffix(PACKAGE_EXTENSION)
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    portable, report = build_self_contained_graph(
        graph_data, owner_path=owner_path, app_version=app_version
    )
    validate_self_contained_graph(portable)
    metadata = _graph_metadata(portable)
    if not metadata["asset_id"]:
        raise VFXPackageError("The graph has no stable Asset ID.")

    graph_name = _safe_slug(metadata["name"], "graph-asset") + ".vfxgraph"
    entry_graph = f"graphs/{graph_name}"
    image_sources: list[dict[str, Any]] = []
    image_source_files: list[tuple[str, str, bytes]] = []
    if include_image_sources:
        image_sources, image_source_files = _collect_packaged_image_sources(
            portable, entry_graph=entry_graph
        )
    mesh_sources: list[dict[str, Any]] = []
    mesh_source_files: list[tuple[str, str, bytes]] = []
    if include_mesh_sources:
        mesh_sources, mesh_source_files = _collect_packaged_mesh_sources(
            portable, entry_graph=entry_graph
        )
    graph_bytes = json.dumps(portable, indent=2, ensure_ascii=False).encode("utf-8")
    files: list[tuple[str, str, bytes]] = [(entry_graph, "graph", graph_bytes)]
    files.extend(image_source_files)
    files.extend(mesh_source_files)
    export_templates: list[dict[str, Any]] = []
    if include_export_templates:
        export_templates, export_template_files = _collect_graph_export_templates(portable)
        files.extend(export_template_files)
    custom_nodes, custom_node_files = _collect_custom_node_packages(portable, registry)
    files.extend(custom_node_files)

    thumbnail_bytes = _decode_thumbnail(metadata["thumbnail_png"])
    thumbnail_path = ""
    if thumbnail_bytes is not None:
        thumbnail_path = "thumbnail.png"
        files.append((thumbnail_path, "thumbnail", thumbnail_bytes))

    file_entries = [
        {
            "path": path,
            "kind": kind,
            "size": len(payload),
            "sha256": _sha256(payload),
        }
        for path, kind, payload in files
    ]
    manifest = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_FORMAT_VERSION,
        "created_with": str(app_version or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "package_id": metadata["asset_id"],
        "asset": {
            "asset_id": metadata["asset_id"],
            "name": metadata["name"],
            "description": metadata["description"],
            "category": metadata["category"],
            "tags": list(metadata["tags"]),
            "author": metadata["author"],
            "version": metadata["version"],
        },
        "entry_graph": entry_graph,
        "thumbnail": thumbnail_path,
        "portable_mode": "single-file",
        "image_source_mode": "included-with-embedded-fallback" if include_image_sources else "embedded-only",
        "image_sources": image_sources,
        "mesh_source_mode": "included-with-embedded-fallback" if include_mesh_sources else "embedded-only",
        "mesh_sources": mesh_sources,
        "export_templates": export_templates,
        "custom_nodes": custom_nodes,
        "files": file_entries,
    }
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")

    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.writestr(PACKAGE_MANIFEST, manifest_bytes)
            for member_path, _kind, payload in files:
                archive.writestr(member_path, payload)
        info = inspect_vfxpackage(temporary, validate_graph=True)
        temporary.replace(target)
        info.source_path = target
        return info, report
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = archive.getinfo(PACKAGE_MANIFEST)
    except KeyError as exc:
        raise VFXPackageError(f"Package is missing {PACKAGE_MANIFEST}.") from exc
    if info.file_size > MAX_MANIFEST_BYTES:
        raise VFXPackageError("Package manifest is unreasonably large.")
    try:
        payload = json.loads(archive.read(info).decode("utf-8"))
    except Exception as exc:
        raise VFXPackageError(f"Could not read package manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise VFXPackageError("Package manifest must be a JSON object.")
    return payload


def inspect_vfxpackage(
    source: str | Path,
    *,
    validate_graph: bool = True,
) -> VFXPackageInfo:
    """Validate a package's archive layout, hashes, manifest, and entry graph."""

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise VFXPackageError(f"Package could not be found:\n{path}")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise VFXPackageError(f"This is not a readable VFX package: {exc}") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_PACKAGE_MEMBERS:
            raise VFXPackageError("Package contains too many files.")
        seen: set[str] = set()
        total_size = 0
        actual_files: set[str] = set()
        for info in infos:
            name = info.filename
            _safe_member_path(name.rstrip("/")) if name.rstrip("/") else None
            if name in seen:
                raise VFXPackageError(f"Package contains a duplicate path: {name}")
            seen.add(name)
            if info.flag_bits & 0x1:
                raise VFXPackageError("Encrypted package members are not supported.")
            if _member_is_symlink(info):
                raise VFXPackageError(f"Symbolic links are not allowed in packages: {name}")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise VFXPackageError(f"Unsupported compression method for: {name}")
            if info.is_dir():
                continue
            if info.file_size > MAX_PACKAGE_FILE_BYTES:
                raise VFXPackageError(f"Package member is too large: {name}")
            total_size += int(info.file_size)
            if total_size > MAX_PACKAGE_UNCOMPRESSED_BYTES:
                raise VFXPackageError("Package expands beyond the supported size limit.")
            actual_files.add(name)

        manifest = _read_manifest(archive)
        if str(manifest.get("format", "")) != PACKAGE_FORMAT:
            raise VFXPackageError("Archive is not a VFX Texture Lab package.")
        version = int(manifest.get("version", 0) or 0)
        if version != PACKAGE_FORMAT_VERSION:
            raise VFXPackageError(
                f"Unsupported package format version {version}; this build supports version {PACKAGE_FORMAT_VERSION}."
            )

        entry_graph = str(manifest.get("entry_graph", "") or "")
        _safe_member_path(entry_graph)
        if not entry_graph.lower().endswith(".vfxgraph"):
            raise VFXPackageError("Package entry_graph must be a .vfxgraph file.")
        thumbnail_path = str(manifest.get("thumbnail", "") or "")
        if thumbnail_path:
            _safe_member_path(thumbnail_path)

        declared = manifest.get("files")
        if not isinstance(declared, list) or not declared:
            raise VFXPackageError("Package manifest has no file inventory.")
        files: list[PackageFile] = []
        declared_paths: set[str] = set()
        for entry in declared:
            if not isinstance(entry, Mapping):
                raise VFXPackageError("Package file inventory contains an invalid entry.")
            member_path = str(entry.get("path", "") or "")
            _safe_member_path(member_path)
            if member_path == PACKAGE_MANIFEST:
                raise VFXPackageError("The manifest must not inventory itself.")
            if member_path in declared_paths:
                raise VFXPackageError(f"Manifest lists a duplicate file: {member_path}")
            declared_paths.add(member_path)
            if member_path not in actual_files:
                raise VFXPackageError(f"Package is missing declared file: {member_path}")
            expected_size = int(entry.get("size", -1))
            expected_hash = str(entry.get("sha256", "") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise VFXPackageError(f"Manifest has an invalid SHA-256 for: {member_path}")
            hasher = hashlib.sha256()
            actual_size = 0
            try:
                with archive.open(member_path, "r") as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        actual_size += len(chunk)
                        if actual_size > MAX_PACKAGE_FILE_BYTES:
                            raise VFXPackageError(f"Package member is too large: {member_path}")
                        hasher.update(chunk)
            except VFXPackageError:
                raise
            except Exception as exc:
                raise VFXPackageError(f"Could not verify package file {member_path}: {exc}") from exc
            if actual_size != expected_size:
                raise VFXPackageError(f"Size mismatch for package file: {member_path}")
            if hasher.hexdigest() != expected_hash:
                raise VFXPackageError(f"Integrity check failed for package file: {member_path}")
            files.append(
                PackageFile(
                    path=member_path,
                    kind=str(entry.get("kind", "resource") or "resource"),
                    size=expected_size,
                    sha256=expected_hash,
                )
            )

        custom_nodes_raw = manifest.get("custom_nodes", ())
        if not isinstance(custom_nodes_raw, list):
            raise VFXPackageError("Package custom_nodes inventory must be a list.")
        custom_nodes: list[dict[str, Any]] = []
        custom_node_paths: set[str] = set()
        custom_node_ids: set[str] = set()
        for record in custom_nodes_raw:
            if not isinstance(record, Mapping):
                raise VFXPackageError("Package custom_nodes inventory contains an invalid entry.")
            package_id = str(record.get("package_id") or "").strip()
            root_text = str(record.get("root") or "").strip()
            if not package_id or package_id in custom_node_ids:
                raise VFXPackageError("Bundled custom node package IDs must be non-empty and unique.")
            custom_node_ids.add(package_id)
            root_path = _safe_member_path(root_text)
            listed_files = record.get("files", ())
            if not isinstance(listed_files, list) or not listed_files:
                raise VFXPackageError(f"Bundled custom node '{package_id}' has no file list.")
            record_paths: set[str] = set()
            for member in listed_files:
                member_text = str(member or "")
                member_path = _safe_member_path(member_text)
                try:
                    member_path.relative_to(root_path)
                except ValueError as exc:
                    raise VFXPackageError(
                        f"Custom node file escapes its package root: {member_text}"
                    ) from exc
                if member_text not in declared_paths:
                    raise VFXPackageError(
                        f"Bundled custom node file is not declared by the package: {member_text}"
                    )
                record_paths.add(member_text)
                custom_node_paths.add(member_text)
            manifest_member = str(PurePosixPath(root_text, "node.toml"))
            if manifest_member not in record_paths:
                raise VFXPackageError(
                    f"Bundled custom node '{package_id}' has no root node.toml."
                )
            custom_nodes.append(dict(record))
        declared_custom_paths = {entry.path for entry in files if entry.kind == "custom-node"}
        if declared_custom_paths != custom_node_paths:
            missing = sorted(declared_custom_paths ^ custom_node_paths)
            raise VFXPackageError(
                "Custom node inventory does not match packaged files:\n" + "\n".join(missing)
            )

        image_sources_raw = manifest.get("image_sources", ())
        if not isinstance(image_sources_raw, list):
            raise VFXPackageError("Package image_sources inventory must be a list.")
        image_sources: list[dict[str, Any]] = []
        image_source_paths: set[str] = set()
        file_by_path = {entry.path: entry for entry in files}
        for record in image_sources_raw:
            if not isinstance(record, Mapping):
                raise VFXPackageError("Package image_sources inventory contains an invalid entry.")
            member_text = str(record.get("path") or "")
            _safe_member_path(member_text)
            if member_text in image_source_paths:
                raise VFXPackageError(f"Package image_sources lists a duplicate file: {member_text}")
            image_source_paths.add(member_text)
            file_entry = file_by_path.get(member_text)
            if file_entry is None or file_entry.kind != "image-source":
                raise VFXPackageError(
                    f"Packaged image source is not declared as an image-source file: {member_text}"
                )
            expected_hash = str(record.get("sha256") or "").lower()
            if expected_hash != file_entry.sha256:
                raise VFXPackageError(
                    f"Packaged image source hash does not match the file inventory: {member_text}"
                )
            if int(record.get("size", -1)) != file_entry.size:
                raise VFXPackageError(
                    f"Packaged image source size does not match the file inventory: {member_text}"
                )
            uses = record.get("uses", ())
            if not isinstance(uses, list):
                raise VFXPackageError(f"Packaged image source has an invalid uses list: {member_text}")
            image_sources.append(dict(record))
        declared_image_paths = {entry.path for entry in files if entry.kind == "image-source"}
        if declared_image_paths != image_source_paths:
            mismatch = sorted(declared_image_paths ^ image_source_paths)
            raise VFXPackageError(
                "Image source inventory does not match packaged files:\n" + "\n".join(mismatch)
            )

        mesh_sources_raw = manifest.get("mesh_sources", [])
        if not isinstance(mesh_sources_raw, list):
            raise VFXPackageError("Package mesh_sources inventory must be a list.")
        mesh_sources: list[dict[str, Any]] = []
        mesh_source_paths: set[str] = set()
        for record in mesh_sources_raw:
            if not isinstance(record, Mapping):
                raise VFXPackageError("Package mesh_sources inventory contains an invalid entry.")
            member_text = str(record.get("path") or "")
            _safe_member_path(member_text)
            if member_text in mesh_source_paths:
                raise VFXPackageError(f"Package mesh_sources lists a duplicate file: {member_text}")
            mesh_source_paths.add(member_text)
            file_entry = file_by_path.get(member_text)
            if file_entry is None or file_entry.kind != "mesh-source":
                raise VFXPackageError(
                    f"Packaged mesh source is not declared as a mesh-source file: {member_text}"
                )
            expected_hash = str(record.get("sha256") or "").lower()
            if expected_hash != file_entry.sha256:
                raise VFXPackageError(
                    f"Packaged mesh source hash does not match the file inventory: {member_text}"
                )
            if int(record.get("size", -1)) != file_entry.size:
                raise VFXPackageError(
                    f"Packaged mesh source size does not match the file inventory: {member_text}"
                )
            uses = record.get("uses", ())
            if not isinstance(uses, list):
                raise VFXPackageError(f"Packaged mesh source has an invalid uses list: {member_text}")
            mesh_sources.append(dict(record))
        declared_mesh_paths = {entry.path for entry in files if entry.kind == "mesh-source"}
        if declared_mesh_paths != mesh_source_paths:
            mismatch = sorted(declared_mesh_paths ^ mesh_source_paths)
            raise VFXPackageError(
                "Mesh source inventory does not match packaged files:\n" + "\n".join(mismatch)
            )

        export_templates_raw = manifest.get("export_templates", ())
        if not isinstance(export_templates_raw, list):
            raise VFXPackageError("Package export_templates inventory must be a list.")
        export_templates: list[dict[str, Any]] = []
        export_template_paths: set[str] = set()
        export_template_ids: set[str] = set()
        for record in export_templates_raw:
            if not isinstance(record, Mapping):
                raise VFXPackageError("Package export_templates inventory contains an invalid entry.")
            member_text = str(record.get("path") or "")
            _safe_member_path(member_text)
            if member_text in export_template_paths:
                raise VFXPackageError(f"Package export_templates lists a duplicate file: {member_text}")
            export_template_paths.add(member_text)
            file_entry = file_by_path.get(member_text)
            if file_entry is None or file_entry.kind != "export-template":
                raise VFXPackageError(
                    f"Packaged export template is not declared as an export-template file: {member_text}"
                )
            expected_hash = str(record.get("sha256") or "").lower()
            if expected_hash and expected_hash != file_entry.sha256:
                raise VFXPackageError(
                    f"Packaged export template hash does not match the file inventory: {member_text}"
                )
            try:
                raw_template = json.loads(archive.read(member_text).decode("utf-8"))
                if str(raw_template.get("format") or "") != "vfx-texture-lab-export-template":
                    raise ValueError("wrong format")
                template = ExportTemplate.from_dict(raw_template)
                errors, _warnings = validate_export_template(template)
                if errors:
                    raise ValueError("; ".join(errors))
            except Exception as exc:
                raise VFXPackageError(f"Packaged export template is invalid: {member_text}") from exc
            template_id = str(record.get("template_id") or template.template_id).strip()
            if template_id and template_id in export_template_ids:
                raise VFXPackageError(f"Package contains duplicate export Template ID: {template_id}")
            if template_id:
                export_template_ids.add(template_id)
            export_templates.append(dict(record))
        declared_template_paths = {entry.path for entry in files if entry.kind == "export-template"}
        if declared_template_paths != export_template_paths:
            mismatch = sorted(declared_template_paths ^ export_template_paths)
            raise VFXPackageError(
                "Export template inventory does not match packaged files:\n" + "\n".join(mismatch)
            )

        expected_files = declared_paths | {PACKAGE_MANIFEST}
        extras = actual_files - expected_files
        if extras:
            raise VFXPackageError(
                "Package contains files not declared by its manifest:\n" + "\n".join(sorted(extras))
            )
        if entry_graph not in declared_paths:
            raise VFXPackageError("The entry graph is not present in the manifest inventory.")
        if thumbnail_path and thumbnail_path not in declared_paths:
            raise VFXPackageError("The thumbnail is not present in the manifest inventory.")

        try:
            graph = json.loads(archive.read(entry_graph).decode("utf-8"))
        except Exception as exc:
            raise VFXPackageError(f"Could not read package entry graph: {exc}") from exc
        if not isinstance(graph, dict) or str(graph.get("format", "")) != GRAPH_ASSET_FORMAT:
            raise VFXPackageError("Package entry graph is not a valid VFX Texture Lab graph.")
        if validate_graph:
            try:
                validate_self_contained_graph(graph)
            except SelfContainedGraphError as exc:
                raise VFXPackageError(f"Package entry graph is not self-contained:\n{exc}") from exc

        asset = manifest.get("asset")
        if not isinstance(asset, Mapping):
            raise VFXPackageError("Package manifest has no asset metadata.")
        asset_id = str(asset.get("asset_id") or "").strip()
        package_id = str(manifest.get("package_id") or asset_id).strip()
        if not asset_id or not package_id:
            raise VFXPackageError("Package has no stable Asset ID.")
        graph_meta = graph.get("graph_asset") if isinstance(graph, Mapping) else None
        if isinstance(graph_meta, Mapping):
            graph_asset_id = str(graph_meta.get("asset_id") or "").strip()
            if graph_asset_id and graph_asset_id != asset_id:
                raise VFXPackageError("Manifest Asset ID does not match the entry graph.")

        return VFXPackageInfo(
            source_path=path,
            package_id=package_id,
            asset_id=asset_id,
            name=str(asset.get("name") or Path(entry_graph).stem),
            description=str(asset.get("description") or ""),
            category=str(asset.get("category") or "Graph Assets"),
            tags=_normalise_tags(asset.get("tags", ())),
            author=str(asset.get("author") or ""),
            asset_version=str(asset.get("version") or "1.0.0"),
            created_with=str(manifest.get("created_with") or ""),
            created_at=str(manifest.get("created_at") or ""),
            entry_graph=entry_graph,
            thumbnail_path=thumbnail_path,
            files=files,
            custom_nodes=custom_nodes,
            image_sources=image_sources,
            mesh_sources=mesh_sources,
            export_templates=export_templates,
            manifest=dict(manifest),
        )


def read_package_entry_graph(source: str | Path, info: VFXPackageInfo | None = None) -> dict[str, Any]:
    path = Path(source).expanduser().resolve()
    info = info or inspect_vfxpackage(path)
    with zipfile.ZipFile(path, "r") as archive:
        return json.loads(archive.read(info.entry_graph).decode("utf-8"))


def read_package_thumbnail(source: str | Path, info: VFXPackageInfo | None = None) -> bytes | None:
    path = Path(source).expanduser().resolve()
    info = info or inspect_vfxpackage(path)
    if not info.thumbnail_path:
        return None
    with zipfile.ZipFile(path, "r") as archive:
        return archive.read(info.thumbnail_path)



def write_packaged_custom_node_archives(
    source: str | Path,
    destination: str | Path,
    info: VFXPackageInfo | None = None,
) -> list[tuple[dict[str, Any], Path]]:
    """Write bundled custom-node folders as installable .vfxnodepkg archives."""

    source_path = Path(source).expanduser().resolve()
    info = info or inspect_vfxpackage(source_path)
    root = Path(destination).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    results: list[tuple[dict[str, Any], Path]] = []
    with zipfile.ZipFile(source_path, "r") as package_archive:
        for record in info.custom_nodes:
            package_id = str(record.get("package_id") or "custom-node")
            package_root = _safe_member_path(str(record.get("root") or ""))
            archive_path = root / f"{_safe_slug(package_id, 'custom-node')}.vfxnodepkg"
            with zipfile.ZipFile(
                archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as node_archive:
                for member_text in record.get("files", ()):
                    member = _safe_member_path(str(member_text))
                    relative = member.relative_to(package_root)
                    node_archive.writestr(str(relative), package_archive.read(str(member)))
            results.append((dict(record), archive_path))
    return results



def read_packaged_export_templates(source: str | Path, info: VFXPackageInfo | None = None) -> list[ExportTemplate]:
    path = Path(source).expanduser().resolve()
    info = info or inspect_vfxpackage(path)
    templates: list[ExportTemplate] = []
    with zipfile.ZipFile(path, "r") as archive:
        for record in info.export_templates:
            member = str(record.get("path") or "")
            if not member:
                continue
            templates.append(ExportTemplate.from_dict(json.loads(archive.read(member).decode("utf-8"))))
    return templates

def extract_vfxpackage(
    source: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> tuple[VFXPackageInfo, Path]:
    """Safely extract declared files through staging and return the entry graph."""

    source_path = Path(source).expanduser().resolve()
    info = inspect_vfxpackage(source_path)
    authored_root = Path(destination).expanduser()
    if authored_root.is_symlink():
        raise VFXPackageError(f"Refusing to extract through a symbolic-link destination:\n{authored_root}")
    root = authored_root.resolve()
    if root.exists():
        if not root.is_dir():
            raise VFXPackageError(f"Destination is not a folder:\n{root}")
        if any(root.iterdir()) and not overwrite:
            raise VFXPackageError(f"Destination folder is not empty:\n{root}")
    root.parent.mkdir(parents=True, exist_ok=True)

    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{root.name}-extract-", dir=root.parent)
    )
    backup: Path | None = None
    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            for member in [PACKAGE_MANIFEST, *(entry.path for entry in info.files)]:
                relative = _safe_member_path(member)
                assert staging is not None
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source_stream, target.open("wb") as output:
                    shutil.copyfileobj(source_stream, output, length=1024 * 1024)
        # Validate from extracted bytes as well, not only through the archive.
        assert staging is not None
        manifest = json.loads((staging / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
        for entry in info.files:
            candidate = staging.joinpath(*PurePosixPath(entry.path).parts)
            hasher = hashlib.sha256()
            actual_size = 0
            with candidate.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    actual_size += len(chunk)
                    hasher.update(chunk)
            if actual_size != entry.size or hasher.hexdigest() != entry.sha256:
                raise VFXPackageError(f"Extracted file failed integrity validation: {entry.path}")
        entry_in_staging = staging.joinpath(*PurePosixPath(info.entry_graph).parts)
        if str(manifest.get("entry_graph", "")) != info.entry_graph or not entry_in_staging.is_file():
            raise VFXPackageError("Extracted package has no valid entry graph.")

        if root.exists():
            backup = root.parent / f".{root.name}.backup-{time.time_ns()}"
            root.replace(backup)
        try:
            staging.replace(root)
            staging = None
        except Exception:
            if backup is not None and backup.exists() and not root.exists():
                backup.replace(root)
                backup = None
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
        entry = root.joinpath(*PurePosixPath(info.entry_graph).parts)
        return info, entry
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists():
            if not root.exists():
                try:
                    backup.replace(root)
                    backup = None
                except OSError:
                    pass
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)


def installed_package_root(graph_asset_root: str | Path) -> Path:
    path = Path(graph_asset_root).expanduser().resolve() / "Packages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def installed_packages(graph_asset_root: str | Path, *, asset_id: str = "") -> list[VFXPackageInfo]:
    root = installed_package_root(graph_asset_root)
    matches: list[VFXPackageInfo] = []
    for manifest_path in sorted(root.rglob(PACKAGE_MANIFEST), key=lambda value: str(value).casefold()):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            package_asset = manifest.get("asset", {}) if isinstance(manifest, Mapping) else {}
            current_id = str(package_asset.get("asset_id") or "").strip()
            if asset_id and current_id != asset_id:
                continue
            files = [
                PackageFile(
                    path=str(entry.get("path") or ""),
                    kind=str(entry.get("kind") or "resource"),
                    size=int(entry.get("size", 0) or 0),
                    sha256=str(entry.get("sha256") or ""),
                )
                for entry in manifest.get("files", ())
                if isinstance(entry, Mapping)
            ]
            matches.append(
                VFXPackageInfo(
                    source_path=manifest_path.parent,
                    package_id=str(manifest.get("package_id") or current_id),
                    asset_id=current_id,
                    name=str(package_asset.get("name") or manifest_path.parent.name),
                    description=str(package_asset.get("description") or ""),
                    category=str(package_asset.get("category") or "Graph Assets"),
                    tags=_normalise_tags(package_asset.get("tags", ())),
                    author=str(package_asset.get("author") or ""),
                    asset_version=str(package_asset.get("version") or "1.0.0"),
                    created_with=str(manifest.get("created_with") or ""),
                    created_at=str(manifest.get("created_at") or ""),
                    entry_graph=str(manifest.get("entry_graph") or ""),
                    thumbnail_path=str(manifest.get("thumbnail") or ""),
                    files=files,
                    custom_nodes=[dict(entry) for entry in manifest.get("custom_nodes", ()) if isinstance(entry, Mapping)],
                    image_sources=[dict(entry) for entry in manifest.get("image_sources", ()) if isinstance(entry, Mapping)],
                    mesh_sources=[dict(entry) for entry in manifest.get("mesh_sources", ()) if isinstance(entry, Mapping)],
                    export_templates=[dict(entry) for entry in manifest.get("export_templates", ()) if isinstance(entry, Mapping)],
                    manifest=dict(manifest),
                )
            )
        except Exception:
            continue
    return matches


def install_vfxpackage(
    source: str | Path,
    graph_asset_root: str | Path,
    *,
    replace_directory: str | Path | None = None,
    side_by_side: bool = False,
) -> tuple[VFXPackageInfo, Path]:
    """Install a validated package into the managed Graph Asset package folder."""

    info = inspect_vfxpackage(source)
    root = installed_package_root(graph_asset_root)
    if replace_directory is not None:
        destination = Path(replace_directory).expanduser().resolve()
        try:
            destination.relative_to(root)
        except ValueError as exc:
            raise VFXPackageError("Refusing to replace a package outside the managed library.") from exc
        overwrite = True
    else:
        base = _safe_slug(f"{info.name}-{info.asset_version}", "graph-asset")
        destination = root / base
        if destination.exists() or side_by_side:
            suffix = info.asset_id[:8] or "asset"
            destination = root / f"{base}-{suffix}"
            index = 2
            while destination.exists():
                destination = root / f"{base}-{suffix}-{index}"
                index += 1
        overwrite = False
    return extract_vfxpackage(source, destination, overwrite=overwrite)
