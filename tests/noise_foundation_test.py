from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.custom_nodes import CustomNodePackageManager
from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.engine.backends.cpu import CpuBackend
from vfx_texture_lab.engine.backends.wgpu_backend import WgpuBackend
from vfx_texture_lab.engine.formats import RenderContext, TextureFormat
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


CORE_IDS = (
    "noise.value",
    "noise.perlin",
    "noise.fractal",
    "noise.simplex",
    "org.vfxtexturelab.voronoi_noise",
    "noise.worley",
    "noise.white",
    "noise.gaussian",
)
VARIATION_IDS = (
    "noise.ridged",
    "noise.billow",
    "noise.turbulence",
    "noise.voronoi_fractal",
)


def seam_ratio(image: np.ndarray) -> float:
    value = image[..., 0]
    seam_x = float(np.abs(value[:, -1] - value[:, 0]).mean())
    seam_y = float(np.abs(value[-1, :] - value[0, :]).mean())
    interior_x = float(np.abs(value[:, 1:] - value[:, :-1]).mean())
    interior_y = float(np.abs(value[1:, :] - value[:-1, :]).mean())
    return max(seam_x / max(interior_x, 1e-6), seam_y / max(interior_y, 1e-6))


def main() -> int:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    gpu = WgpuBackend()
    with tempfile.TemporaryDirectory(prefix="vfxtl-noise-test-") as temp:
        settings = QSettings(str(Path(temp) / "settings.ini"), QSettings.Format.IniFormat)
        manager = CustomNodePackageManager(settings)
        packages = manager.discover(gpu if gpu.available else None, {})
        registry.replace_package_definitions(packages.values())

        for type_id in CORE_IDS + VARIATION_IDS:
            assert registry.contains(type_id), type_id
            definition = registry.get(type_id)
            numeric = [parameter for parameter in definition.parameters if parameter.kind in ("float", "int")]
            assert numeric, type_id
            assert all(parameter.animatable for parameter in numeric), (
                type_id,
                [parameter.name for parameter in numeric if not parameter.animatable],
            )

        voronoi = registry.get("org.vfxtexturelab.voronoi_noise")
        assert voronoi.output_names == ("Distance", "Edge", "Cell Value", "F2 - F1")
        assert voronoi.named_output_parameter == "mode"
        assert voronoi.evaluator is not None, "Bundled Voronoi should keep a trusted CPU reference"

        cpu = CpuBackend(gpu if gpu.available else None)
        render_context = RenderContext(96, 64, TextureFormat.RGBA16F)
        eval_context = EvalContext(96, 64)
        for type_id in CORE_IDS + VARIATION_IDS:
            definition = registry.get(type_id)
            parameters = definition.default_parameters()
            if "evolution" in parameters:
                parameters["evolution"] = 0.0
            first = definition.evaluator({}, parameters, eval_context) if definition.evaluator else None
            if first is not None:
                assert np.isfinite(first).all(), type_id
                assert float(first[..., 0].std()) > 0.01, type_id
                # Random noise is tile-safe by statistical adjacency rather than
                # matching border pixels. Other families should not reveal a
                # discontinuity larger than ordinary neighbouring variation.
                if type_id not in {"noise.white", "noise.gaussian"}:
                    assert seam_ratio(first) < 2.2, (type_id, seam_ratio(first))
                if "evolution" in parameters:
                    parameters["evolution"] = 1.0
                    last = definition.evaluator({}, parameters, eval_context)
                    assert np.max(np.abs(first - last)) < 2.0e-5, type_id

            if gpu.available and definition.evaluator is not None:
                parameters = definition.default_parameters()
                cpu_image = cpu.evaluate_node(
                    definition, {}, parameters, render_context, f"cpu:{type_id}", TextureFormat.R16F
                )
                gpu_image = gpu.to_cpu(gpu.evaluate_node(
                    definition, {}, parameters, render_context, f"gpu:{type_id}", TextureFormat.R16F
                ))
                difference = np.abs(cpu_image.array - gpu_image.array)
                if "worley" in type_id or "voronoi" in type_id:
                    assert float(difference.mean()) < 0.02, (type_id, difference.mean(), difference.max())
                else:
                    assert float(difference.max()) < 2.0e-3, (type_id, difference.mean(), difference.max())

        # Named public-package outputs must evaluate as genuinely distinct graph sockets.
        scene = GraphScene(registry)
        source = scene.create_node("org.vfxtexturelab.voronoi_noise", QPointF(), record_undo=False)
        outputs = []
        for index, output_name in enumerate(voronoi.output_names):
            sink = scene.create_node("output.image", QPointF(300, index * 140), record_undo=False)
            assert scene.add_connection(source.output_ports[output_name], sink.input_ports["Image"], record_undo=False)
            outputs.append(sink)
        evaluator = GraphEvaluator(scene, backend_preference="gpu" if gpu.available else "cpu")
        images = [evaluator.evaluate(item.uid, 80, 80).image[..., 0] for item in outputs]
        for index, first in enumerate(images):
            for second in images[index + 1 :]:
                assert float(np.mean(np.abs(first - second))) > 0.02

    print(
        "Noise foundation test passed: core and fractal noise families, shared WGSL includes, "
        "loopable evolution, animatable controls, CPU/GPU references and multi-output Voronoi"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
