from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.engine.backends.base import BackendCancelled
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.evaluator import GraphEvaluator, SnapshotNode
from vfx_texture_lab.engine.formats import RenderContext
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext
from vfx_texture_lab.nodes.terrain import _fluvial_counts, _terrain_iterations, _thermal_iterations
from vfx_texture_lab.three_d.settings import TEXTURE_RESOLUTION_OPTIONS


class FakeQueue:
    def __init__(self) -> None:
        self.waits = 0

    def on_submitted_work_done_sync(self) -> None:
        self.waits += 1


def main() -> None:
    # Automatic quality is now based on intent, never on a 1024px threshold.
    thermal = {"quality": "Automatic", "preview_iterations": 74, "final_iterations": 92}
    flow = {"quality": "Automatic", "preview_iterations": 165, "final_iterations": 121}
    fluvial = {
        "quality": "Automatic",
        "preview_iterations": 74,
        "final_iterations": 92,
        "preview_drainage_iterations": 165,
        "final_drainage_iterations": 121,
    }
    preview_2k = EvalContext(2048, 2048, render_mode="preview")
    preview_3d = EvalContext(2048, 2048, render_mode="preview_3d")
    interactive_2k = EvalContext(2048, 2048, render_mode="interactive")
    final_2k = EvalContext(2048, 2048, render_mode="final")

    assert _thermal_iterations(thermal, preview_2k) == 74
    assert _thermal_iterations(thermal, preview_3d) == 74
    assert _thermal_iterations(thermal, interactive_2k) == 8
    assert _thermal_iterations(thermal, final_2k) == 92

    assert _terrain_iterations(flow, preview_2k, preview_default=32, final_default=128) == 165
    assert _terrain_iterations(flow, interactive_2k, preview_default=32, final_default=128) == 16
    assert _terrain_iterations(flow, final_2k, preview_default=32, final_default=128) == 121

    assert _fluvial_counts(fluvial, preview_2k) == (74, 165)
    assert _fluvial_counts(fluvial, preview_3d) == (74, 165)
    assert _fluvial_counts(fluvial, interactive_2k) == (4, 24)
    assert _fluvial_counts(fluvial, final_2k) == (92, 121)

    # Matching 2D and 3D resolutions share preview cache signatures; draft and
    # final renders remain isolated so reduced results cannot poison exact ones.
    definition = build_registry().get("terrain.thermal_erosion")
    node = SnapshotNode("erosion", definition, definition.default_parameters(), tuple(definition.inputs))
    preview_context = RenderContext(2048, 2048, render_mode="preview")
    preview_3d_context = RenderContext(2048, 2048, render_mode="preview_3d")
    interactive_context = RenderContext(2048, 2048, render_mode="interactive")
    final_context = RenderContext(2048, 2048, render_mode="final")
    preview_signature = GraphEvaluator._signature(node, [], preview_context, "gpu", False)
    assert preview_signature == GraphEvaluator._signature(node, [], preview_3d_context, "gpu", False)
    assert preview_signature != GraphEvaluator._signature(node, [], interactive_context, "gpu", False)
    assert preview_signature != GraphEvaluator._signature(node, [], final_context, "gpu", False)

    # The iterative backend waits for genuine GPU completion instead of treating
    # command submission as completed work.
    backend = object.__new__(WgpuBackend)
    backend.queue = FakeQueue()
    backend._wait_for_submitted_work(cooperative=False)
    assert backend.queue.waits == 1
    try:
        backend._wait_for_submitted_work(lambda: True, cooperative=False)
    except BackendCancelled:
        pass
    else:
        raise AssertionError("GPU wait must re-check cancellation")

    assert "2048" in TEXTURE_RESOLUTION_OPTIONS and "4096" in TEXTURE_RESOLUTION_OPTIONS
    assert "Match 2D Preview" in TEXTURE_RESOLUTION_OPTIONS
    assert build_registry().get("material.pbr").parameter_spec("texture_resolution") is None

    print(
        "erosion interactivity test passed: intent-based preview/final quality, "
        "bounded live-drag solves, shared 2D/3D preview caches, truthful GPU waits and viewport-owned 3D resolutions"
    )


if __name__ == "__main__":
    main()
