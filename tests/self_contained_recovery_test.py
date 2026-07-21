from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.graph_assets import GRAPH_INSTANCE_TYPE, GRAPH_OUTPUT_TYPE
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.portable_graph import (
    SelfContainedGraphError,
    build_self_contained_graph,
    validate_self_contained_graph,
)


def connect(scene: GraphScene, source, output: str, target, input_name: str) -> None:
    assert scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    ) is not None


def graph_data(scene: GraphScene, name: str) -> dict:
    data = scene.to_dict()
    data["graph_asset"] = {
        "asset_id": f"test-{name.lower().replace(' ', '-')}",
        "name": name,
        "category": "Tests",
        "description": "Portable graph regression fixture.",
        "version": "1.0.0",
    }
    return data


def write_graph(scene: GraphScene, path: Path, name: str) -> Path:
    path.write_text(json.dumps(graph_data(scene, name), indent=2), encoding="utf-8")
    return path


def image_child(registry, image_path: Path, path: Path) -> Path:
    scene = GraphScene(registry)
    image = scene.create_node(
        "input.image", QPointF(), parameters={"path": str(image_path), "embedded": False}, record_undo=False
    )
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(240, 0), parameters={"name": "Image", "primary_preview": True}, record_undo=False
    )
    connect(scene, image, "Image", output, "Value")
    return write_graph(scene, path, "Image Child")


