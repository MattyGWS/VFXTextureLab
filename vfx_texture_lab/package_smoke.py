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
    fast_simplification_module = _check_import("fast_simplification", checks, errors)
    xatlas_module = _check_import("xatlas", checks, errors)
    trimesh_module = _check_import("trimesh", checks, errors)
    embreex_module = _check_import("embreex", checks, errors)
    _check_import("scipy.ndimage", checks, errors)
    _check_import("scipy.sparse.csgraph", checks, errors)
    skimage_measure_module = _check_import("skimage.measure", checks, errors)
    if xatlas_module is not None:
        if not hasattr(xatlas_module, "Atlas") or not hasattr(xatlas_module, "ChartOptions"):
            errors.append("Native xatlas bindings do not expose the expected Atlas API")
        elif numpy_module is not None:
            try:
                atlas = xatlas_module.Atlas()
                points = numpy_module.asarray(
                    ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
                    dtype=numpy_module.float32,
                )
                faces = numpy_module.asarray(
                    ((0, 1, 2), (0, 2, 3)), dtype=numpy_module.uint32
                )
                atlas.add_mesh(points, faces)
                atlas.generate()
                mapping, output_faces, uvs = atlas[0]
                atlas_ids, chart_ids = atlas.get_mesh_vertex_assignment(0)
                if (
                    len(mapping) < 4
                    or len(output_faces) != 2
                    or len(uvs) != len(mapping)
                    or len(atlas_ids) != len(mapping)
                    or len(chart_ids) != len(mapping)
                ):
                    raise ValueError("native xatlas returned incomplete smoke-test data")
                checks.append("Executed native xatlas UV charting and assignment API")
            except Exception as exc:
                errors.append(f"Native xatlas: {type(exc).__name__}: {exc}")
    if embreex_module is not None and trimesh_module is not None and numpy_module is not None:
        try:
            from trimesh.ray.ray_pyembree import RayMeshIntersector
            mesh = trimesh_module.Trimesh(
                vertices=numpy_module.asarray(((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0))),
                faces=numpy_module.asarray(((0, 1, 2),)),
                process=False,
            )
            intersector = RayMeshIntersector(mesh)
            hit = intersector.intersects_any(
                numpy_module.asarray(((0.0, 0.0, 1.0),)),
                numpy_module.asarray(((0.0, 0.0, -1.0),)),
            )
            if not bool(hit[0]):
                raise ValueError("Embree ray missed the smoke-test triangle")
            checks.append("Executed the native Embree high-to-low projection backend")

            from .geometry import GeometryData, plane_geometry
            from .geometry_bake import _perform_bake
            low = plane_geometry(1.0, 1.0, 1, 1, "Vertical (XY)", name="Bake Low")
            high_base = plane_geometry(1.0, 1.0, 1, 1, "Vertical (XY)", name="Bake High")
            high_vertices = high_base.vertices.copy()
            high_vertices[:, 2] += 0.05
            high = GeometryData(high_vertices, high_base.indices.copy(), "Bake High")
            source_colour = numpy_module.ones((8, 8, 4), dtype=numpy_module.float32)
            source_colour[..., 0] = 0.25
            baked = _perform_bake(
                high, low, source_colour, None,
                {
                    "resolution": 64,
                    "supersampling": "1x",
                    "padding": 2,
                    "bake_albedo": True,
                    "bake_normal": True,
                    "bake_height": True,
                    "bake_ambient_occlusion": False,
                    "projection_mode": "Outward Only",
                    "distance_mode": "Manual",
                    "front_distance": 0.2,
                    "back_distance": 0.2,
                    "ray_bias_percent": 0.001,
                    "height_range": "Automatic Symmetric",
                    "normal_y": "OpenGL (+Y)",
                    "albedo_filter": "Bilinear",
                    "preserve_alpha": True,
                    "name": "Bake Smoke",
                },
                None,
            )
            if baked.diagnostics.get("hit_percent", 0.0) < 99.0:
                raise ValueError("high-to-low bake smoke test had projection misses")
            if not {"Albedo", "Normal", "Height", "Projection Mask"}.issubset(baked.maps):
                raise ValueError("high-to-low bake smoke test did not publish all requested maps")
            checks.append("Completed a native high-to-low map bake")
        except Exception as exc:
            errors.append(f"Embree bake backend: {type(exc).__name__}: {exc}")

    if (
        trimesh_module is not None
        and skimage_measure_module is not None
        and numpy_module is not None
    ):
        try:
            from .geometry import GeometryEvalContext, box_geometry
            from .mesh_remesh import voxel_remesh

            source = box_geometry(1.0, 1.0, 1.0, 1, 1, 1, name="Smoke Box")
            result = voxel_remesh(
                source,
                {
                    "name": "Smoke Remesh",
                    "voxel_size_mode": "Relative to Bounds",
                    "relative_voxel_size": 25.0,
                    "fill_interior": True,
                    "surface_smoothing": 0.25,
                    "preserve_volume": True,
                    "adaptivity": 0.0,
                },
                GeometryEvalContext(),
            )
            if result.geometry.triangle_count < 4:
                raise ValueError("voxel remesh returned an empty smoke-test mesh")
            if not bool(result.diagnostics.get("output_closed_manifold", False)):
                raise ValueError("voxel remesh smoke-test output was not closed")
            checks.append("Executed Geometry Remesh native dependency stack")
        except Exception as exc:
            errors.append(f"Geometry Remesh: {type(exc).__name__}: {exc}")

    if fast_simplification_module is not None and numpy_module is not None:
        try:
            points = numpy_module.asarray(
                ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
                dtype=numpy_module.float64,
            )
            faces = numpy_module.asarray(((0, 1, 2), (0, 2, 3)), dtype=numpy_module.int64)
            out_points, out_faces = fast_simplification_module.simplify(
                points, faces, target_count=1, agg=3.0
            )
            if len(out_points) < 3 or len(out_faces) < 1:
                raise ValueError("native simplifier returned an empty smoke-test mesh")
            checks.append("Executed native high-poly simplification extension")
        except Exception as exc:
            errors.append(f"Native simplification: {type(exc).__name__}: {exc}")

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
