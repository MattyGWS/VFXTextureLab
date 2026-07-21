from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QFileSystemWatcher, QObject, QSettings, QStandardPaths, QTimer, Signal

from .nodes.base import (
    GpuNodeSpec,
    NodeDefinition,
    NodePackageInfo,
    ParameterSpec,
    ShaderParameterBinding,
)

API_VERSION = 2
SUPPORTED_API_VERSIONS = {1, 2}
NODE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+$")
SUPPORTED_PARAMETER_KINDS = {"float", "int", "bool", "enum", "color"}
SUPPORTED_FORMATS = {"r16f", "rg16f", "rgba16f", "rgba32f"}
SUPPORTED_FORMAT_POLICIES = {"declared", "preserve_first"}
SUPPORTED_IMAGE_KINDS = {"grayscale", "color", "vector", "image_any", "image"}


@dataclass(slots=True)
class NodeLibraryLocation:
    uid: str
    name: str
    path: str
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"uid": self.uid, "name": self.name, "path": self.path, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeLibraryLocation":
        path = str(data.get("path", "")).strip()
        uid = str(data.get("uid", "")).strip() or hashlib.blake2b(path.encode(), digest_size=8).hexdigest()
        name = str(data.get("name", "")).strip() or Path(path).name or "Custom Node Library"
        return cls(uid=uid, name=name, path=path, enabled=bool(data.get("enabled", True)))


@dataclass(slots=True)
class PackageDiagnostic:
    package_id: str
    name: str
    version: str
    severity: str
    message: str
    root: str
    source_kind: str
    library_name: str
    manifest_path: str = ""
    shader_path: str = ""
    line: int | None = None
    column: int | None = None
    using_last_good: bool = False

    @property
    def status_label(self) -> str:
        return {
            "ok": "Ready",
            "warning": "Warning",
            "error": "Error",
            "disabled": "Disabled",
        }.get(self.severity, self.severity.title())


class PackageValidationError(ValueError):
    pass


