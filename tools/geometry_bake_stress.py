#!/usr/bin/env python3
"""Generate a dense reference surface and exercise the native high-to-low baker.

This is intentionally a command-line diagnostics harness rather than an app
feature.  It gives Linux and Windows packaging tests a repeatable large-mesh
scene without committing a huge OBJ to the repository.
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np

from vfx_texture_lab.geometry import GeometryData
from vfx_texture_lab.geometry_bake import _perform_bake
from vfx_texture_lab.nodes.registry import build_registry


def grid_surface(subdivisions: int, *, detailed: bool, name: str) -> GeometryData:
    subdivisions = max(int(subdivisions), 1)
    columns = subdivisions + 1
    coordinate = np.linspace(-1.0, 1.0, columns, dtype=np.float32)
    xx, yy = np.meshgrid(coordinate, coordinate)
    if detailed:
        zz = (
            0.05
            + 0.025 * np.sin(xx * math.pi * 7.0) * np.cos(yy * math.pi * 5.0)
            + 0.010 * np.sin((xx + yy) * math.pi * 19.0)
        ).astype(np.float32)
        dzdx = (
            0.025 * math.pi * 7.0 * np.cos(xx * math.pi * 7.0) * np.cos(yy * math.pi * 5.0)
            + 0.010 * math.pi * 19.0 * np.cos((xx + yy) * math.pi * 19.0)
        )
        dzdy = (
            -0.025 * math.pi * 5.0 * np.sin(xx * math.pi * 7.0) * np.sin(yy * math.pi * 5.0)
            + 0.010 * math.pi * 19.0 * np.cos((xx + yy) * math.pi * 19.0)
        )
        normals = np.stack((-dzdx, -dzdy, np.ones_like(zz)), axis=2)
        normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1.0e-8)
    else:
        zz = np.zeros_like(xx)
        normals = np.zeros((*xx.shape, 3), dtype=np.float32)
        normals[..., 2] = 1.0
    positions = np.stack((xx, yy, zz), axis=2)
    uv = np.stack(((xx + 1.0) * 0.5, (yy + 1.0) * 0.5), axis=2)
    vertices = np.concatenate((positions, normals.astype(np.float32), uv), axis=2).reshape(-1, 8)

    row = np.arange(subdivisions, dtype=np.uint32)[:, None] * columns
    column = np.arange(subdivisions, dtype=np.uint32)[None, :]
    top_left = row + column
    top_right = top_left + 1
    bottom_left = top_left + columns
    bottom_right = bottom_left + 1
    faces = np.stack(
        (
            np.stack((top_left, bottom_right, top_right), axis=2),
            np.stack((top_left, bottom_left, bottom_right), axis=2),
        ),
        axis=2,
    ).reshape(-1, 3)
    return GeometryData(vertices, faces.astype(np.uint32, copy=False).reshape(-1), name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--high-subdivisions", type=int, default=708,
                        help="Grid cells per side; 708 produces 1,002,528 triangles.")
    parser.add_argument("--low-subdivisions", type=int, default=32)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--ao", action="store_true", help="Also run Draft ambient occlusion.")
    args = parser.parse_args()

    started = time.perf_counter()
    high = grid_surface(args.high_subdivisions, detailed=True, name="Stress High")
    low = grid_surface(args.low_subdivisions, detailed=False, name="Stress Low")
    source = np.ones((1024, 1024, 4), dtype=np.float32)
    source[..., 0] = np.linspace(0.1, 0.9, 1024, dtype=np.float32)[None, :]
    source[..., 1] = np.linspace(0.9, 0.1, 1024, dtype=np.float32)[:, None]
    source[..., 2] = 0.35

    definition = build_registry().get("geometry.bake_high_to_low")
    parameters = definition.default_parameters()
    parameters.update({
        "resolution": max(64, min(int(args.resolution), 4096)),
        "supersampling": "1x",
        "bake_ambient_occlusion": bool(args.ao),
        "projection_mode": "Bidirectional Normals",
        "distance_mode": "Automatic",
        "name": "Stress Bake",
    })
    result = _perform_bake(high, low, source, None, parameters, None)
    report = {
        "high_vertices": high.vertex_count,
        "high_triangles": high.triangle_count,
        "low_vertices": low.vertex_count,
        "low_triangles": low.triangle_count,
        "maps": list(result.maps),
        "backend": result.diagnostics.get("backend"),
        "hit_percent": result.diagnostics.get("hit_percent"),
        "bake_elapsed_ms": result.diagnostics.get("elapsed_ms"),
        "wall_elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "result_memory_bytes": result.memory_bytes,
        "estimated_working_memory_bytes": result.diagnostics.get("estimated_working_memory_bytes"),
        "warnings": result.diagnostics.get("warnings", []),
    }
    print(json.dumps(report, indent=2))
    if "Embree" not in str(report["backend"]):
        raise SystemExit("Stress run did not use the native Embree backend")
    if float(report["hit_percent"] or 0.0) < 99.0:
        raise SystemExit("Stress run had unexpected projection misses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
