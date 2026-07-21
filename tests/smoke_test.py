from __future__ import annotations

import json
import os
import sys
import tempfile
import struct
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.exporting import ExportOptions, export_image
from vfx_texture_lab.graph.scene import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.node_preferences import NodePreferences
from vfx_texture_lab.ui.preview import PreviewCanvas, array_to_qimage


def assert_noise_wraps(registry) -> None:
    scene = GraphScene(registry)
    noise = scene.create_node("noise.fractal", QPointF(), emit_change=False)
    image = GraphEvaluator(scene).evaluate(noise.uid, 192, 192).image[..., 0]

    interior_x = np.abs(np.diff(image, axis=1)).mean()
    interior_y = np.abs(np.diff(image, axis=0)).mean()
    seam_x = np.abs(image[:, -1] - image[:, 0]).mean()
    seam_y = np.abs(image[-1, :] - image[0, :]).mean()

    # A periodic function's wrap transition should be no harsher than its normal
    # neighbouring-pixel transitions. The deterministic default noise is much
    # better than this generous threshold, but leave room for future algorithms.
    assert seam_x <= interior_x * 1.5 + 1e-6, (seam_x, interior_x)
    assert seam_y <= interior_y * 1.5 + 1e-6, (seam_y, interior_y)


def assert_shapes_wrap(registry) -> None:
    scene = GraphScene(registry)
    shape = scene.create_node(
        "shape.shape",
        QPointF(),
        parameters={
            "shape": "Disc",
            "center_x": 0.98,
            "center_y": 0.5,
            "scale": 0.3,
            "edge_softness": 0.03,
            "invert": False,
        },
        emit_change=False,
    )
    image = GraphEvaluator(scene).evaluate(shape.uid, 128, 128).image[..., 0]
    assert image[:, 0].max() > 0.9
    assert image[:, -1].max() > 0.9
    assert image[:, image.shape[1] // 2].max() < 0.1


def assert_connections_work_in_both_directions(registry) -> None:
    scene = GraphScene(registry)
    noise = scene.create_node("noise.fractal", QPointF(0, 0), emit_change=False)
    levels = scene.create_node("filter.levels", QPointF(300, 0), emit_change=False)

    # Reverse drag order: input first, output second.
    connection = scene.add_connection(
        levels.input_ports["Image"],
        noise.output_port,
        emit_change=False,
    )
    assert connection is not None
    assert connection.source_node is noise
    assert connection.target_node is levels
    assert connection.input_name == "Image"

    # Invalid same-direction pairs must still be refused.
    assert scene.add_connection(noise.output_port, levels.output_port, emit_change=False) is None
    assert scene.add_connection(
        levels.input_ports["Image"],
        levels.input_ports["Image"],
        emit_change=False,
    ) is None


def assert_graph_view_accepts_reverse_drag(app, registry) -> None:
    scene = GraphScene(registry)
    view = GraphView(scene, NodePreferences())
    view.resize(1000, 600)
    view.show()

    noise = scene.create_node("noise.fractal", QPointF(-300, 0), emit_change=False)
    levels = scene.create_node("filter.levels", QPointF(200, 0), emit_change=False)
    view.centerOn(0, 50)
    app.processEvents()

    input_position = view.mapFromScene(levels.input_ports["Image"].centre_scene_pos())
    output_position = view.mapFromScene(noise.output_port.centre_scene_pos())
    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        input_position,
    )
    QTest.mouseMove(view.viewport(), output_position, 25)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        output_position,
    )
    app.processEvents()

    assert len(scene.connections) == 1
    assert scene.connections[0].source_node is noise
    assert scene.connections[0].target_node is levels
    view.close()


def assert_copy_paste_preserves_internal_connections(app, registry) -> None:
    scene = GraphScene(registry)
    preferences = NodePreferences()
    view = GraphView(scene, preferences)
    view.resize(900, 600)
    view.show()
    app.processEvents()

    noise = scene.create_node("noise.fractal", QPointF(-300, 0), emit_change=False)
    levels = scene.create_node("filter.levels", QPointF(0, 0), emit_change=False)
    invert = scene.create_node("filter.invert", QPointF(300, 0), emit_change=False)
    scene.add_connection(noise.output_port, levels.input_ports["Image"], emit_change=False)
    scene.add_connection(levels.output_port, invert.input_ports["Image"], emit_change=False)
    noise.setSelected(True)
    levels.setSelected(True)

    assert view.copy_selected()
    pasted = view.paste_at_cursor()
    assert len(pasted) == 2
    assert len(scene.nodes) == 5

    pasted_ids = {node.uid for node in pasted}
    pasted_internal = [
        connection
        for connection in scene.connections
        if connection.source_node.uid in pasted_ids and connection.target_node.uid in pasted_ids
    ]
    pasted_external = [
        connection
        for connection in scene.connections
        if (connection.source_node.uid in pasted_ids) != (connection.target_node.uid in pasted_ids)
    ]
    assert len(pasted_internal) == 1
    assert not pasted_external
    view.close()


