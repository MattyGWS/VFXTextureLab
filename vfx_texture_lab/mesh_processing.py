"""High-poly mesh diagnostics and native simplification helpers.

The public graph geometry value stores one position/normal/UV tuple per indexed
vertex.  Attribute seams therefore duplicate positions, while a mesh reducer
must treat those copies as one topological point or the copies can drift apart
and open visible cracks.  This module builds a welded *geometric* topology for
simplification, then restores UV and hard-normal splits after the native QEM
collapse sequence has finished.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import threading
from typing import Any, Callable

import numpy as np

try:  # Installed by setup.sh/setup.bat and bundled by the Windows build.
    import fast_simplification as _fast_simplification
except Exception:  # pragma: no cover - exercised by fallback-only environments.
    _fast_simplification = None


CancelCheck = Callable[[], bool] | None
ProgressCallback = Callable[[int, int, str], None] | None


class NativeSimplificationUnavailable(RuntimeError):
    pass


class NativeSimplificationCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MeshDiagnostics:
    vertex_count: int
    triangle_count: int
    unique_position_count: int
    boundary_edges: int
    non_manifold_edges: int
    degenerate_triangles: int
    duplicate_triangles: int
    connected_components: int
    uv_seam_vertices: int
    hard_normal_seam_vertices: int
    bytes_used: int

    @property
    def closed_manifold(self) -> bool:
        return (
            self.triangle_count > 0
            and self.boundary_edges == 0
            and self.non_manifold_edges == 0
            and self.degenerate_triangles == 0
        )

    def as_metadata(self, prefix: str = "") -> dict[str, Any]:
        key = (lambda name: f"{prefix}{name}" if prefix else name)
        return {
            key("vertex_count"): self.vertex_count,
            key("triangle_count"): self.triangle_count,
            key("unique_position_count"): self.unique_position_count,
            key("boundary_edges"): self.boundary_edges,
            key("non_manifold_edges"): self.non_manifold_edges,
            key("degenerate_triangles"): self.degenerate_triangles,
            key("duplicate_triangles"): self.duplicate_triangles,
            key("connected_components"): self.connected_components,
            key("uv_seam_vertices"): self.uv_seam_vertices,
            key("hard_normal_seam_vertices"): self.hard_normal_seam_vertices,
            key("memory_bytes"): self.bytes_used,
            key("closed_manifold"): self.closed_manifold,
        }


@dataclass(slots=True)
class _Topology:
    points: np.ndarray
    faces: np.ndarray
    raw_to_topology: np.ndarray
    source_triangles: np.ndarray
    source_topology_faces: np.ndarray
    source_uvs: np.ndarray
    source_normals: np.ndarray
    hard_signatures: np.ndarray
    diagnostics: MeshDiagnostics

    @property
    def bytes_used(self) -> int:
        return int(
            self.points.nbytes
            + self.faces.nbytes
            + self.raw_to_topology.nbytes
            + self.source_triangles.nbytes
            + self.source_topology_faces.nbytes
            + self.source_uvs.nbytes
            + self.source_normals.nbytes
            + self.hard_signatures.nbytes
        )


@dataclass(slots=True)
class _SimplificationPlan:
    key: str
    topology: _Topology
    collapses: np.ndarray
    endpoint_points: np.ndarray
    endpoint_faces: np.ndarray
    endpoint_face_count: int
    aggression: float

    @property
    def bytes_used(self) -> int:
        return int(
            self.topology.bytes_used
            + self.collapses.nbytes
            + self.endpoint_points.nbytes
            + self.endpoint_faces.nbytes
        )


_PLAN_CACHE: "OrderedDict[str, _SimplificationPlan]" = OrderedDict()
_PLAN_CACHE_LOCK = threading.RLock()
_PLAN_CACHE_BUDGET = 768 * 1024 * 1024


def native_simplification_available() -> bool:
    return _fast_simplification is not None


def _checkpoint(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        raise NativeSimplificationCancelled("Geometry simplification was cancelled")


def _emit(progress: ProgressCallback, current: int, total: int, message: str) -> None:
    if progress is not None:
        progress(int(current), int(total), str(message))


def _position_topology(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weld bit-identical positions without merging merely nearby surfaces."""

    points = np.ascontiguousarray(positions, dtype=np.float32).reshape(-1, 3)
    if not points.size:
        return points.astype(np.float64), np.empty((0,), dtype=np.int64)
    # Viewing float bits avoids NaN/rounding surprises and preserves exact OBJ
    # seam copies. GeometryData has already rejected non-finite values.
    bits = points.view(np.uint32).reshape(-1, 3)
    _unique, first, inverse = np.unique(
        bits, axis=0, return_index=True, return_inverse=True
    )
    welded = np.ascontiguousarray(points[first], dtype=np.float64)
    return welded, np.ascontiguousarray(inverse, dtype=np.int64)


