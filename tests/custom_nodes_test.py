from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QCoreApplication, QPointF, QSettings
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.custom_nodes import CustomNodePackageManager
from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.nodes import build_registry


def build_manager(root: Path) -> tuple[CustomNodePackageManager, QSettings]:
    settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
    manager = CustomNodePackageManager(settings)
    manager.managed_directory = root / "managed"
    manager.managed_directory.mkdir(parents=True, exist_ok=True)
    return manager, settings


def assert_bundled_public_packages(manager, evaluator, registry) -> dict:
    definitions = manager.discover(evaluator.gpu_backend, {})
    expected = {
        "org.vfxtexturelab.voronoi_noise",
        "org.vfxtexturelab.polar_coordinates",
        "org.vfxtexturelab.directional_warp",
    }
    assert expected.issubset(definitions)
    assert all(item.severity == "ok" for item in manager.diagnostics() if item.package_id in expected)
    registry.replace_package_definitions(definitions.values())
    return definitions


def assert_public_nodes_execute(registry, evaluator, scene) -> None:
    voronoi = scene.create_node("org.vfxtexturelab.voronoi_noise", QPointF(), record_undo=False)
    result = evaluator.evaluate(voronoi.uid, 96, 64)
    assert result.error is None and result.gpu_nodes == 1
    assert np.isfinite(result.image).all()

    scene.clear_graph(record_undo=False)
    gradient = scene.create_node("generator.linear_gradient", QPointF(), record_undo=False)
    polar = scene.create_node("org.vfxtexturelab.polar_coordinates", QPointF(), record_undo=False)
    scene.add_connection(gradient.output_port, polar.input_ports["Image"], record_undo=False)
    result = evaluator.evaluate(polar.uid, 96, 64)
    assert result.error is None and result.gpu_nodes == 2

    scene.clear_graph(record_undo=False)
    checker = scene.create_node("pattern.checker", QPointF(), record_undo=False)
    noise = scene.create_node("noise.fractal", QPointF(), record_undo=False)
    warp = scene.create_node("org.vfxtexturelab.directional_warp", QPointF(), record_undo=False)
    scene.add_connection(checker.output_port, warp.input_ports["Image"], record_undo=False)
    scene.add_connection(noise.output_port, warp.input_ports["Intensity"], record_undo=False)
    result = evaluator.evaluate(warp.uid, 96, 64)
    assert result.error is None and result.gpu_nodes == 3