def assert_group_interior_behaves_like_canvas(app, registry) -> None:
    scene = GraphScene(registry)
    view = GraphView(scene, NodePreferences())
    view.resize(1000, 650)
    node = scene.create_node("filter.levels", QPointF(0, 0), record_undo=False)
    group = scene.create_group(
        QPointF(-400, -250),
        width=900,
        height=600,
        members={node.uid},
        record_undo=False,
    )
    view.show()
    view.centerOn(50, 0)
    app.processEvents()

    # Expanded groups are hit-testable on their title bar and resize handle,
    # but their transparent body behaves like empty graph canvas.
    title_pos = view.mapFromScene(group.mapToScene(QPointF(30, 20)))
    interior_pos = view.mapFromScene(group.mapToScene(QPointF(40, 120)))
    resize_pos = view.mapFromScene(
        group.mapToScene(QPointF(group.frame_width - 5, group.frame_height - 5))
    )
    assert view.itemAt(title_pos) is group
    assert view.itemAt(interior_pos) is None
    assert view.itemAt(resize_pos) is group

    # Start a rubber-band selection from empty space inside the group and drag
    # across its member node. The frame must stay put and the node is selected.
    group_start = QPointF(group.pos())
    drag_start = view.mapFromScene(QPointF(-120, -100))
    drag_end = view.mapFromScene(QPointF(260, 130))
    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        drag_start,
    )
    QTest.mouseMove(view.viewport(), drag_end, 30)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        drag_end,
    )
    app.processEvents()
    assert node.isSelected()
    assert group.pos() == group_start
    view.close()


def assert_preview_modes(app) -> None:
    canvas = PreviewCanvas()
    canvas.resize(400, 400)
    image = np.zeros((32, 32, 4), dtype=np.float32)
    image[..., 0] = 1.0
    image[..., 3] = 1.0
    canvas.set_image(array_to_qimage(image))
    canvas.set_tile_preview(True)
    canvas.show()
    app.processEvents()
    assert canvas.tile_preview
    assert canvas.zoom == 1.0
    canvas.reset_view()
    assert canvas.zoom == 1.0
    canvas.close()



def assert_undo_redo_and_groups(registry) -> None:
    scene = GraphScene(registry)
    noise = scene.create_node("noise.fractal", QPointF(0, 0), record_undo=False)
    levels = scene.create_node("filter.levels", QPointF(300, 0), record_undo=False)
    invert = scene.create_node("filter.invert", QPointF(600, 0), record_undo=False)
    noise_uid, levels_uid, invert_uid = noise.uid, levels.uid, invert.uid
    scene.add_connection(noise.output_port, levels.input_ports["Image"], record_undo=False)
    scene.add_connection(levels.output_port, invert.input_ports["Image"], record_undo=False)
    scene.undo_stack.clear()
    scene.undo_stack.setClean()

    scene.nodes[noise_uid].setSelected(True)
    scene.nodes[levels_uid].setSelected(True)
    group = scene.group_selected_nodes()
    assert group is not None
    group_uid = group.uid
    assert scene.undo_stack.count() == 1
    assert scene.nodes[noise_uid].group_uid == group_uid
    assert scene.nodes[levels_uid].group_uid == group_uid

    scene.undo_stack.undo()
    assert not scene.groups
    assert scene.nodes[noise_uid].group_uid is None
    scene.undo_stack.redo()
    group = scene.groups[group_uid]
    assert group.members == {noise_uid, levels_uid}

    scene.toggle_group(group)
    group = scene.groups[group_uid]
    assert group.collapsed
    assert not scene.nodes[noise_uid].isVisible()
    assert not scene.nodes[levels_uid].isVisible()
    internal = scene.connection_for_input(levels_uid, "Image")
    external = scene.connection_for_input(invert_uid, "Image")
    assert internal is not None and not internal.isVisible()
    assert external is not None and external.isVisible()
    assert len(group.output_ports) == 1

    scene.undo_stack.undo()
    group = scene.groups[group_uid]
    assert not group.collapsed
    assert scene.nodes[noise_uid].isVisible()

    # Repeated slider-like changes merge into one undo step.
    before_index = scene.undo_stack.index()
    old_scale = scene.nodes[noise_uid].parameters["scale"]
    for value in (3.0, 4.0, 5.0):
        scene.change_node_parameter(scene.nodes[noise_uid], "scale", value, label="Change Scale")
    assert scene.undo_stack.index() == before_index + 1
    scene.undo_stack.undo()
    assert scene.nodes[noise_uid].parameters["scale"] == old_scale
    scene.undo_stack.redo()
    assert scene.nodes[noise_uid].parameters["scale"] == 5.0