def _canonical_triangle_keys(triangles: np.ndarray) -> np.ndarray:
    rows = np.sort(np.ascontiguousarray(triangles, dtype=np.int64), axis=1)
    dtype = np.dtype([("a", np.int64), ("b", np.int64), ("c", np.int64)])
    return rows.view(dtype).reshape(-1)


def _edge_statistics(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not faces.size:
        return (
            np.empty((0, 2), dtype=np.int64),
            np.empty((0,), dtype=np.int64),
            np.empty((0,), dtype=np.int64),
        )
    edges = np.concatenate(
        (faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]), axis=0
    )
    edges = np.sort(edges, axis=1)
    unique, inverse, counts = np.unique(
        edges, axis=0, return_inverse=True, return_counts=True
    )
    return unique, inverse, counts


def _closed_geometric_faces(faces: np.ndarray) -> bool:
    """Return whether triangle indices form a closed two-manifold surface.

    This deliberately inspects the welded geometric index buffer produced by
    the native reducer, before UV and hard-normal copies are restored.  It is
    therefore both cheaper and more precise than rebuilding the full public
    GeometryData payload merely to decide whether a collapse opened a crack.
    """

    triangles = np.ascontiguousarray(faces, dtype=np.int64).reshape(-1, 3)
    if triangles.shape[0] == 0:
        return False
    distinct = (
        (triangles[:, 0] != triangles[:, 1])
        & (triangles[:, 1] != triangles[:, 2])
        & (triangles[:, 2] != triangles[:, 0])
    )
    if not bool(np.all(distinct)):
        return False
    # Duplicate geometric triangles necessarily make each of their three
    # undirected edges occur more than twice, so the edge-count test below also
    # rejects them without a second large sort over the triangle array.
    _edges, _inverse, counts = _edge_statistics(triangles)
    return counts.size > 0 and bool(np.all(counts == 2))


def _component_count(vertex_count: int, edges: np.ndarray, cancel_check: CancelCheck = None) -> int:
    if vertex_count <= 0:
        return 0
    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.uint8)

    def find(value: int) -> int:
        root = value
        while parent[root] != root:
            root = int(parent[root])
        while parent[value] != value:
            next_value = int(parent[value])
            parent[value] = root
            value = next_value
        return root

    # Diagnostics are normally run once on import or after decimation. This
    # compact union-find is considerably cheaper than materialising adjacency
    # lists for million-triangle scans.
    for edge_index, (a_raw, b_raw) in enumerate(edges):
        if (edge_index & 0xFFFF) == 0:
            _checkpoint(cancel_check)
        a = find(int(a_raw))
        b = find(int(b_raw))
        if a == b:
            continue
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1
    _checkpoint(cancel_check)
    for index in range(vertex_count):
        if (index & 0xFFFF) == 0:
            _checkpoint(cancel_check)
        parent[index] = find(index)
    return int(np.unique(parent).size)


def _attribute_seam_counts(
    raw_to_topology: np.ndarray,
    uvs: np.ndarray,
    normals: np.ndarray,
    topology_count: int,
) -> tuple[int, int, np.ndarray]:
    if raw_to_topology.size == 0:
        return 0, 0, np.empty((0, 3), dtype=np.int16)

    duplicate_counts = np.bincount(raw_to_topology, minlength=topology_count)
    duplicate_groups = duplicate_counts > 1

    uv_bits = np.ascontiguousarray(uvs, dtype=np.float32).view(np.uint32).reshape(-1, 2)
    uv_rows = np.column_stack((raw_to_topology, uv_bits.astype(np.int64, copy=False)))
    uv_unique = np.unique(uv_rows, axis=0)
    uv_variants = np.bincount(uv_unique[:, 0], minlength=topology_count)
    uv_groups = duplicate_groups & (uv_variants > 1)
    uv_seam_vertices = int(duplicate_counts[uv_groups].sum())

    normal_values = np.ascontiguousarray(normals, dtype=np.float32)
    normal_lengths = np.linalg.norm(normal_values, axis=1, keepdims=True)
    normal_values = normal_values / np.maximum(normal_lengths, 1.0e-8)
    normal_sum = np.zeros((topology_count, 3), dtype=np.float64)
    np.add.at(normal_sum, raw_to_topology, normal_values.astype(np.float64))
    average_lengths = np.linalg.norm(normal_sum, axis=1, keepdims=True)
    average = normal_sum / np.maximum(average_lengths, 1.0e-12)
    alignment = np.einsum("ij,ij->i", normal_values, average[raw_to_topology])
    minimum_alignment = np.ones((topology_count,), dtype=np.float64)
    np.minimum.at(minimum_alignment, raw_to_topology, alignment)
    hard_groups = duplicate_groups & (minimum_alignment < 0.94)
    hard_normal_seam_vertices = int(duplicate_counts[hard_groups].sum())

    # Only genuine hard-split groups get a signature. Smooth normals remain in
    # one shading group even when UV seams duplicate their vertices.
    quantised = np.rint(np.clip(normal_values, -1.0, 1.0) * 2047.0).astype(np.int16)
    signatures = np.zeros_like(quantised)
    signatures[hard_groups[raw_to_topology]] = quantised[hard_groups[raw_to_topology]]
    return uv_seam_vertices, hard_normal_seam_vertices, signatures


