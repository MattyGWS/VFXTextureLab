#!/usr/bin/env python3
"""Repeatable high-poly import, diagnostics, viewport and decimation stress test.

Examples:
    python tools/geometry_stress.py --triangles 1000000
    python tools/geometry_stress.py --triangles 1000000 --obj-roundtrip
    python tools/geometry_stress.py --triangles 1000000 --decimate-percent 1

The native simplifier is optional at script startup so the report can also prove
whether an older tester environment needs setup.sh/setup.bat rerun.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vfx_texture_lab.geometry import GeometryData, decimate_geometry, load_obj_geometry
from vfx_texture_lab.mesh_processing import diagnose_mesh, native_simplification_available
AUTO_WIREFRAME_TRIANGLE_LIMIT = 250_000


def prepare_viewport_mesh(geometry: GeometryData) -> tuple[np.ndarray, np.ndarray]:
    """Mirror the renderer-facing MeshData normalization without importing Qt."""
    vertices = np.ascontiguousarray(geometry.vertices, dtype=np.float32).reshape(-1, 8)
    indices = np.ascontiguousarray(geometry.indices, dtype=np.uint32).reshape(-1)
    if indices.size % 3:
        raise ValueError("Mesh indices must describe triangles")
    return vertices, indices


def regular_grid(requested_triangles: int) -> GeometryData:
    cells = max(int(math.ceil(requested_triangles / 2)), 1)
    cells_x = max(int(math.sqrt(cells)), 1)
    while cells_x > 1 and cells % cells_x:
        cells_x -= 1
    cells_y = max(int(math.ceil(cells / cells_x)), 1)
    x_count = cells_x + 1
    y_count = cells_y + 1

    xs = np.linspace(-1.0, 1.0, x_count, dtype=np.float32)
    ys = np.linspace(-1.0, 1.0, y_count, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    positions = np.column_stack(
        (xx.reshape(-1), np.zeros(xx.size, dtype=np.float32), yy.reshape(-1))
    )
    normals = np.zeros_like(positions)
    normals[:, 1] = 1.0
    uvs = np.column_stack(
        (
            (xx.reshape(-1) + 1.0) * 0.5,
            (yy.reshape(-1) + 1.0) * 0.5,
        )
    ).astype(np.float32)
    vertices = np.concatenate((positions, normals, uvs), axis=1)

    base = np.arange(cells_y * cells_x, dtype=np.uint32).reshape(cells_y, cells_x)
    row = np.arange(cells_y, dtype=np.uint32)[:, None] * np.uint32(x_count)
    col = np.arange(cells_x, dtype=np.uint32)[None, :]
    a = row + col
    b = a + 1
    c = a + np.uint32(x_count)
    d = c + 1
    triangles = np.stack((a, c, b, b, c, d), axis=-1).reshape(-1, 3)
    triangles = triangles[:requested_triangles]
    return GeometryData(vertices, triangles.reshape(-1), "Stress Grid")


def write_obj(path: Path, geometry: GeometryData) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("o Million Triangle Stress Grid\n")
        for x, y, z in geometry.vertices[:, :3]:
            handle.write(f"v {x:.7g} {y:.7g} {z:.7g}\n")
        for u, v in geometry.vertices[:, 6:8]:
            handle.write(f"vt {u:.7g} {v:.7g}\n")
        for a, b, c in geometry.indices.reshape(-1, 3):
            # Positions and UVs deliberately share one index here.
            ai, bi, ci = int(a) + 1, int(b) + 1, int(c) + 1
            handle.write(f"f {ai}/{ai} {bi}/{bi} {ci}/{ci}\n")


def timer() -> tuple[float, callable]:
    started = time.perf_counter()
    return started, lambda: (time.perf_counter() - started) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--triangles", type=int, default=1_000_000)
    parser.add_argument("--obj-roundtrip", action="store_true")
    parser.add_argument("--keep-obj", type=Path)
    parser.add_argument("--decimate-percent", type=float, default=None)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    requested = max(int(args.triangles), 1)
    _start, elapsed = timer()
    geometry = regular_grid(requested)
    report: dict[str, object] = {
        "requested_triangles": requested,
        "generated_vertices": geometry.vertex_count,
        "generated_triangles": geometry.triangle_count,
        "generated_mesh_bytes": int(geometry.vertices.nbytes + geometry.indices.nbytes),
        "generation_ms": elapsed(),
        "native_simplification_available": native_simplification_available(),
        "auto_wireframe_triangle_limit": AUTO_WIREFRAME_TRIANGLE_LIMIT,
        "auto_wireframe_suppressed": geometry.triangle_count > AUTO_WIREFRAME_TRIANGLE_LIMIT,
    }

    _start, elapsed = timer()
    viewport_vertices, viewport_indices = prepare_viewport_mesh(geometry)
    report["viewport_mesh_prepare_ms"] = elapsed()
    report["viewport_mesh_bytes"] = int(viewport_vertices.nbytes + viewport_indices.nbytes)

    _start, elapsed = timer()
    diagnostics = diagnose_mesh(geometry.vertices, geometry.indices)
    report["diagnostics_ms"] = elapsed()
    report["diagnostics"] = diagnostics.as_metadata()

    if args.obj_roundtrip or args.keep_obj is not None:
        if args.keep_obj is not None:
            obj_path = args.keep_obj.expanduser().resolve()
            obj_path.parent.mkdir(parents=True, exist_ok=True)
            cleanup = False
        else:
            temporary = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
            temporary.close()
            obj_path = Path(temporary.name)
            cleanup = True
        try:
            _start, elapsed = timer()
            write_obj(obj_path, geometry)
            report["obj_write_ms"] = elapsed()
            report["obj_file_bytes"] = obj_path.stat().st_size
            _start, elapsed = timer()
            imported, metadata = load_obj_geometry({"path": str(obj_path)})
            report["obj_import_ms"] = elapsed()
            report["imported_vertices"] = imported.vertex_count
            report["imported_triangles"] = imported.triangle_count
            report["imported_mesh_bytes"] = int(imported.vertices.nbytes + imported.indices.nbytes)
            report["import_metadata"] = metadata
        finally:
            if cleanup:
                obj_path.unlink(missing_ok=True)

    if args.decimate_percent is not None:
        _start, elapsed = timer()
        reduced = decimate_geometry(geometry, float(args.decimate_percent))
        report["decimation_ms"] = elapsed()
        report["decimated_vertices"] = reduced.vertex_count
        report["decimated_triangles"] = reduced.triangle_count
        report["decimated_mesh_bytes"] = int(reduced.vertices.nbytes + reduced.indices.nbytes)

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