def assert_group_interface_controls(registry) -> None:
    scene = GraphScene(registry)
    levels = scene.create_node("filter.levels", QPointF(0, 0), record_undo=False)
    invert = scene.create_node("filter.invert", QPointF(280, 0), record_undo=False)
    scene.add_connection(levels.output_port, invert.input_ports["Image"], record_undo=False)
    levels.setSelected(True)
    invert.setSelected(True)
    group = scene.group_selected_nodes()
    assert group is not None
    assert len(group.interface_inputs) == 1
    assert len(group.interface_outputs) == 1

    scene.set_group_interface_alias(group, "input", 0, "Mask In")
    group = scene.groups[group.uid]
    assert group.interface_inputs[0]["name"] == "Mask In"
    scene.set_group_interface_enabled(group, "input", 0, False)
    group = scene.groups[group.uid]
    assert not group.interface_inputs[0]["enabled"]
    assert not group.input_ports
    scene.undo_stack.undo()
    group = scene.groups[group.uid]
    assert group.interface_inputs[0]["enabled"]
    assert group.input_ports

    asset = scene.group_to_asset(group)
    instance = scene.instantiate_group_asset(asset, QPointF(900, 0))
    assert instance is not None
    assert instance.interface_inputs[0]["name"] == "Mask In"
    assert instance.input_ports


def assert_reusable_group_assets(registry) -> None:
    scene = GraphScene(registry)
    circle = scene.create_node("shape.shape", QPointF(80, 90), parameters={"shape": "Disc"}, record_undo=False)
    blur = scene.create_node("filter.blur", QPointF(350, 90), record_undo=False)
    scene.add_connection(circle.output_port, blur.input_ports["Image"], record_undo=False)
    circle.setSelected(True)
    blur.setSelected(True)
    group = scene.group_selected_nodes()
    assert group is not None
    group.name = "Soft Circle"
    group.description = "A reusable feathered circular mask."
    group.category = "User/Shapes"
    scene.set_group_parameter_exposed(group, circle.uid, "scale", True, "Scale")
    group = scene.groups[group.uid]
    assert len(group.exposed_parameters) == 1

    asset = scene.group_to_asset(group)
    assert asset["format"] == "vfx-texture-lab-user-node"
    assert len(asset["nodes"]) == 2
    assert len(asset["connections"]) == 1

    instance = scene.instantiate_group_asset(asset, QPointF(900, 300))
    assert instance is not None and instance.collapsed
    assert len(instance.members) == 2
    assert instance.name == "Soft Circle"
    assert len(instance.exposed_parameters) == 1

    # Saved projects retain groups, collapse state and exposed interfaces.
    data = json.loads(json.dumps(scene.to_dict()))
    restored = GraphScene(registry)
    restored.from_dict(data)
    assert len(restored.groups) == 2
    restored_instance = restored.groups[instance.uid]
    assert restored_instance.collapsed
    assert len(restored_instance.members) == 2
    assert len(restored_instance.exposed_parameters) == 1


def assert_document_resolution_tiers() -> None:
    settings = DocumentSettings(width=2048, height=512, preview_max_dimension=512, working_precision="16-bit float")
    assert settings.preview_size() == (512, 128)
    assert settings.texture_precision.value == "rgba16f"
    restored = DocumentSettings.from_dict(settings.to_dict())
    assert restored.to_dict() == settings.to_dict()


def assert_image_input_and_export(registry) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        source_path = folder / "source.png"
        source = np.zeros((12, 24, 4), dtype=np.uint8)
        source[..., 0] = np.linspace(0, 255, 24, dtype=np.uint8)[None, :]
        source[..., 2] = 180
        source[..., 3] = 255
        Image.fromarray(source, mode="RGBA").save(source_path)

        scene = GraphScene(registry)
        image_node = scene.create_node("input.image", QPointF(), parameters={"path": str(source_path)}, record_undo=False)
        result = GraphEvaluator(scene, backend_preference="cpu").evaluate(image_node.uid, 128, 32)
        assert result.error is None, result.error
        assert result.image.shape == (32, 128, 4)
        assert np.isfinite(result.image).all()

        png_path = folder / "mask16.png"
        export_image(
            png_path, result.image,
            ExportOptions(format_name="PNG", bit_depth=16, channels="Grayscale", source_channel="Red", colour_encoding="Linear"),
        )
        raw = png_path.read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        ihdr_length = struct.unpack(">I", raw[8:12])[0]
        assert ihdr_length == 13 and raw[12:16] == b"IHDR"
        assert raw[24] == 16  # PNG IHDR bit depth

        r16_path = folder / "mask.r16"
        export_image(
            r16_path, result.image,
            ExportOptions(format_name="R16", bit_depth=16, channels="Grayscale", source_channel="Red", colour_encoding="Linear"),
        )
        assert r16_path.stat().st_size == 128 * 32 * 2