def build_topology(
    vertices: np.ndarray,
    indices: np.ndarray,
    *,
    cancel_check: CancelCheck = None,
    progress_callback: ProgressCallback = None,
) -> _Topology:
    _checkpoint(cancel_check)
    _emit(progress_callback, 1, 7, "Welding attribute seams for geometric topology")
    raw_vertices = np.ascontiguousarray(vertices, dtype=np.float32).reshape(-1, 8)
    source_triangles = np.ascontiguousarray(indices, dtype=np.uint32).reshape(-1, 3)
    points, raw_to_topology = _position_topology(raw_vertices[:, :3])
    _checkpoint(cancel_check)

    source_topology_faces = raw_to_topology[source_triangles]
    distinct = (
        (source_topology_faces[:, 0] != source_topology_faces[:, 1])
        & (source_topology_faces[:, 1] != source_topology_faces[:, 2])
        & (source_topology_faces[:, 2] != source_topology_faces[:, 0])
    )
    valid_faces = np.ascontiguousarray(source_topology_faces[distinct], dtype=np.int64)
    degenerate_count = int(source_topology_faces.shape[0] - valid_faces.shape[0])

    _emit(progress_callback, 2, 7, "Removing duplicate geometric triangles")
    if valid_faces.size:
        keys = _canonical_triangle_keys(valid_faces)
        _unique_keys, first = np.unique(keys, return_index=True)
        first.sort()
        faces = np.ascontiguousarray(valid_faces[first], dtype=np.int64)
        duplicate_count = int(valid_faces.shape[0] - faces.shape[0])
    else:
        faces = np.empty((0, 3), dtype=np.int64)
        duplicate_count = 0
    _checkpoint(cancel_check)

    _emit(progress_callback, 3, 7, "Inspecting manifold edges")
    edges, _edge_inverse, edge_counts = _edge_statistics(faces)
    boundary_edges = int(np.count_nonzero(edge_counts == 1))
    non_manifold_edges = int(np.count_nonzero(edge_counts > 2))
    _checkpoint(cancel_check)

    _emit(progress_callback, 4, 7, "Inspecting UV and normal seams")
    uv_seams, hard_seams, hard_signatures = _attribute_seam_counts(
        raw_to_topology,
        raw_vertices[:, 6:8],
        raw_vertices[:, 3:6],
        points.shape[0],
    )
    _checkpoint(cancel_check)

    _emit(progress_callback, 5, 7, "Counting connected mesh components")
    # Union-find over every edge can be noticeable on giant meshes. It remains
    # cancellable and runs off the UI thread in VFX Texture Lab 0.51.3.
    components = _component_count(points.shape[0], edges, cancel_check)
    _checkpoint(cancel_check)

    diagnostics = MeshDiagnostics(
        vertex_count=int(raw_vertices.shape[0]),
        triangle_count=int(source_triangles.shape[0]),
        unique_position_count=int(points.shape[0]),
        boundary_edges=boundary_edges,
        non_manifold_edges=non_manifold_edges,
        degenerate_triangles=degenerate_count,
        duplicate_triangles=duplicate_count,
        connected_components=components,
        uv_seam_vertices=uv_seams,
        hard_normal_seam_vertices=hard_seams,
        bytes_used=int(raw_vertices.nbytes + source_triangles.nbytes),
    )
    _emit(progress_callback, 6, 7, "Mesh diagnostics complete")
    return _Topology(
        points=points,
        faces=faces,
        raw_to_topology=raw_to_topology,
        source_triangles=source_triangles,
        source_topology_faces=np.ascontiguousarray(source_topology_faces, dtype=np.int64),
        source_uvs=np.ascontiguousarray(raw_vertices[:, 6:8], dtype=np.float32),
        source_normals=np.ascontiguousarray(raw_vertices[:, 3:6], dtype=np.float32),
        hard_signatures=hard_signatures,
        diagnostics=diagnostics,
    )


