from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.export_plan import build_export_artifacts
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.material_graph import MaterialEvaluationSession, material_channel_present
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import NodeDefinition
from vfx_texture_lab.three_d.evaluation import _MaterialWorker


def pixel(result) -> np.ndarray:
    assert result.error is None, result.error
    assert result.image is not None
    return result.image[0, 0]


def connect(scene: GraphScene, source, output: str, target, input_name: str) -> None:
    connection = scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    )
    assert connection is not None, f"failed to connect {source.definition.name}.{output} -> {target.definition.name}.{input_name}"


def material_with(scene: GraphScene, *, colour=None, roughness=None, height=None, name="Material"):
    material = scene.create_node("material.pbr", QPointF(), parameters={"name": name}, record_undo=False)
    if colour is not None:
        node = scene.create_node("generator.color", QPointF(), parameters={"color": colour}, record_undo=False)
        connect(scene, node, "Image", material, "Base Colour")
    if roughness is not None:
        node = scene.create_node("generator.constant", QPointF(), parameters={"value": roughness}, record_undo=False)
        connect(scene, node, "Image", material, "Roughness")
    if height is not None:
        node = scene.create_node("generator.constant", QPointF(), parameters={"value": height}, record_undo=False)
        connect(scene, node, "Image", material, "Height")
    return material


