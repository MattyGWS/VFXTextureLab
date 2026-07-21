from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.evaluator import (
    GraphEvaluator,
    GraphSnapshot,
    SnapshotNode,
    _prepare_cpu_preview_rgba8,
)
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.engine.resources import CpuImage
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.preview import PreviewPanel


def reference_image(width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    u = (x.astype(np.float32) + 0.5) / width
    v = (y.astype(np.float32) + 0.5) / height
    return np.stack((u, v, 0.25 + 0.5 * u * v, np.ones_like(u)), axis=2).astype(np.float32)


def assert_cpu_display_preparation() -> None:
    source = reference_image(257, 193)
    prepared = _prepare_cpu_preview_rgba8(source, 91, 67, "color")
    assert prepared.shape == (67, 89, 4) or prepared.shape == (67, 91, 4)
    # Width/height are independently capped, not aspect-corrected inside the
    # low-level helper. This call requests exactly 91 x 67.
    assert prepared.shape == (67, 91, 4)
    assert prepared.dtype == np.uint8
    assert np.all(prepared[..., 3] == 255)

    grayscale = _prepare_cpu_preview_rgba8(source, 64, 48, "grayscale")
    assert np.array_equal(grayscale[..., 0], grayscale[..., 1])
    assert np.array_equal(grayscale[..., 1], grayscale[..., 2])


def assert_evaluator_returns_view_sized_pixels() -> None:
    registry = build_registry()
    definition = registry.get("generator.linear_gradient")
    node = SnapshotNode(
        "gradient",
        definition,
        definition.default_parameters(),
        tuple(definition.inputs),
        (),
        "grayscale",
    )
    snapshot = GraphSnapshot({"gradient": node}, {})
    evaluator = GraphEvaluator(backend_preference="cpu")
    result = evaluator.evaluate_snapshot(
        snapshot,
        "gradient",
        256,
        192,
        precision=TextureFormat.R16F,
        prepare_display=True,
        display_width=96,
        display_height=72,
    )
    assert result.error is None
    assert result.image is None
    assert result.display_rgba is not None
    assert result.display_rgba.shape == (72, 96, 4)
    assert result.display_rgba.dtype == np.uint8
    assert (result.source_width, result.source_height) == (256, 192)


def assert_gpu_preparation_matches_cpu() -> None:
    gpu = WgpuBackend()
    if not gpu.available:
        print("GPU preview comparison skipped:", gpu.info().detail)
        return
    source = reference_image(211, 157)
    cpu = _prepare_cpu_preview_rgba8(source, 83, 61, "color")
    resource = CpuImage(
        source,
        TextureFormat.RGBA16F,
        "preview-reference",
        frozenset({"cpu"}),
        "color",
        "16-bit",
    )
    uploaded = gpu.ensure_gpu(resource, RenderContext(211, 157, TextureFormat.RGBA16F))
    prepared = gpu.prepare_preview_rgba8(uploaded, 83, 61, "color")
    delta = np.abs(prepared.astype(np.int16) - cpu.astype(np.int16))
    assert int(delta.max()) <= 2, int(delta.max())


def assert_preview_panel_uses_prepared_pixels() -> None:
    app = QApplication.instance() or QApplication([])
    panel = PreviewPanel()
    panel.resize(900, 700)
    panel.show()
    app.processEvents()
    width, height = panel.recommended_render_size(2048, 1024)
    assert (width, height) == (2048, 1024)
    # Preview Max is now a truthful quality control: lower authored previews
    # remain lower resolution rather than being enlarged into the same hidden
    # display footprint.
    low_width, low_height = panel.recommended_render_size(512, 256)
    assert (low_width, low_height) == (512, 256)

    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = 180
    rgba[..., 3] = 255
    panel.set_result("Prepared", None, None, 2048, 1024, display_rgba=rgba, data_kind="color")
    app.processEvents()
    assert panel.display_image.width() == width
    assert panel.display_image.height() == height
    panel.channel_buttons["R"].setChecked(False)
    app.processEvents()
    assert panel.display_image.pixelColor(0, 0).red() == 0
    panel.close()


def main() -> None:
    assert_cpu_display_preparation()
    assert_evaluator_returns_view_sized_pixels()
    assert_gpu_preparation_matches_cpu()
    assert_preview_panel_uses_prepared_pixels()
    print("GPU-prepared 2D preview/readback test passed")


if __name__ == "__main__":
    main()