def assert_soft_expanding_canvas(app, registry) -> None:
    scene = GraphScene(registry)
    view = GraphView(scene, NodePreferences())
    view.resize(900, 600)
    view.show()
    node = scene.create_node("generator.constant", QPointF(12000, -9000), record_undo=False)
    view._refresh_scene_bounds()
    app.processEvents()
    assert scene.sceneRect().contains(node.sceneBoundingRect())
    # Attempt to travel absurdly far beyond the authored graph. The view clamps
    # into a generous buffer around content rather than exposing an endless void.
    view.centerOn(QPointF(1_000_000, 1_000_000))
    view._clamp_view_center()
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert view._soft_bounds().contains(visible.center())
    view.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    scene = GraphScene(registry)
    evaluator = GraphEvaluator(scene)

    # Every built-in node must evaluate safely. Image Input receives a real file;
    # procedural nodes continue to support empty/unconnected inputs.
    with tempfile.TemporaryDirectory() as temporary:
        source_path = Path(temporary) / "input.png"
        Image.new("RGBA", (8, 8), (128, 64, 255, 255)).save(source_path)
        x = 0
        standalone_exclusions = {
            "graph.output",
            "graph.receive",
            "graph.send",
            "output.texture_set",
            "output.geometry",
        }
        for definition in registry.all():
            # Structural graph/material values are exercised by their dedicated
            # integration tests; they intentionally do not produce a standalone
            # RGBA image when unconnected.
            if definition.type_id in standalone_exclusions or definition.type_id.startswith("material.") or definition.is_geometry_node:
                continue
            parameters = {"path": str(source_path)} if definition.type_id == "input.image" else None
            node = scene.create_node(definition.type_id, QPointF(x, 0), parameters=parameters, emit_change=False)
            result = evaluator.evaluate(node.uid, 64, 64)
            assert result.error is None, (definition.type_id, result.error)
            assert result.image.shape == (64, 64, 4)
            x += 10

    # Exercise connections and graph persistence.
    scene.clear_graph()
    circle = scene.create_node("shape.shape", QPointF(0, 0), parameters={"shape": "Disc"}, emit_change=False)
    blur = scene.create_node("filter.blur", QPointF(250, 0), emit_change=False)
    output = scene.create_node("output.image", QPointF(500, 0), emit_change=False)
    scene.add_connection(circle.output_port, blur.input_ports["Image"])
    scene.add_connection(blur.output_port, output.input_ports["Image"])
    result = evaluator.evaluate(output.uid, 96, 96)
    assert result.error is None
    assert result.image[..., 0].max() > 0.9

    data = json.loads(json.dumps(scene.to_dict()))
    restored = GraphScene(registry)
    restored.from_dict(data)
    restored_result = GraphEvaluator(restored).evaluate(output.uid, 96, 96)
    assert restored_result.error is None
    assert restored_result.image.shape == (96, 96, 4)

    assert_noise_wraps(registry)
    assert_shapes_wrap(registry)
    assert_connections_work_in_both_directions(registry)
    assert_graph_view_accepts_reverse_drag(app, registry)
    assert_copy_paste_preserves_internal_connections(app, registry)
    assert_group_interior_behaves_like_canvas(app, registry)
    assert_undo_redo_and_groups(registry)
    assert_group_interface_controls(registry)
    assert_reusable_group_assets(registry)
    assert_preview_modes(app)
    assert_document_resolution_tiers()
    assert_image_input_and_export(registry)
    assert_soft_expanding_canvas(app, registry)

    QApplication.clipboard().clear()
    app.processEvents()
    print(
        f"Smoke test passed: {len(registry.all())} node types, bidirectional connections, tiling, "
        "copy/paste, group-interior rubber-band selection, undo/redo, editable group interfaces, comment groups, collapsed group nodes, "
        "reusable .vfxnode assets, rectangular documents, Image Input, 16-bit export, soft canvas bounds and preview modes"
    )
    app.quit()


if __name__ == "__main__":
    main()