class CustomNodePackageManager(QObject):
    """Discovers declarative WGSL node packages and watches their source files.

    Built-in packages, the managed user package directory, and any user-added
    library folders all travel through the exact same parser and validation path.
    """

    packagesChanged = Signal()
    diagnosticsChanged = Signal()
    sourceFilesChanged = Signal(list)

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings()
        app_data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self.managed_directory = app_data / "custom_node_packages"
        self.managed_directory.mkdir(parents=True, exist_ok=True)
        self._libraries = self._load_libraries()
        self._disabled_ids = set(self._load_string_list("custom_nodes/disabled_ids"))
        self._definitions: dict[str, NodeDefinition] = {}
        self._diagnostics: list[PackageDiagnostic] = []
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._watcher_changed)
        self._watcher.directoryChanged.connect(self._watcher_changed)
        self._changed_paths: set[str] = set()
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(280)
        self._watch_timer.timeout.connect(self._emit_watched_changes)

    # ------------------------------------------------------------------
    # Locations and persistent application settings
    # ------------------------------------------------------------------
    @staticmethod
    def bundled_directory() -> Path:
        return Path(__file__).resolve().parent / "node_packages"

    def libraries(self) -> list[NodeLibraryLocation]:
        return [NodeLibraryLocation(item.uid, item.name, item.path, item.enabled) for item in self._libraries]

    def add_library(self, path: str | Path, name: str | None = None) -> NodeLibraryLocation:
        resolved = str(Path(path).expanduser().resolve())
        for existing in self._libraries:
            if str(Path(existing.path).expanduser().resolve()) == resolved:
                existing.enabled = True
                if name:
                    existing.name = name.strip() or existing.name
                self._save_libraries()
                return existing
        uid = hashlib.blake2b(resolved.encode("utf-8"), digest_size=8).hexdigest()
        entry = NodeLibraryLocation(uid, (name or Path(resolved).name or "Custom Node Library").strip(), resolved, True)
        self._libraries.append(entry)
        self._save_libraries()
        return entry

    def remove_library(self, uid: str) -> None:
        self._libraries = [item for item in self._libraries if item.uid != uid]
        self._save_libraries()

    def set_library_enabled(self, uid: str, enabled: bool) -> None:
        for item in self._libraries:
            if item.uid == uid:
                item.enabled = bool(enabled)
                break
        self._save_libraries()

    def set_library_name(self, uid: str, name: str) -> None:
        for item in self._libraries:
            if item.uid == uid:
                item.name = name.strip() or item.name
                break
        self._save_libraries()

    def is_disabled(self, package_id: str) -> bool:
        return package_id in self._disabled_ids

    def set_disabled(self, package_id: str, disabled: bool) -> None:
        if disabled:
            self._disabled_ids.add(package_id)
        else:
            self._disabled_ids.discard(package_id)
        self.settings.setValue("custom_nodes/disabled_ids", sorted(self._disabled_ids))

    def _load_libraries(self) -> list[NodeLibraryLocation]:
        raw = self.settings.value("custom_nodes/library_locations", "[]")
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            data = []
        result: list[NodeLibraryLocation] = []
        for entry in data if isinstance(data, list) else []:
            if isinstance(entry, dict):
                item = NodeLibraryLocation.from_dict(entry)
                if item.path:
                    result.append(item)
        return result

    def _save_libraries(self) -> None:
        self.settings.setValue(
            "custom_nodes/library_locations",
            json.dumps([entry.to_dict() for entry in self._libraries], separators=(",", ":")),
        )

    def _load_string_list(self, key: str) -> list[str]:
        value = self.settings.value(key, [])
        if isinstance(value, str):
            return [value] if value else []
        return [str(item) for item in value or []]

    # ------------------------------------------------------------------
    # Discovery, parsing and validation
    # ------------------------------------------------------------------
    def definitions(self) -> dict[str, NodeDefinition]:
        return dict(self._definitions)

    def diagnostics(self) -> list[PackageDiagnostic]:
        return list(self._diagnostics)

    def diagnostic_for(self, package_id: str) -> PackageDiagnostic | None:
        for item in self._diagnostics:
            if item.package_id == package_id:
                return item
        return None

    def discover(
        self,
        gpu_backend=None,
        previous: dict[str, NodeDefinition] | None = None,
    ) -> dict[str, NodeDefinition]:
        previous = previous or {}
        candidates: dict[str, NodeDefinition] = {}
        diagnostics: list[PackageDiagnostic] = []
        seen_manifest_paths: set[str] = set()

        for source_kind, library_name, root in self._roots():
            root_path = Path(root).expanduser()
            if not root_path.is_dir():
                if source_kind == "library":
                    diagnostics.append(
                        PackageDiagnostic(
                            package_id=f"library:{root_path}",
                            name=library_name,
                            version="",
                            severity="warning",
                            message="Library folder does not exist or is not accessible.",
                            root=str(root_path),
                            source_kind=source_kind,
                            library_name=library_name,
                        )
                    )
                continue
            for manifest_path in sorted(root_path.rglob("node.toml"), key=lambda p: str(p).lower()):
                if any(part.startswith(".") for part in manifest_path.relative_to(root_path).parts):
                    continue
                manifest_key = str(manifest_path.resolve())
                if manifest_key in seen_manifest_paths:
                    continue
                seen_manifest_paths.add(manifest_key)
                try:
                    definition = self._parse_package(manifest_path, source_kind, library_name)
                except Exception as exc:
                    package_id, name, version = self._manifest_identity(manifest_path)
                    diagnostics.append(
                        PackageDiagnostic(
                            package_id=package_id,
                            name=name,
                            version=version,
                            severity="error",
                            message=f"Manifest error: {exc}",
                            root=str(manifest_path.parent),
                            source_kind=source_kind,
                            library_name=library_name,
                            manifest_path=str(manifest_path),
                        )
                    )
                    continue

                package_id = definition.type_id
                package = definition.package
                assert package is not None
                if package_id in candidates:
                    diagnostics.append(
                        PackageDiagnostic(
                            package_id=package_id,
                            name=definition.name,
                            version=package.version,
                            severity="error",
                            message=(
                                "Duplicate permanent node ID. The first discovered package remains active; "
                                "rename this package ID to a unique reverse-domain identifier."
                            ),
                            root=package.root,
                            source_kind=source_kind,
                            library_name=library_name,
                            manifest_path=package.manifest_path,
                            shader_path=package.shader_path,
                        )
                    )
                    continue

                if package_id in self._disabled_ids:
                    diagnostics.append(
                        self._diagnostic_for_definition(
                            definition, "disabled", "Package is disabled in application settings."
                        )
                    )
                    continue

                if gpu_backend is not None and getattr(gpu_backend, "available", False):
                    try:
                        gpu_backend.validate_definition(definition)
                    except Exception as exc:
                        old = previous.get(package_id)
                        line, column = self._extract_line_column(str(exc))
                        if old is not None:
                            candidates[package_id] = old
                            diagnostics.append(
                                PackageDiagnostic(
                                    package_id=package_id,
                                    name=definition.name,
                                    version=package.version,
                                    severity="error",
                                    message=f"Shader reload failed; the last working shader is still active.\n{exc}",
                                    root=package.root,
                                    source_kind=source_kind,
                                    library_name=library_name,
                                    manifest_path=package.manifest_path,
                                    shader_path=package.shader_path,
                                    line=line,
                                    column=column,
                                    using_last_good=True,
                                )
                            )
                        else:
                            diagnostics.append(
                                PackageDiagnostic(
                                    package_id=package_id,
                                    name=definition.name,
                                    version=package.version,
                                    severity="error",
                                    message=f"WGSL compilation failed.\n{exc}",
                                    root=package.root,
                                    source_kind=source_kind,
                                    library_name=library_name,
                                    manifest_path=package.manifest_path,
                                    shader_path=package.shader_path,
                                    line=line,
                                    column=column,
                                )
                            )
                        continue
                elif gpu_backend is None or not getattr(gpu_backend, "available", False):
                    candidates[package_id] = definition
                    diagnostics.append(
                        self._diagnostic_for_definition(
                            definition,
                            "warning",
                            "Manifest loaded, but the WGSL shader could not be preflighted because WebGPU is unavailable.",
                        )
                    )
                    continue

                candidates[package_id] = definition
                diagnostics.append(self._diagnostic_for_definition(definition, "ok", "Package loaded and WGSL compiled successfully."))

        self._definitions = candidates
        self._diagnostics = diagnostics
        self._refresh_watcher()
        self.packagesChanged.emit()
        self.diagnosticsChanged.emit()
        return dict(candidates)

    def _roots(self) -> Iterable[tuple[str, str, Path]]:
        yield "bundled", "Built-in Public Nodes", self.bundled_directory()
        yield "managed", "Managed User Nodes", self.managed_directory
        for library in self._libraries:
            if library.enabled:
                yield "library", library.name, Path(library.path)

    def _parse_package(self, manifest_path: Path, source_kind: str, library_name: str) -> NodeDefinition:
        try:
            data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise PackageValidationError(str(exc)) from exc

        api_version = int(data.get("api_version", 0))
        if api_version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(str(value) for value in sorted(SUPPORTED_API_VERSIONS))
            raise PackageValidationError(f"Unsupported api_version {api_version}; this application supports {supported}.")
        type_id = str(data.get("id", "")).strip()
        if not NODE_ID_RE.fullmatch(type_id):
            raise PackageValidationError("id must be a unique reverse-domain identifier such as com.artist.cloud_noise")
        name = str(data.get("name", "")).strip()
        if not name:
            raise PackageValidationError("name is required")
        version = str(data.get("version", "")).strip()
        if not version:
            raise PackageValidationError("version is required")
        category = str(data.get("category", "Custom")).strip() or "Custom"
        description = str(data.get("description", "")).strip()
        accent = str(data.get("accent", "#6876df")).strip()
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
            raise PackageValidationError("accent must be a six-digit hexadecimal colour such as #6876df")
        tags_raw = data.get("tags", [])
        if not isinstance(tags_raw, list):
            raise PackageValidationError("tags must be an array of strings")
        tags = tuple(str(item).strip() for item in tags_raw if str(item).strip())
        output_format = str(data.get("output_format", "rgba16f")).lower()
        if output_format not in SUPPORTED_FORMATS:
            raise PackageValidationError(f"output_format must be one of {', '.join(sorted(SUPPORTED_FORMATS))}")
        format_policy = str(data.get("format_policy", "declared")).strip().lower()
        if format_policy not in SUPPORTED_FORMAT_POLICIES:
            raise PackageValidationError("format_policy must be declared or preserve_first")
        output_name = str(data.get("output_name", "Image")).strip() or "Image"
        inferred_kind = (
            "image_any" if format_policy == "preserve_first"
            else "color" if output_format.startswith("rgba")
            else "vector" if output_format.startswith("rg")
            else "grayscale"
        )
        output_kind = str(data.get("output_kind", inferred_kind)).strip().lower()
        if output_kind == "image":
            output_kind = "image_any"
        if output_kind not in {"grayscale", "color", "vector", "image_any"}:
            raise PackageValidationError("output_kind must be grayscale, color, vector or image_any")
        raw_outputs = data.get("outputs", [])
        if raw_outputs is None:
            raw_outputs = []
        if not isinstance(raw_outputs, list):
            raise PackageValidationError("[[outputs]] entries must be an array of tables")

        shader_name = str(data.get("shader", "kernel.wgsl")).strip() or "kernel.wgsl"
        shader_path = (manifest_path.parent / shader_name).resolve()
        if manifest_path.parent.resolve() not in shader_path.parents:
            raise PackageValidationError("shader path must remain inside the package folder")
        if not shader_path.is_file():
            raise PackageValidationError(f"shader file does not exist: {shader_name}")

        icon_path: str | None = None
        icon_name = str(data.get("icon", "")).strip()
        if icon_name:
            candidate = (manifest_path.parent / icon_name).resolve()
            if manifest_path.parent.resolve() not in candidate.parents or not candidate.is_file():
                raise PackageValidationError(f"icon file does not exist inside package: {icon_name}")
            icon_path = str(candidate)

        inputs: list[str] = []
        input_kinds: list[tuple[str, str]] = []
        input_defaults: list[tuple[str, float]] = []
        for entry in data.get("inputs", []):
            if not isinstance(entry, dict):
                raise PackageValidationError("each [[inputs]] entry must be a table")
            input_name = str(entry.get("name", "")).strip()
            if not input_name:
                raise PackageValidationError("every input requires a name")
            if input_name in inputs:
                raise PackageValidationError(f"duplicate input name: {input_name}")
            input_type = str(entry.get("type", entry.get("kind", "image_any"))).strip().lower()
            if input_type == "image":
                input_type = "image_any"
            if input_type not in {"grayscale", "color", "vector", "image_any"}:
                raise PackageValidationError(
                    f"public WGSL package input {input_name!r} type must be grayscale, color, vector or image_any"
                )
            inputs.append(input_name)
            input_kinds.append((input_name, input_type))
            default = str(entry.get("default", "black")).strip().lower()
            if default not in ("black", "white"):
                raise PackageValidationError(f"input {input_name!r} default must be black or white")
            input_defaults.append((input_name, 1.0 if default == "white" else 0.0))
        if len(inputs) > 8:
            raise PackageValidationError("The public WGSL API supports at most eight image inputs per node")

        parameters: list[ParameterSpec] = []
        bindings: list[ShaderParameterBinding] = []
        next_slot = 0
        parameter_ids: set[str] = set()
        for entry in data.get("parameters", []):
            if not isinstance(entry, dict):
                raise PackageValidationError("each [[parameters]] entry must be a table")
            parameter_id = str(entry.get("id", "")).strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parameter_id):
                raise PackageValidationError(f"invalid parameter id: {parameter_id!r}")
            if parameter_id in parameter_ids:
                raise PackageValidationError(f"duplicate parameter id: {parameter_id}")
            parameter_ids.add(parameter_id)
            kind = str(entry.get("type", "float")).strip().lower()
            if kind not in SUPPORTED_PARAMETER_KINDS:
                raise PackageValidationError(
                    f"parameter {parameter_id!r} type must be one of {', '.join(sorted(SUPPORTED_PARAMETER_KINDS))}"
                )
            width = 4 if kind == "color" else 1
            if next_slot + width > 12:
                raise PackageValidationError("parameters exceed the public ABI limit of twelve f32 shader slots")
            label = str(entry.get("name", parameter_id.replace("_", " ").title())).strip()
            description_text = str(entry.get("description", "")).strip()
            options: tuple[str, ...] = ()
            minimum = entry.get("minimum")
            maximum = entry.get("maximum")
            step = entry.get("step")
            if kind == "float":
                default: Any = float(entry.get("default", 0.0))
                minimum = float(minimum) if minimum is not None else None
                maximum = float(maximum) if maximum is not None else None
                step = float(step) if step is not None else 0.01
            elif kind == "int":
                default = int(entry.get("default", 0))
                minimum = int(minimum) if minimum is not None else None
                maximum = int(maximum) if maximum is not None else None
                step = int(step) if step is not None else 1
            elif kind == "bool":
                default = bool(entry.get("default", False))
                minimum = maximum = step = None
            elif kind == "enum":
                raw_options = entry.get("options", [])
                if not isinstance(raw_options, list) or not raw_options:
                    raise PackageValidationError(f"enum parameter {parameter_id!r} requires a non-empty options array")
                options = tuple(str(item) for item in raw_options)
                default = str(entry.get("default", options[0]))
                if default not in options:
                    raise PackageValidationError(f"default for {parameter_id!r} must be one of its options")
                minimum = maximum = step = None
            else:  # color
                default = str(entry.get("default", "#ffffffff"))
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", default):
                    raise PackageValidationError(f"colour default for {parameter_id!r} must be #RRGGBB or #RRGGBBAA")
                if len(default) == 7:
                    default += "ff"
                minimum = maximum = step = None
            group_name = str(entry.get("group", "")).strip()
            try:
                group_order = int(entry.get("group_order", 100))
            except (TypeError, ValueError) as exc:
                raise PackageValidationError(
                    f"group_order for parameter {parameter_id!r} must be an integer"
                ) from exc
            slider_minimum = entry.get("slider_minimum")
            slider_maximum = entry.get("slider_maximum")
            fine_step = entry.get("fine_step")
            coarse_step = entry.get("coarse_step")
            if kind == "float":
                slider_minimum = float(slider_minimum) if slider_minimum is not None else None
                slider_maximum = float(slider_maximum) if slider_maximum is not None else None
                fine_step = float(fine_step) if fine_step is not None else None
                coarse_step = float(coarse_step) if coarse_step is not None else None
            elif kind == "int":
                slider_minimum = int(slider_minimum) if slider_minimum is not None else None
                slider_maximum = int(slider_maximum) if slider_maximum is not None else None
                fine_step = int(fine_step) if fine_step is not None else None
                coarse_step = int(coarse_step) if coarse_step is not None else None
            else:
                slider_minimum = slider_maximum = fine_step = coarse_step = None
            editor = str(entry.get("editor", "")).strip().lower()
            if editor not in {"", "angle"}:
                raise PackageValidationError(
                    f"editor for parameter {parameter_id!r} must be empty or 'angle'"
                )
            if editor == "angle" and kind not in {"float", "int"}:
                raise PackageValidationError(
                    f"angle editor for parameter {parameter_id!r} requires a float or int parameter"
                )
            unit = str(entry.get("unit", "")).strip()
            angle_wrap = bool(entry.get("angle_wrap", True))
            parameters.append(
                ParameterSpec(
                    name=parameter_id,
                    label=label,
                    kind=kind,
                    default=default,
                    minimum=minimum,
                    maximum=maximum,
                    step=step,
                    options=options,
                    description=description_text,
                    animatable=bool(entry.get("animatable", False)) if api_version >= 2 and kind in ("float", "int") else False,
                    group=group_name,
                    group_order=group_order,
                    slider_minimum=slider_minimum,
                    slider_maximum=slider_maximum,
                    fine_step=fine_step,
                    coarse_step=coarse_step,
                    editor=editor,
                    unit=unit,
                    angle_wrap=angle_wrap,
                )
            )
            bindings.append(ShaderParameterBinding(parameter_id, kind, next_slot, width, options))
            next_slot += width

        output_names: list[str] = []
        output_kinds: list[tuple[str, str]] = []
        named_output_values: list[tuple[str, Any]] = []
        named_output_parameter: str | None = None
        if raw_outputs:
            named_output_parameter = str(data.get("output_parameter", "")).strip() or None
            if named_output_parameter is None:
                raise PackageValidationError("multi-output packages require output_parameter")
            if named_output_parameter not in parameter_ids:
                raise PackageValidationError("output_parameter must name a declared parameter")
            for entry in raw_outputs:
                if not isinstance(entry, dict):
                    raise PackageValidationError("each [[outputs]] entry must be a table")
                item_name = str(entry.get("name", "")).strip()
                if not item_name or item_name in output_names:
                    raise PackageValidationError(f"invalid or duplicate output name: {item_name!r}")
                item_kind = str(entry.get("kind", output_kind)).strip().lower()
                if item_kind == "image":
                    item_kind = "image_any"
                if item_kind not in {"grayscale", "color", "vector", "image_any"}:
                    raise PackageValidationError(f"invalid output kind for {item_name!r}")
                selector = entry.get("value", item_name)
                output_names.append(item_name)
                output_kinds.append((item_name, item_kind))
                named_output_values.append((item_name, selector))
            output_name = output_names[0]
        else:
            output_names = [output_name]
            output_kinds = [(output_name, output_kind)]

        animation_data = data.get("animation", {})
        if animation_data is None:
            animation_data = {}
        if not isinstance(animation_data, dict):
            raise PackageValidationError("[animation] must be a table")
        uses_time = bool(animation_data.get("uses_time", data.get("uses_time", False))) if api_version >= 2 else False

        revision = self._package_revision(manifest_path, shader_path, Path(icon_path) if icon_path else None)
        package = NodePackageInfo(
            package_id=type_id,
            version=version,
            api_version=api_version,
            root=str(manifest_path.parent.resolve()),
            manifest_path=str(manifest_path.resolve()),
            shader_path=str(shader_path),
            source_kind=source_kind,
            library_name=library_name,
            revision=revision,
            icon_path=icon_path,
        )
        gpu_spec = GpuNodeSpec(
            shader_path=str(shader_path),
            parameter_bindings=tuple(bindings),
            input_defaults=tuple(input_defaults),
            format_policy=format_policy,
            package=package,
            uses_time=uses_time,
        )
        evaluator = None
        if source_kind == "bundled":
            # Bundled packages may opt into a trusted CPU reference supplied by
            # the application. User packages remain WGSL-only and never execute
            # downloaded Python.
            try:
                from .nodes.noise import bundled_package_evaluator
                evaluator = bundled_package_evaluator(type_id)
            except Exception:
                evaluator = None
        return NodeDefinition(
            type_id=type_id,
            name=name,
            category=category,
            evaluator=evaluator,
            inputs=tuple(inputs),
            parameters=tuple(parameters),
            description=description,
            accent=accent,
            tags=tags,
            output_format=output_format,
            gpu_kernel=str(shader_path),
            gpu_spec=gpu_spec,
            output_name=output_name,
            outputs=tuple(output_names),
            named_output_parameter=named_output_parameter,
            named_output_values=tuple(named_output_values),
            input_kinds=tuple(input_kinds),
            output_kinds=tuple(output_kinds),
            uses_time=uses_time,
            type_policy="preserve_primary" if format_policy == "preserve_first" else "fixed",
            primary_input=inputs[0] if inputs and format_policy == "preserve_first" else None,
            default_image_kind=(inferred_kind if output_kind == "image_any" and inferred_kind != "image_any" else ("color" if output_kind == "image_any" else output_kind)),
        )

    @staticmethod
    def _package_revision(manifest: Path, shader: Path, icon: Path | None) -> str:
        hasher = hashlib.blake2b(digest_size=16)
        for path in (manifest, shader, icon):
            if path is None:
                continue
            try:
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(str(path).encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def _manifest_identity(path: Path) -> tuple[str, str, str]:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return f"invalid:{path.parent.name}", path.parent.name, ""
        return (
            str(data.get("id", f"invalid:{path.parent.name}")),
            str(data.get("name", path.parent.name)),
            str(data.get("version", "")),
        )

    @staticmethod
    def _extract_line_column(message: str) -> tuple[int | None, int | None]:
        patterns = (
            r"(?i)line\s+(\d+)[,: ]+column\s+(\d+)",
            r"(?i):(\d+):(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None, None

    @staticmethod
    def _diagnostic_for_definition(definition: NodeDefinition, severity: str, message: str) -> PackageDiagnostic:
        package = definition.package
        assert package is not None
        return PackageDiagnostic(
            package_id=definition.type_id,
            name=definition.name,
            version=package.version,
            severity=severity,
            message=message,
            root=package.root,
            source_kind=package.source_kind,
            library_name=package.library_name,
            manifest_path=package.manifest_path,
            shader_path=package.shader_path,
        )

    # ------------------------------------------------------------------
    # File watching and hot reload
    # ------------------------------------------------------------------
    def _refresh_watcher(self) -> None:
        current_files = set(self._watcher.files())
        current_dirs = set(self._watcher.directories())
        wanted_files: set[str] = set()
        wanted_dirs: set[str] = set()
        for definition in self._definitions.values():
            package = definition.package
            if package is None:
                continue
            wanted_files.update((package.manifest_path, package.shader_path))
            if package.icon_path:
                wanted_files.add(package.icon_path)
            wanted_dirs.add(package.root)
        # Invalid packages must remain watched too, otherwise correcting a shader
        # or manifest would require restarting the application.
        for diagnostic in self._diagnostics:
            if diagnostic.manifest_path:
                wanted_files.add(diagnostic.manifest_path)
            if diagnostic.shader_path:
                wanted_files.add(diagnostic.shader_path)
            if diagnostic.root:
                wanted_dirs.add(diagnostic.root)
        for _kind, _name, root in self._roots():
            if Path(root).is_dir():
                wanted_dirs.add(str(Path(root).resolve()))
        remove_files = sorted(current_files - wanted_files)
        remove_dirs = sorted(current_dirs - wanted_dirs)
        if remove_files:
            self._watcher.removePaths(remove_files)
        if remove_dirs:
            self._watcher.removePaths(remove_dirs)
        add_files = [path for path in sorted(wanted_files - current_files) if Path(path).exists()]
        add_dirs = [path for path in sorted(wanted_dirs - current_dirs) if Path(path).exists()]
        if add_files:
            self._watcher.addPaths(add_files)
        if add_dirs:
            self._watcher.addPaths(add_dirs)

    def _watcher_changed(self, path: str) -> None:
        self._changed_paths.add(str(path))
        self._watch_timer.start()

    def _emit_watched_changes(self) -> None:
        changed = sorted(self._changed_paths)
        self._changed_paths.clear()
        # Some editors replace files atomically, which removes the old watch.
        self._refresh_watcher()
        self.sourceFilesChanged.emit(changed)

    # ------------------------------------------------------------------
    # Package installation and runtime diagnostics
    # ------------------------------------------------------------------
    def install_archive(self, archive_path: str | Path) -> Path:
        archive = Path(archive_path).expanduser().resolve()
        if not archive.is_file():
            raise FileNotFoundError(archive)
        if not zipfile.is_zipfile(archive):
            raise PackageValidationError("Custom node packages must be ZIP-compatible .zip or .vfxnodepkg archives.")
        with tempfile.TemporaryDirectory(prefix="vfxtl-node-") as temp_dir:
            temp_root = Path(temp_dir)
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    member = Path(info.filename)
                    if member.is_absolute() or ".." in member.parts:
                        raise PackageValidationError("Archive contains an unsafe path.")
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise PackageValidationError("Symbolic links are not allowed in custom node archives.")
                bundle.extractall(temp_root)
            manifests = list(temp_root.rglob("node.toml"))
            if len(manifests) != 1:
                raise PackageValidationError("Archive must contain exactly one node.toml package manifest.")
            manifest = manifests[0]
            definition = self._parse_package(manifest, "managed", "Managed User Nodes")
            target = self.managed_directory / self._safe_folder_name(definition.type_id)
            staging = self.managed_directory / f".{target.name}.installing"
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(manifest.parent, staging)
            if target.exists():
                shutil.rmtree(target)
            staging.replace(target)
            return target

    @staticmethod
    def _safe_folder_name(package_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", package_id).strip("._") or "custom_node"

    def record_runtime_error(self, definition: NodeDefinition, message: str) -> None:
        package = definition.package
        if package is None:
            return
        line, column = self._extract_line_column(message)
        replacement = PackageDiagnostic(
            package_id=definition.type_id,
            name=definition.name,
            version=package.version,
            severity="error",
            message=f"Runtime shader error.\n{message}",
            root=package.root,
            source_kind=package.source_kind,
            library_name=package.library_name,
            manifest_path=package.manifest_path,
            shader_path=package.shader_path,
            line=line,
            column=column,
        )
        self._diagnostics = [item for item in self._diagnostics if item.package_id != definition.type_id]
        self._diagnostics.append(replacement)
        self.diagnosticsChanged.emit()