def diagnose_mesh(
    vertices: np.ndarray,
    indices: np.ndarray,
    *,
    cancel_check: CancelCheck = None,
    progress_callback: ProgressCallback = None,
) -> MeshDiagnostics:
    return build_topology(
        vertices,
        indices,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    ).diagnostics


def _geometry_key(vertices: np.ndarray, indices: np.ndarray) -> str:
    digest = hashlib.blake2b(digest_size=20)
    # UV/normal edits do not change QEM topology, but they do change how the
    # cached collapse sequence must restore split attributes. Include the full
    # vertex payload so replay never returns stale seams or shading.
    vertex_data = np.ascontiguousarray(vertices, dtype=np.float32)
    digest.update(memoryview(vertex_data).cast("B"))
    digest.update(memoryview(np.ascontiguousarray(indices, dtype=np.uint32)).cast("B"))
    return digest.hexdigest()


def _cache_get(key: str) -> _SimplificationPlan | None:
    with _PLAN_CACHE_LOCK:
        value = _PLAN_CACHE.get(key)
        if value is not None:
            _PLAN_CACHE.move_to_end(key)
        return value


def _cache_put(plan: _SimplificationPlan) -> None:
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE[plan.key] = plan
        _PLAN_CACHE.move_to_end(plan.key)
        total = sum(item.bytes_used for item in _PLAN_CACHE.values())
        while total > _PLAN_CACHE_BUDGET and len(_PLAN_CACHE) > 1:
            _key, removed = _PLAN_CACHE.popitem(last=False)
            total -= removed.bytes_used


def clear_simplification_cache() -> None:
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE.clear()


