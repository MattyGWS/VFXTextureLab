from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.evaluator import SnapshotNode
from vfx_texture_lab.nodes import build_registry


def build_snapshot(node_count: int, disconnected: int) -> tuple[GraphSnapshot, str]:
    registry = build_registry()
    constant = registry.get("generator.constant")
    invert = registry.get("filter.invert")
    nodes: dict[str, SnapshotNode] = {}
    inputs: dict[tuple[str, str], str] = {}

    root = "root"
    nodes[root] = SnapshotNode(root, constant, constant.default_parameters())
    previous = root
    for index in range(node_count - 1):
        uid = f"chain-{index:06d}"
        nodes[uid] = SnapshotNode(uid, invert, invert.default_parameters())
        inputs[(uid, "Image")] = previous
        previous = uid
    for index in range(disconnected):
        uid = f"unused-{index:06d}"
        nodes[uid] = SnapshotNode(uid, invert, invert.default_parameters())
    return GraphSnapshot(nodes, inputs), previous


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-test VFX Texture Lab's demand-driven graph evaluator")
    parser.add_argument("--nodes", type=int, default=2000, help="reachable nodes in a deep chain")
    parser.add_argument("--disconnected", type=int, default=3000, help="extra nodes that must not be evaluated")
    parser.add_argument("--resolution", type=int, default=32)
    parser.add_argument("--backend", choices=("auto", "gpu", "cpu"), default="cpu")
    parser.add_argument("--budget", type=int, default=64, help="GPU cache budget in MiB")
    args = parser.parse_args()

    snapshot, target = build_snapshot(max(args.nodes, 1), max(args.disconnected, 0))
    evaluator = GraphEvaluator(
        backend_preference=args.backend,
        gpu_budget_mb=args.budget,
        cpu_budget_mb=max(args.budget // 2, 32),
    )

    started = time.perf_counter()
    cold = evaluator.evaluate(target, args.resolution, args.resolution, snapshot=snapshot)
    cold_time = (time.perf_counter() - started) * 1000.0
    if cold.error:
        print("FAILED:", cold.error)
        return 1

    started = time.perf_counter()
    warm = evaluator.evaluate(target, args.resolution, args.resolution, snapshot=snapshot)
    warm_time = (time.perf_counter() - started) * 1000.0
    cache = evaluator.cache_stats()

    print(f"Document nodes: {len(snapshot.nodes):,}")
    print(f"Reachable/evaluated: {cold.reachable_nodes:,}")
    print(f"Disconnected/skipped: {len(snapshot.nodes) - cold.reachable_nodes:,}")
    print(f"Cold: {cold_time:.1f} ms ({cold.backend})")
    print(f"Warm: {warm_time:.1f} ms, {warm.cache_hits:,} cache hits ({warm.backend})")
    print(
        f"CPU cache: {cache['cpu'].bytes_used / 1048576:.1f} / "
        f"{cache['cpu'].budget_bytes / 1048576:.0f} MiB, {cache['cpu'].evictions} evictions"
    )
    print(
        f"GPU cache: {cache['gpu'].bytes_used / 1048576:.1f} / "
        f"{cache['gpu'].budget_bytes / 1048576:.0f} MiB, {cache['gpu'].evictions} evictions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