def main() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    registry = build_registry()

    # Public node contracts and typed sockets.
    blend_def = registry.get("material.blend")
    override_def = registry.get("material.override")
    channels_def = registry.get("material.channels")
    switch_def = registry.get("material.switch")
    assert all(definition.category == "Materials" for definition in (
        registry.get("material.pbr"), blend_def, override_def, channels_def, switch_def
    ))
    assert blend_def.input_kind("Background Material") == "material"
    assert blend_def.input_kind("Mask") == "grayscale"
    assert channels_def.output_kind("Base Colour") == "color"
    assert channels_def.output_kind("Normal") == "vector"
    assert channels_def.output_kind("Roughness") == "grayscale"
    assert switch_def.input_kind("Selection") == "scalar"

    scene = GraphScene(registry)
    red = material_with(scene, colour="#ff0000ff", roughness=0.2, height=0.2, name="Red")
    blue = material_with(scene, colour="#0000ffff", roughness=0.8, height=0.8, name="Blue")
    blend = scene.create_node("material.blend", QPointF(), parameters={"amount": 0.25}, record_undo=False)
    connect(scene, red, "Material", blend, "Background Material")
    connect(scene, blue, "Material", blend, "Foreground Material")
    breakout = scene.create_node("material.channels", QPointF(), record_undo=False)
    connect(scene, blend, "Material", breakout, "Material")
    evaluator = GraphEvaluator(scene, backend_preference="cpu")

    mixed = evaluator.evaluate(breakout.uid, 8, 8, output_name="Base Colour")
    assert np.allclose(pixel(mixed), (0.75, 0.0, 0.25, 1.0), atol=1e-6)

    # Named breakout outputs behave as ordinary image sources downstream.
    invert = scene.create_node("filter.invert", QPointF(), record_undo=False)
    connect(scene, breakout, "Base Colour", invert, "Image")
    inverted = evaluator.evaluate(invert.uid, 8, 8)
    assert np.allclose(pixel(inverted), (0.25, 1.0, 0.75, 1.0), atol=1e-6)

    # Mask extremes are exact at full Amount, and semantic defaults fill only the missing side.
    scene.change_node_parameter(blend, "amount", 1.0)
    mask = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.0}, record_undo=False)
    connect(scene, mask, "Image", blend, "Mask")
    evaluator.clear_cache()
    assert np.allclose(pixel(evaluator.evaluate(blend.uid, 8, 8, output_name="Base Colour")), (1, 0, 0, 1), atol=1e-6)
    scene.change_node_parameter(mask, "value", 1.0)
    evaluator.clear_cache()
    assert np.allclose(pixel(evaluator.evaluate(blend.uid, 8, 8, output_name="Base Colour")), (0, 0, 1, 1), atol=1e-6)

    foreground_only = scene.create_node("material.blend", QPointF(), parameters={"amount": 1.0}, record_undo=False)
    connect(scene, blue, "Material", foreground_only, "Foreground Material")
    assert np.isclose(pixel(evaluator.evaluate(foreground_only.uid, 4, 4, output_name="Roughness"))[0], 0.8)
    black = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.0}, record_undo=False)
    connect(scene, black, "Image", foreground_only, "Mask")
    evaluator.clear_cache()
    assert np.isclose(pixel(evaluator.evaluate(foreground_only.uid, 4, 4, output_name="Roughness"))[0], 0.5)

    # Height-aware blend responds to relative material heights.
    height_blend = scene.create_node(
        "material.blend", QPointF(),
        parameters={"blend_method": "Height Aware", "height_influence": 1.0, "transition_softness": 0.05},
        record_undo=False,
    )
    mid_mask = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.5}, record_undo=False)
    connect(scene, red, "Material", height_blend, "Background Material")
    connect(scene, blue, "Material", height_blend, "Foreground Material")
    connect(scene, mid_mask, "Image", height_blend, "Mask")
    height_colour = pixel(evaluator.evaluate(height_blend.uid, 4, 4, output_name="Base Colour"))
    assert height_colour[2] > 0.95 and height_colour[0] < 0.05

    # Override changes only connected channels, obeys masks, and removal restores
    # a semantic default while marking the channel absent for export.
    override = scene.create_node("material.override", QPointF(), record_undo=False)
    connect(scene, red, "Material", override, "Material")
    override_rough = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.9}, record_undo=False)
    connect(scene, override_rough, "Image", override, "Roughness")
    assert np.isclose(pixel(evaluator.evaluate(override.uid, 4, 4, output_name="Roughness"))[0], 0.9)
    assert np.allclose(pixel(evaluator.evaluate(override.uid, 4, 4, output_name="Base Colour")), (1, 0, 0, 1), atol=1e-6)
    zero_mask = scene.create_node("generator.constant", QPointF(), parameters={"value": 0.0}, record_undo=False)
    connect(scene, zero_mask, "Image", override, "Mask")
    evaluator.clear_cache()
    assert np.isclose(pixel(evaluator.evaluate(override.uid, 4, 4, output_name="Roughness"))[0], 0.2)
    scene.change_node_parameter(override, "remove_roughness", True)
    evaluator.clear_cache()
    removed = evaluator.evaluate(override.uid, 4, 4, output_name="Roughness")
    assert np.isclose(pixel(removed)[0], 0.5)
    snapshot = GraphSnapshot.from_scene(scene)
    assert not material_channel_present(snapshot, override.uid, "Roughness")

    # Material settings inherit, or can be intentionally overridden.
    scene.change_node_parameter(red, "surface_mode", "Alpha Cutout")
    scene.change_node_parameter(red, "cutout_threshold", 0.33)
    snapshot = GraphSnapshot.from_scene(scene)
    session = MaterialEvaluationSession(evaluator, snapshot, 4, 4)
    inherited = session.material_info(override.uid)
    assert inherited.settings["surface_mode"] == "Alpha Cutout"
    assert np.isclose(inherited.settings["cutout_threshold"], 0.33)
    scene.change_node_parameter(override, "override_material_settings", True)
    scene.change_node_parameter(override, "surface_mode", "Additive")
    snapshot = GraphSnapshot.from_scene(scene)
    session = MaterialEvaluationSession(evaluator, snapshot, 4, 4)
    assert session.material_info(override.uid).settings["surface_mode"] == "Additive"

    # Static and signal-driven switching select only one branch. A deliberately
    # failing image on B proves that A does not evaluate the unselected branch.
    def fail_eval(_inputs, _params, _context):
        raise RuntimeError("unselected branch evaluated")

    registry.register(NodeDefinition(
        "test.fail_image", "Fail Image", "Test", fail_eval,
        output_kinds=(("Image", "color"),), default_image_kind="color",
    ))
    switch_scene = GraphScene(registry)
    safe = material_with(switch_scene, colour="#00ff00ff", name="Safe")
    bad_image = switch_scene.create_node("test.fail_image", QPointF(), record_undo=False)
    bad = switch_scene.create_node("material.pbr", QPointF(), record_undo=False)
    connect(switch_scene, bad_image, "Image", bad, "Base Colour")
    switch = switch_scene.create_node("material.switch", QPointF(), parameters={"selected_material": "A"}, record_undo=False)
    connect(switch_scene, safe, "Material", switch, "Material A")
    connect(switch_scene, bad, "Material", switch, "Material B")
    switch_eval = GraphEvaluator(switch_scene, backend_preference="cpu")
    safe_result = switch_eval.evaluate(switch.uid, 4, 4, output_name="Base Colour")
    assert safe_result.error is None
    switch_scene.change_node_parameter(switch, "selected_material", "B")
    switch_eval.clear_cache()
    assert switch_eval.evaluate(switch.uid, 4, 4, output_name="Base Colour").error is not None

    signal_scene = GraphScene(build_registry())
    a = material_with(signal_scene, colour="#ff0000ff", name="A")
    b = material_with(signal_scene, colour="#0000ffff", name="B")
    signal_switch = signal_scene.create_node("material.switch", QPointF(), record_undo=False)
    phase = signal_scene.create_node("signal.loop_phase", QPointF(), record_undo=False)
    connect(signal_scene, a, "Material", signal_switch, "Material A")
    connect(signal_scene, b, "Material", signal_switch, "Material B")
    connect(signal_scene, phase, "Phase", signal_switch, "Selection")
    signal_eval = GraphEvaluator(signal_scene, backend_preference="cpu")
    at_a = signal_eval.evaluate(signal_switch.uid, 4, 4, output_name="Base Colour", frame_number=30, frame_position=30.0)
    at_b = signal_eval.evaluate(signal_switch.uid, 4, 4, output_name="Base Colour", frame_number=90, frame_position=90.0)
    assert np.allclose(pixel(at_a), (1, 0, 0, 1), atol=1e-6)
    assert np.allclose(pixel(at_b), (0, 0, 1, 1), atol=1e-6)


    # Material portals preserve the composed purple value without expanding it.
    portal_send = scene.create_node(
        "graph.send", QPointF(), parameters={"channel_name": "Layered Material"}, record_undo=False
    )
    connect(scene, blend, "Material", portal_send, "Input")
    portal_receive = scene.create_node(
        "graph.receive", QPointF(), parameters={"sender_uid": portal_send.uid}, record_undo=False
    )
    portal_channels = scene.create_node("material.channels", QPointF(), record_undo=False)
    connect(scene, portal_receive, "Output", portal_channels, "Material")
    evaluator.clear_cache()
    portal_colour = evaluator.evaluate(portal_channels.uid, 4, 4, output_name="Base Colour")
    assert np.allclose(pixel(portal_colour), (0, 0, 1, 1), atol=1e-6)

    # The 3D worker accepts a composed material directly and resolves all maps
    # through one shared lazy session.
    worker = _MaterialWorker(
        1, evaluator, GraphSnapshot.from_scene(scene), blend.uid, 8, 8, 8, 8,
        TextureFormat.RGBA16F, "Linear", {}, threading.Event(),
    )
    worker_results = []
    worker_errors = []
    worker.signals.finished.connect(lambda _request_id, result: worker_results.append(result))
    worker.signals.failed.connect(lambda _request_id, message: worker_errors.append(message))
    worker.run()
    assert not worker_errors
    assert len(worker_results) == 1
    material_result = worker_results[0]
    assert material_result.output_name == "Material Blend"
    assert {"Base Colour", "Roughness", "Height"}.issubset(material_result.connected)
    assert np.allclose(material_result.textures["Base Colour"][0, 0], (0, 0, 1, 1), atol=1e-6)

    # Texture Set Output follows composed materials and omits removed channels.
    texture_set = scene.create_node(
        "output.texture_set", QPointF(),
        parameters={
            "name": "Layered", "export_preset": "Separate PBR Maps", "export_filename": "{set}_{map}",
            "export_resolution": "Document", "normal_convention": "OpenGL (+Y)", "texture_format": "PNG",
            "colour_bit_depth": "8", "data_bit_depth": "16", "height_format": "PNG 16-bit",
        },
        record_undo=False,
    )
    connect(scene, override, "Material", texture_set, "Material")
    snapshot = GraphSnapshot.from_scene(scene)
    artifacts = build_export_artifacts(snapshot, [texture_set.uid], type("Doc", (), {"width": 64, "height": 64})())
    labels = {artifact.label for artifact in artifacts}
    assert "Layered · BaseColor" in labels
    assert "Layered · Roughness" not in labels
    base_artifact = next(artifact for artifact in artifacts if artifact.label == "Layered · BaseColor")
    source = base_artifact.sources[0][1]
    assert source.node_uid == override.uid and source.output_name == "Base Colour"

    # Save/load retains all material sockets and parameters.
    saved = scene.to_dict()
    restored = GraphScene(build_registry())
    restored.from_dict(saved)
    restored_types = {node.definition.type_id for node in restored.nodes.values()}
    assert {"material.blend", "material.override", "material.channels"}.issubset(restored_types)
    restored_override = next(node for node in restored.nodes.values() if node.definition.type_id == "material.override")
    assert restored_override.parameters["remove_roughness"] is True

    print(
        "material composition test passed: typed nodes, lazy breakout, standard/height-aware blend, masked override/removal, "
        "settings inheritance, branch-lazy switch, material portals, composed 3D evaluation, texture-set export and graph persistence"
    )


if __name__ == "__main__":
    main()
