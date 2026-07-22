"""Non-interactive validation used by Windows packaging automation."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import json
import platform
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from . import __version__


@dataclass(slots=True)
class SmokeReport:
    ok: bool
    version: str
    frozen: bool
    python: str
    platform: str
    node_count: int
    shader_count: int
    environment_count: int
    bundled_node_package_count: int
    native_wgpu_libraries: list[str]
    checks: list[str]
    errors: list[str]


def _walk_files(root) -> Iterable:
    for child in root.iterdir():
        if child.is_dir():
            yield from _walk_files(child)
        else:
            yield child


def _resource_files(package: str) -> list:
    return list(_walk_files(importlib.resources.files(package)))


def _check_import(module_name: str, checks: list[str], errors: list[str]):
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - diagnostic path
        errors.append(f"Import {module_name}: {type(exc).__name__}: {exc}")
        return None
    checks.append(f"Imported {module_name}")
    return module


def run_package_smoke_test(*, require_frozen: bool = False) -> SmokeReport:
    checks: list[str] = []
    errors: list[str] = []
    frozen = bool(getattr(sys, "frozen", False))

    if require_frozen and not frozen:
        errors.append("The smoke test was required to run from a frozen executable.")

    try:
        installed_version = importlib.metadata.version("vfx-texture-lab")
    except importlib.metadata.PackageNotFoundError:
        installed_version = __version__
    if installed_version != __version__:
        errors.append(
            f"Version mismatch: package metadata says {installed_version}, "
            f"but vfx_texture_lab.__version__ says {__version__}."
        )
    else:
        checks.append(f"Application version is {__version__}")

    numpy_module = _check_import("numpy", checks, errors)
    _check_import("PIL.Image", checks, errors)
    _check_import("PySide6.QtCore", checks, errors)
    _check_import("rendercanvas", checks, errors)
    _check_import("wgpu", checks, errors)
    _check_import("wgpu.backends.auto", checks, errors)
    _check_import("wgpu.backends.wgpu_native", checks, errors)

    shader_files: list = []
    try:
        shader_files = [
            item for item in _resource_files("vfx_texture_lab.shaders")
            if item.name.lower().endswith(".wgsl")
        ]
        required_shaders = {
            "preview_3d.wgsl",
            "preview_3d_post.wgsl",
            "preview_3d_bloom.wgsl",
            "fused_adjustments.wgsl",
        }
        present = {item.name for item in shader_files}
        missing = sorted(required_shaders - present)
        if missing:
            errors.append(f"Required WGSL shaders are missing: {', '.join(missing)}")
        elif len(shader_files) < 100:
            errors.append(f"Only {len(shader_files)} WGSL shaders were packaged; expected at least 100.")
        else:
            checks.append(f"Found {len(shader_files)} packaged WGSL shaders")
    except Exception as exc:
        errors.append(f"Shader resources: {type(exc).__name__}: {exc}")

    environment_files: list = []
    try:
        environment_files = [
            item for item in _resource_files("vfx_texture_lab.assets.environments")
            if item.name.lower().endswith(".npz")
        ]
        if len(environment_files) < 4:
            errors.append(
                f"Only {len(environment_files)} environment archives were packaged; expected at least 4."
            )
        elif numpy_module is not None:
            for resource in environment_files:
                with importlib.resources.as_file(resource) as path:
                    with numpy_module.load(path) as archive:
                        if not archive.files:
                            raise ValueError(f"Environment archive is empty: {resource.name}")
            checks.append(f"Opened {len(environment_files)} packaged environment archives")
    except Exception as exc:
        errors.append(f"Environment resources: {type(exc).__name__}: {exc}")

    bundled_manifests: list = []
    try:
        package_files = _resource_files("vfx_texture_lab.node_packages")
        bundled_manifests = [item for item in package_files if item.name == "node.toml"]
        bundled_shaders = [item for item in package_files if item.name.lower().endswith(".wgsl")]
        if not bundled_manifests:
            errors.append("No bundled custom-node manifests were packaged.")
        elif len(bundled_shaders) < len(bundled_manifests):
            errors.append("A bundled custom-node package is missing its WGSL shader.")
        else:
            for manifest in bundled_manifests:
                tomllib.loads(manifest.read_text(encoding="utf-8"))
            checks.append(f"Parsed {len(bundled_manifests)} bundled custom-node manifests")
    except Exception as exc:
        errors.append(f"Bundled node packages: {type(exc).__name__}: {exc}")

    node_count = 0
    try:
        from .nodes import build_registry

        registry = build_registry()
        node_count = len(registry.all(include_hidden=True))
        if node_count < 170:
            errors.append(f"Only {node_count} built-in node definitions loaded; expected at least 170.")
        else:
            checks.append(f"Loaded {node_count} built-in node definitions")
    except Exception as exc:
        errors.append(f"Node registry: {type(exc).__name__}: {exc}")

    native_libraries: list[str] = []
    try:
        wgpu_root = importlib.resources.files("wgpu")
        native_libraries = sorted(
            str(item).replace("\\", "/")
            for item in _walk_files(wgpu_root)
            if item.name.lower().endswith((".dll", ".so", ".dylib"))
            and "wgpu" in item.name.lower()
        )
        if not native_libraries:
            errors.append("No packaged wgpu-native dynamic library was found.")
        else:
            checks.append(f"Found {len(native_libraries)} wgpu-native dynamic library file(s)")
    except Exception as exc:
        errors.append(f"wgpu-native resources: {type(exc).__name__}: {exc}")

    return SmokeReport(
        ok=not errors,
        version=__version__,
        frozen=frozen,
        python=sys.version.split()[0],
        platform=platform.platform(),
        node_count=node_count,
        shader_count=len(shader_files),
        environment_count=len(environment_files),
        bundled_node_package_count=len(bundled_manifests),
        native_wgpu_libraries=native_libraries,
        checks=checks,
        errors=errors,
    )


def write_smoke_report(report: SmokeReport, path: str | Path | None = None) -> None:
    payload = json.dumps(asdict(report), indent=2, sort_keys=True)
    if path is not None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