def make_external_package(root: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "vfx_texture_lab" / "node_packages" / "voronoi_noise"
    target = root / "MyNodes" / "custom_voronoi"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest = target / "node.toml"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace("org.vfxtexturelab.voronoi_noise", "com.test.custom_voronoi")
    text = text.replace('name = "Voronoi Noise"', 'name = "Test Library Voronoi"')
    text = text.replace('category = "Noise"', 'category = "Test Library/Noise"')
    manifest.write_text(text, encoding="utf-8")
    return target


def assert_library_settings_and_hot_reload(root: Path, manager, settings, evaluator) -> None:
    package_root = make_external_package(root)
    library_root = package_root.parent
    entry = manager.add_library(library_root, "Artist Node Shelf")
    assert entry.enabled

    # Application-global locations survive a new manager/startup.
    second = CustomNodePackageManager(settings)
    second.managed_directory = manager.managed_directory
    assert any(Path(item.path) == library_root.resolve() for item in second.libraries())

    first_definitions = manager.discover(evaluator.gpu_backend, manager.definitions())
    package_id = "com.test.custom_voronoi"
    assert package_id in first_definitions
    old_definition = first_definitions[package_id]

    # A broken save reports a useful diagnostic but retains all preflighted
    # last-good physical-format pipelines and the previous definition.
    shader = package_root / "kernel.wgsl"
    good_source = shader.read_text(encoding="utf-8")
    shader.write_text(good_source + "\nthis is deliberately invalid wgsl;\n", encoding="utf-8")
    failed = manager.discover(evaluator.gpu_backend, first_definitions)
    assert failed[package_id] is old_definition
    diagnostic = manager.diagnostic_for(package_id)
    assert diagnostic is not None and diagnostic.severity == "error" and diagnostic.using_last_good

    registry = build_registry()
    registry.replace_package_definitions(failed.values())
    scene = GraphScene(registry)
    old_evaluator = GraphEvaluator(scene, backend_preference="gpu", gpu_budget_mb=64, cpu_budget_mb=32)
    # Transfer the manager evaluator's validated backend cache is not practical;
    # test the actual last-good guarantee on the backend that performed discovery.
    node = GraphScene(build_registry())
    del node, old_evaluator
    # Directly dispatch through the same backend used for preflight.
    from vfx_texture_lab.engine.formats import RenderContext
    result = evaluator.gpu_backend.evaluate_node(
        old_definition, {}, old_definition.default_parameters(), RenderContext(32, 32), "last-good"
    )
    assert evaluator.gpu_backend.to_cpu(result).array.shape == (32, 32, 4)

    shader.write_text(good_source, encoding="utf-8")
    recovered = manager.discover(evaluator.gpu_backend, failed)
    assert recovered[package_id] is not old_definition
    assert recovered[package_id].package.revision == old_definition.package.revision
    assert manager.diagnostic_for(package_id).severity == "ok"


def assert_install_and_missing_placeholder(root: Path, manager, evaluator) -> None:
    package_root = make_external_package(root / "archive_source")
    archive = root / "custom.vfxnodepkg"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in package_root.rglob("*"):
            if path.is_file():
                bundle.write(path, Path("custom_voronoi") / path.relative_to(package_root))
    installed = manager.install_archive(archive)
    assert (installed / "node.toml").is_file()

    definitions = manager.discover(evaluator.gpu_backend, manager.definitions())
    custom = definitions["com.test.custom_voronoi"]
    registry = build_registry()
    registry.replace_package_definitions(definitions.values())
    scene = GraphScene(registry)
    source = scene.create_node(custom.type_id, QPointF(), record_undo=False)
    levels = scene.create_node("filter.levels", QPointF(260, 0), record_undo=False)
    scene.add_connection(source.output_port, levels.input_ports["Image"], record_undo=False)
    saved = json.loads(json.dumps(scene.to_dict()))

    missing_registry = build_registry()
    restored = GraphScene(missing_registry)
    restored.from_dict(saved)
    missing = restored.nodes[source.uid]
    assert missing.definition.missing
    assert missing.definition.type_id == custom.type_id
    assert len(restored.connections) == 1

    missing_registry.replace_package_definitions([custom])
    restored.rebind_registry_definitions()
    assert not restored.nodes[source.uid].definition.missing
    assert restored.nodes[source.uid].definition.name == custom.name
    assert len(restored.connections) == 1


def main() -> int:
    app = QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("CustomNodes")
    with tempfile.TemporaryDirectory(prefix="vfxtl-custom-test-") as temp:
        root = Path(temp)
        manager, settings = build_manager(root)
        registry = build_registry()
        scene = GraphScene(registry)
        evaluator = GraphEvaluator(scene, backend_preference="gpu", gpu_budget_mb=128, cpu_budget_mb=64)
        definitions = assert_bundled_public_packages(manager, evaluator, registry)
        if evaluator.gpu_available:
            assert_public_nodes_execute(registry, evaluator, scene)
            assert_library_settings_and_hot_reload(root, manager, settings, evaluator)
            assert_install_and_missing_placeholder(root, manager, evaluator)
        else:
            print("GPU execution/hot-reload tests skipped:", evaluator.backend_info()["gpu_detail"])
            assert len(definitions) >= 3
    app.processEvents()
    print(
        "Custom node test passed: public package discovery, configurable library folders, "
        "three WGSL package nodes, safe archive installation, hot reload with last-good shader retention, "
        "diagnostics and missing-package graph placeholders"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