def _native_simplify(
    points: np.ndarray,
    faces: np.ndarray,
    target_count: int,
    aggression: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _fast_simplification is None:
        raise NativeSimplificationUnavailable(
            "fast-simplification is not installed; run setup.sh or setup.bat again"
        )
    target_count = max(1, min(int(target_count), int(faces.shape[0])))
    # The native simplify entry point is double-precision, while its replay
    # entry point deliberately uses float32.  Keep the conversion boundary
    # explicit here rather than relying on the wrapper to reinterpret whatever
    # dtype the graph topology happens to use.
    native_points = np.ascontiguousarray(points, dtype=np.float64).reshape(-1, 3)
    native_faces = np.ascontiguousarray(faces, dtype=np.int32).reshape(-1, 3)
    kwargs = {
        "target_count": target_count,
        "agg": float(aggression),
        "return_collapses": True,
    }
    try:
        result = _fast_simplification.simplify(native_points, native_faces, **kwargs)
    except TypeError:
        # Compatibility with older wrappers that exposed reduction positionally.
        reduction = max(0.0, min(1.0, 1.0 - target_count / max(faces.shape[0], 1)))
        result = _fast_simplification.simplify(
            native_points,
            native_faces,
            reduction,
            agg=float(aggression),
            return_collapses=True,
        )
    out_points, out_faces, collapses = result
    return (
        np.ascontiguousarray(out_points, dtype=np.float64).reshape(-1, 3),
        np.ascontiguousarray(out_faces, dtype=np.int64).reshape(-1, 3),
        np.ascontiguousarray(collapses, dtype=np.int32).reshape(-1, 2),
    )


def _replay(
    topology: _Topology, collapses: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _fast_simplification is None:
        raise NativeSimplificationUnavailable(
            "fast-simplification is not installed; run setup.sh or setup.bat again"
        )
    # fast-simplification's replay Cython bridge expects float32 points and
    # int32 collapses (unlike simplify(), which expects float64 points).  Passing
    # the cached float64 topology directly raises "expected 'float' but got
    # 'double'" even though the package is installed correctly.
    replay_points = np.ascontiguousarray(topology.points, dtype=np.float32).reshape(-1, 3)
    replay_faces = np.ascontiguousarray(topology.faces, dtype=np.int32).reshape(-1, 3)
    replay_collapses = np.ascontiguousarray(collapses, dtype=np.int32).reshape(-1, 2)
    result = _fast_simplification.replay_simplification(
        points=replay_points,
        triangles=replay_faces,
        collapses=replay_collapses,
    )
    out_points, out_faces, mapping = result
    return (
        np.ascontiguousarray(out_points, dtype=np.float64).reshape(-1, 3),
        np.ascontiguousarray(out_faces, dtype=np.int64).reshape(-1, 3),
        np.ascontiguousarray(mapping, dtype=np.int64).reshape(-1),
    )


def _plan_for_target(
    vertices: np.ndarray,
    indices: np.ndarray,
    target_count: int,
    *,
    aggression: float,
    cancel_check: CancelCheck,
    progress_callback: ProgressCallback,
) -> _SimplificationPlan:
    key = _geometry_key(vertices, indices)
    cached = _cache_get(key)
    if cached is not None and cached.endpoint_face_count <= target_count:
        _emit(progress_callback, 2, 6, "Reusing cached native collapse sequence")
        return cached

    _checkpoint(cancel_check)
    topology = cached.topology if cached is not None else build_topology(
        vertices,
        indices,
        cancel_check=cancel_check,
        progress_callback=(
            (lambda current, total, message: _emit(
                progress_callback, 1, 6, f"{message} ({current}/{total})"
            ))
            if progress_callback is not None
            else None
        ),
    )
    if topology.faces.shape[0] <= 1:
        return _SimplificationPlan(
            key,
            topology,
            np.empty((0, 2), dtype=np.int64),
            topology.points,
            topology.faces,
            int(topology.faces.shape[0]),
            aggression,
        )

    # Build some look-ahead into the sequence. Nearby slider changes can then
    # replay a prefix instead of restarting native QEM from the high-poly mesh.
    endpoint_target = max(
        1,
        min(
            target_count,
            max(int(round(target_count * 0.5)), int(round(topology.faces.shape[0] * 0.01))),
        ),
    )
    _emit(progress_callback, 2, 6, "Native quadric simplification")
    endpoint_points, endpoint_faces, collapses = _native_simplify(
        topology.points,
        topology.faces,
        endpoint_target,
        aggression,
    )
    plan = _SimplificationPlan(
        key=key,
        topology=topology,
        collapses=collapses,
        endpoint_points=endpoint_points,
        endpoint_faces=endpoint_faces,
        endpoint_face_count=int(endpoint_faces.shape[0]),
        aggression=aggression,
    )
    # A superseded request may have spent most of its time inside the native
    # call, where cooperative cancellation is impossible. Keep that valid work
    # before honouring cancellation so the newest queued slider value can replay
    # the collapse sequence instead of starting from the scan again.
    _cache_put(plan)
    _checkpoint(cancel_check)
    return plan


def _replay_near_target(
    plan: _SimplificationPlan,
    target_count: int,
    *,
    cancel_check: CancelCheck,
    progress_callback: ProgressCallback,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    topology = plan.topology
    original_count = int(topology.faces.shape[0])
    if target_count >= original_count or plan.collapses.size == 0:
        mapping = np.arange(topology.points.shape[0], dtype=np.int64)
        return topology.points.copy(), topology.faces.copy(), mapping, 0
    if target_count <= plan.endpoint_face_count:
        points, faces, mapping = _replay(topology, plan.collapses)
        return points, faces, mapping, int(plan.collapses.shape[0])

    collapse_total = int(plan.collapses.shape[0])
    denominator = max(original_count - plan.endpoint_face_count, 1)
    fraction = (original_count - target_count) / denominator
    estimate = int(round(np.clip(fraction, 0.0, 1.0) * collapse_total))
    estimate = max(0, min(estimate, collapse_total))

    best: tuple[np.ndarray, np.ndarray, np.ndarray, int] | None = None
    best_delta = original_count
    low = 0
    high = collapse_total
    probe = estimate
    # Native replay is substantially faster than recomputing QEM. Four probes
    # are enough to correct the near-linear face/collapse estimate while keeping
    # million-triangle interactive changes responsive.
    for iteration in range(4):
        _checkpoint(cancel_check)
        _emit(progress_callback, 3 + iteration, 8, "Replaying cached collapse sequence")
        points, faces, mapping = _replay(topology, plan.collapses[:probe])
        count = int(faces.shape[0])
        if count >= target_count and count - target_count < best_delta:
            best = (points, faces, mapping, probe)
            best_delta = count - target_count
        if count > target_count:
            low = max(low, probe + 1)
        elif count < target_count:
            high = min(high, probe - 1)
        else:
            return points, faces, mapping, probe
        if low > high:
            break
        probe = (low + high) // 2

    if best is not None:
        return best
    # A one-step overshoot can happen because a manifold edge collapse removes
    # two triangles. Prefer the closest result over returning the unreduced mesh.
    return points, faces, mapping, probe


def _back_off_to_closed_manifold(
    plan: _SimplificationPlan,
    target_count: int,
    invalid_collapse_count: int,
    *,
    cancel_check: CancelCheck,
    progress_callback: ProgressCallback,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Find the closest earlier native replay that remains watertight.

    ``fast-simplification`` is extremely quick, but its collapse sequence does
    not guarantee that every prefix preserves manifoldness.  Throwing away the
    entire native result and running the Python compatibility reducer made one
    unfortunate collapse turn into a very slow node.  Instead we retreat along
    the already-cached collapse sequence and keep the latest safe prefix.
    """

    topology = plan.topology
    invalid_collapse_count = max(
        1, min(int(invalid_collapse_count), int(plan.collapses.shape[0]))
    )
    known_invalid = invalid_collapse_count
    step = max(1, invalid_collapse_count // 16)
    known_valid = 0
    valid_result = (
        topology.points.copy(),
        topology.faces.copy(),
        np.arange(topology.points.shape[0], dtype=np.int64),
        0,
    )

    # Exponential retreat finds a valid bracket quickly even if the first bad
    # collapse occurred much earlier than the requested target.
    probe = max(0, known_invalid - step)
    for iteration in range(6):
        _checkpoint(cancel_check)
        _emit(
            progress_callback,
            iteration + 1,
            12,
            "Protecting closed-manifold topology",
        )
        if probe == 0:
            known_valid = 0
            break
        points, faces, mapping = _replay(topology, plan.collapses[:probe])
        if _closed_geometric_faces(faces):
            known_valid = probe
            valid_result = (points, faces, mapping, probe)
            break
        known_invalid = probe
        step *= 2
        probe = max(0, known_invalid - step)

    # Refine the bracket. Validity is expected to be monotonic for an edge
    # collapse stream; five probes are enough to stay close to the requested
    # triangle count without making rare repair paths expensive on scan meshes.
    for iteration in range(5):
        _checkpoint(cancel_check)
        if known_valid + 1 >= known_invalid:
            break
        probe = (known_valid + known_invalid) // 2
        _emit(
            progress_callback,
            8 + iteration,
            14,
            "Finding nearest watertight reduction",
        )
        points, faces, mapping = _replay(topology, plan.collapses[:probe])
        if _closed_geometric_faces(faces):
            known_valid = probe
            valid_result = (points, faces, mapping, probe)
        else:
            known_invalid = probe

    # Fewer collapses always mean at least as many triangles. The result may
    # therefore stop above the requested percentage, which is preferable to a
    # cracked mesh or a multi-second compatibility fallback.
    if int(valid_result[1].shape[0]) < int(target_count):
        return (
            topology.points.copy(),
            topology.faces.copy(),
            np.arange(topology.points.shape[0], dtype=np.int64),
            0,
        )
    return valid_result


def _source_face_lookup(
    mapped_source_faces: np.ndarray,
    output_faces: np.ndarray,
) -> np.ndarray:
    valid = (
        (mapped_source_faces[:, 0] != mapped_source_faces[:, 1])
        & (mapped_source_faces[:, 1] != mapped_source_faces[:, 2])
        & (mapped_source_faces[:, 2] != mapped_source_faces[:, 0])
    )
    source_ids = np.flatnonzero(valid)
    if source_ids.size == 0:
        return np.full((output_faces.shape[0],), -1, dtype=np.int64)
    source_keys = _canonical_triangle_keys(mapped_source_faces[valid])
    order = np.argsort(source_keys, kind="stable")
    sorted_keys = source_keys[order]
    sorted_ids = source_ids[order]
    unique_keys, first = np.unique(sorted_keys, return_index=True)
    unique_ids = sorted_ids[first]
    output_keys = _canonical_triangle_keys(output_faces)
    locations = np.searchsorted(unique_keys, output_keys)
    found = locations < unique_keys.shape[0]
    found_indices = np.flatnonzero(found)
    if found_indices.size:
        exact = unique_keys[locations[found_indices]] == output_keys[found_indices]
        found[found_indices] = exact
    result = np.full((output_faces.shape[0],), -1, dtype=np.int64)
    result[found] = unique_ids[locations[found]]
    return result


def _rebuild_attributes(
    topology: _Topology,
    output_points: np.ndarray,
    output_faces: np.ndarray,
    mapping: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    mapped_source_faces = mapping[topology.source_topology_faces]
    source_face_ids = _source_face_lookup(mapped_source_faces, output_faces)

    # Native QEM only collapses existing edges, so every surviving output face
    # should have a source face. A defensive nearest-corner fallback keeps a
    # damaged third-party mesh visible rather than producing an empty result.
    missing = source_face_ids < 0
    if np.any(missing):
        source_face_ids[missing] = 0

    source_triangles = topology.source_triangles[source_face_ids]
    source_mapped = mapping[topology.raw_to_topology[source_triangles]]
    corner_source = np.empty_like(source_triangles, dtype=np.int64)
    for corner in range(3):
        target = output_faces[:, corner][:, None]
        matches = source_mapped == target
        choice = np.argmax(matches, axis=1)
        corner_source[:, corner] = np.take_along_axis(
            source_triangles, choice[:, None], axis=1
        )[:, 0]

    # Area-weighted normals are accumulated by geometric output point. UV seam
    # copies therefore shade continuously, while genuine hard-normal groups get
    # their own accumulator.
    p = output_points[output_faces]
    face_normals = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    hard = topology.hard_signatures[corner_source]
    output_corner_ids = output_faces.reshape(-1)
    hard_flat = hard.reshape(-1, 3).astype(np.int64, copy=False)
    normal_keys = np.column_stack((output_corner_ids, hard_flat))
    unique_normal_keys, normal_inverse = np.unique(
        normal_keys, axis=0, return_inverse=True
    )
    normal_accum = np.zeros((unique_normal_keys.shape[0], 3), dtype=np.float64)
    np.add.at(normal_accum, normal_inverse, np.repeat(face_normals, 3, axis=0))
    lengths = np.linalg.norm(normal_accum, axis=1, keepdims=True)
    normals = normal_accum / np.maximum(lengths, 1.0e-12)
    zero = lengths[:, 0] <= 1.0e-12
    normals[zero] = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)

    corner_uvs = topology.source_uvs[corner_source].reshape(-1, 2)
    uv_bits = np.ascontiguousarray(corner_uvs, dtype=np.float32).view(np.uint32).reshape(-1, 2)
    vertex_keys = np.column_stack((normal_inverse.astype(np.int64), uv_bits.astype(np.int64)))
    unique_vertex_keys, first, vertex_inverse = np.unique(
        vertex_keys, axis=0, return_index=True, return_inverse=True
    )
    del unique_vertex_keys
    first_output_corner = output_corner_ids[first]
    first_normal_group = normal_inverse[first]
    rebuilt_vertices = np.concatenate(
        (
            output_points[first_output_corner].astype(np.float32),
            normals[first_normal_group].astype(np.float32),
            corner_uvs[first].astype(np.float32),
        ),
        axis=1,
    )
    rebuilt_indices = np.ascontiguousarray(vertex_inverse, dtype=np.uint32)
    return np.ascontiguousarray(rebuilt_vertices, dtype=np.float32), rebuilt_indices


def _native_decimate_pass(
    vertices: np.ndarray,
    indices: np.ndarray,
    target_count: int,
    *,
    aggression: float,
    cancel_check: CancelCheck,
    progress_callback: ProgressCallback,
) -> tuple[np.ndarray, np.ndarray, MeshDiagnostics, bool]:
    """Run one native QEM plan and return its nearest watertight result.

    A native collapse ordering is only one possible route through the mesh.  A
    particular ordering can hit a topology-breaking collapse long before the
    mesh itself has reached its true safe reduction limit.  The public
    ``native_decimate`` function therefore treats this as one *round*, accepts
    the closest watertight prefix, and may build a fresh QEM plan from that
    intermediate mesh.
    """

    raw_faces = int(np.asarray(indices).size // 3)
    target_count = max(1, min(int(target_count), max(raw_faces, 1)))
    _emit(progress_callback, 0, 8, "Preparing high-poly geometry")
    plan = _plan_for_target(
        vertices,
        indices,
        target_count,
        aggression=aggression,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    _checkpoint(cancel_check)
    points, faces, mapping, collapse_count = _replay_near_target(
        plan,
        target_count,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    _checkpoint(cancel_check)
    topology_protected = False
    if plan.topology.diagnostics.closed_manifold and not _closed_geometric_faces(faces):
        points, faces, mapping, collapse_count = _back_off_to_closed_manifold(
            plan,
            target_count,
            collapse_count,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        topology_protected = True
        if not _closed_geometric_faces(faces):
            raise RuntimeError(
                "Native simplification could not find a watertight collapse prefix"
            )
    _checkpoint(cancel_check)
    _emit(progress_callback, 7, 8, "Restoring UV seams and normals")
    rebuilt_vertices, rebuilt_indices = _rebuild_attributes(
        plan.topology, points, faces, mapping
    )
    _checkpoint(cancel_check)
    output_diagnostics = diagnose_mesh(
        rebuilt_vertices,
        rebuilt_indices,
        cancel_check=cancel_check,
        progress_callback=None,
    )
    if plan.topology.diagnostics.closed_manifold and not output_diagnostics.closed_manifold:
        raise RuntimeError(
            "Native attribute reconstruction did not remain watertight"
        )
    _emit(progress_callback, 8, 8, "Native simplification pass complete")
    return (
        rebuilt_vertices,
        rebuilt_indices,
        output_diagnostics,
        topology_protected,
    )


def native_decimate(
    vertices: np.ndarray,
    indices: np.ndarray,
    target_count: int,
    *,
    aggression: float = 4.0,
    cancel_check: CancelCheck = None,
    progress_callback: ProgressCallback = None,
) -> tuple[np.ndarray, np.ndarray, MeshDiagnostics, str, int]:
    """Simplify indexed geometry and restore attribute seams without cracks.

    Closed meshes are reduced through one or more native QEM rounds.  When a
    collapse ordering would open the surface, that round backs off to its latest
    watertight prefix, then QEM is re-planned from the accepted intermediate
    mesh while keeping the *original absolute triangle target*.  This performs
    inside one node the useful work users previously obtained by chaining many
    1% Decimate nodes, without compounding the percentage or publishing cracked
    intermediate meshes.
    """

    if _fast_simplification is None:
        raise NativeSimplificationUnavailable(
            "fast-simplification is not installed; run setup.sh or setup.bat again"
        )

    current_vertices = np.ascontiguousarray(vertices, dtype=np.float32)
    current_indices = np.ascontiguousarray(indices, dtype=np.uint32).reshape(-1)
    raw_faces = int(current_indices.size // 3)
    target_count = max(1, min(int(target_count), max(raw_faces, 1)))
    if raw_faces <= target_count:
        diagnostics = diagnose_mesh(
            current_vertices,
            current_indices,
            cancel_check=cancel_check,
            progress_callback=None,
        )
        return (
            current_vertices.copy(),
            current_indices.copy(),
            diagnostics,
            "Native QEM (pass-through)",
            0,
        )

    # Deep requests need more chances to re-plan than gentle reductions, while
    # a hard cap prevents pathological third-party meshes from looping forever.
    reduction_ratio = raw_faces / max(target_count, 1)
    max_passes = min(
        16,
        max(2, int(np.ceil(np.log2(max(reduction_ratio, 1.0)))) + 4),
    )
    pass_count = 0
    topology_protected = False
    final_diagnostics: MeshDiagnostics | None = None

    while int(current_indices.size // 3) > target_count and pass_count < max_passes:
        _checkpoint(cancel_check)
        input_count = int(current_indices.size // 3)
        round_number = pass_count + 1

        def round_progress(current: int, total: int, message: str) -> None:
            # Keep a monotonic overall bar while preserving the detailed native
            # phase message.  The final callback below always fills the bar even
            # when fewer than the maximum possible rounds were needed.
            phase = 0.0 if total <= 0 else min(max(float(current) / float(total), 0.0), 1.0)
            overall = int(round(((round_number - 1) + phase) * 1000.0))
            _emit(
                progress_callback,
                overall,
                max_passes * 1000,
                f"{message} · watertight pass {round_number}",
            )

        next_vertices, next_indices, diagnostics, protected = _native_decimate_pass(
            current_vertices,
            current_indices,
            target_count,
            aggression=aggression,
            cancel_check=cancel_check,
            progress_callback=round_progress if progress_callback is not None else None,
        )
        pass_count += 1
        output_count = int(next_indices.size // 3)
        topology_protected = topology_protected or protected

        # Accept only genuine progress.  This also prevents a topology whose
        # safe prefix is the untouched input from consuming all sixteen rounds.
        if output_count >= input_count:
            break

        current_vertices = next_vertices
        current_indices = next_indices
        final_diagnostics = diagnostics
        if output_count <= target_count:
            break

        _emit(
            progress_callback,
            pass_count * 1000,
            max_passes * 1000,
            f"Re-planning QEM from {output_count:,} watertight triangles",
        )

    if final_diagnostics is None:
        final_diagnostics = diagnose_mesh(
            current_vertices,
            current_indices,
            cancel_check=cancel_check,
            progress_callback=None,
        )

    _emit(
        progress_callback,
        max_passes * 1000,
        max_passes * 1000,
        "Geometry simplification complete",
    )
    if topology_protected and pass_count > 1:
        backend = f"Native QEM (iterative topology-protected · {pass_count} passes)"
    elif topology_protected:
        backend = "Native QEM (topology-protected)"
    elif pass_count > 1:
        backend = f"Native QEM (iterative · {pass_count} passes)"
    else:
        backend = "Native QEM (fast-simplification)"
    return (
        current_vertices,
        current_indices,
        final_diagnostics,
        backend,
        pass_count,
    )