def constant_child(registry, value: float, path: Path, name: str) -> Path:
    scene = GraphScene(registry)
    constant = scene.create_node(
        "generator.constant", QPointF(), parameters={"value": value}, record_undo=False
    )
    output = scene.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(240, 0), parameters={"name": "Value", "primary_preview": True}, record_undo=False
    )
    connect(scene, constant, "Image", output, "Value")
    return write_graph(scene, path, name)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    root = Path(tempfile.mkdtemp(prefix="vfx-self-contained-"))
    registry = build_registry()

    image_path = root / "source.png"
    Image.new("RGBA", (4, 4), (32, 96, 180, 255)).save(image_path)
    child_path = image_child(registry, image_path, root / "image_child.vfxgraph")

    host = GraphScene(registry)
    instance = host.create_graph_instance(child_path, QPointF(), record_undo=False)
    host_data = graph_data(host, "Portable Host")
    portable, report = build_self_contained_graph(
        host_data, owner_path=root / "host.vfxgraph", app_version="0.44.1"
    )
    validate_self_contained_graph(portable)
    assert report.graph_instances == 1
    assert report.images == 1
    node_data = next(node for node in portable["nodes"] if node["type"] == GRAPH_INSTANCE_TYPE)
    params = node_data["parameters"]
    assert params["_asset_mode"] == "Embedded"
    assert params["_asset_path"] == ""
    embedded_child = params["_asset_embedded_graph"]
    embedded_image = next(node for node in embedded_child["nodes"] if node["type"] == "input.image")
    assert embedded_image["parameters"]["path"] == ""
    assert embedded_image["parameters"]["embedded"] is True
    assert base64.b64decode(embedded_image["parameters"]["_embedded_data"])

    # The result remains valid after every original external resource is gone.
    child_path.unlink()
    image_path.unlink()
    validate_self_contained_graph(portable)
    restored_portable = GraphScene(registry)
    restored_portable.from_dict(portable)
    portable_instance = next(
        node for node in restored_portable.nodes.values()
        if node.definition.type_id == GRAPH_INSTANCE_TYPE
    )
    result = GraphEvaluator(restored_portable, backend_preference="cpu").evaluate(
        portable_instance.uid, 8, 8,
        snapshot=GraphSnapshot.from_scene(restored_portable),
        output_name=portable_instance.definition.output_names[0],
        prepare_display=True, display_width=8, display_height=8,
    )
    assert result.error is None and result.display_rgba is not None

    # A missing linked child is recovered from its last-known-good cache.
    recovery_source = constant_child(registry, 0.25, root / "cached_source.vfxgraph", "Cached Source")
    recovery_host = GraphScene(registry)
    recovered_instance = recovery_host.create_graph_instance(recovery_source, QPointF(), record_undo=False)
    recovery_source.unlink()
    recovered_data, recovered_report = build_self_contained_graph(
        graph_data(recovery_host, "Recovery Host"), owner_path=root / "recovery_host.vfxgraph"
    )
    assert recovered_report.recovered_graphs == 1
    validate_self_contained_graph(recovered_data)

    # Cached graph revisions can be restored to disk and relinked.
    restored_path = root / "restored_cached.vfxgraph"
    assert recovery_host.restore_cached_graph_instance(recovered_instance, restored_path, relink=True)
    assert restored_path.is_file()
    assert Path(recovered_instance.parameters["_asset_path"]).resolve() == restored_path.resolve()
    assert recovered_instance.parameters["_asset_mode"] == "Linked"

    # Relink all uses stable asset identity and preserves a single undo action.
    second = recovery_host.create_graph_instance(restored_path, QPointF(300, 0), record_undo=False)
    replacement_path = constant_child(registry, 0.8, root / "replacement.vfxgraph", "Replacement")
    # Make the replacement represent a newer revision of the same logical asset.
    replacement_payload = json.loads(replacement_path.read_text(encoding="utf-8"))
    replacement_payload["graph_asset"]["asset_id"] = recovered_instance.parameters["_asset_identity"]
    replacement_path.write_text(json.dumps(replacement_payload, indent=2), encoding="utf-8")
    assert recovery_host.relink_matching_graph_instances(recovered_instance, replacement_path) == 2
    assert Path(recovered_instance.parameters["_asset_path"]).resolve() == replacement_path.resolve()
    assert Path(second.parameters["_asset_path"]).resolve() == replacement_path.resolve()

    # Image inputs have matching relink, local embedding and restore workflows.
    image_a = root / "image-a.png"
    image_b = root / "image-b.png"
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(image_a)
    Image.new("RGBA", (2, 2), (0, 255, 0, 255)).save(image_b)
    image_scene = GraphScene(registry)
    first_image = image_scene.create_node(
        "input.image", QPointF(), parameters={"path": str(image_a)}, record_undo=False
    )
    second_image = image_scene.create_node(
        "input.image", QPointF(200, 0), parameters={"path": str(image_a)}, record_undo=False
    )
    assert image_scene.relink_image_inputs(first_image, image_b, matching=True) == 2
    assert first_image.parameters["path"] == str(image_b.resolve())
    assert second_image.parameters["path"] == str(image_b.resolve())
    assert image_scene.embed_image_input(first_image, source_path=image_b)
    assert first_image.parameters["path"] == ""
    assert first_image.parameters["embedded"] is True
    restored_image = root / "restored-image.png"
    assert image_scene.restore_embedded_image(first_image, restored_image, relink=True)
    assert restored_image.read_bytes() == image_b.read_bytes()
    assert first_image.parameters["path"] == str(restored_image.resolve())
    assert first_image.parameters["embedded"] is False

    # A genuinely missing image remains a blocking, clearly chained error.
    broken = GraphScene(registry)
    broken.create_node(
        "input.image", QPointF(), parameters={"path": str(root / "missing.png"), "embedded": False}, record_undo=False
    )
    try:
        build_self_contained_graph(graph_data(broken, "Broken"), owner_path=root / "broken.vfxgraph")
    except SelfContainedGraphError as exc:
        assert "missing" in str(exc).lower()
        assert "Broken" in str(exc)
    else:
        raise AssertionError("Missing image should block self-contained export")

    print(
        "self-contained recovery test passed: recursive graph/image embedding, cached graph recovery, "
        "matching relinks and embedded image restoration"
    )


if __name__ == "__main__":
    main()
