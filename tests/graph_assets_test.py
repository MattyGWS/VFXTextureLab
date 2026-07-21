from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.document import DocumentSettings
from vfx_texture_lab.engine import GraphEvaluator, GraphSnapshot
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.export_plan import build_export_artifacts
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.graph_assets import (
    GRAPH_INPUT_TYPE,
    GRAPH_INSTANCE_TYPE,
    GRAPH_OUTPUT_TYPE,
    parse_graph_asset_interface,
)
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.three_d.evaluation import _MaterialWorker


def connect(scene: GraphScene, source, output: str, target, input_name: str) -> None:
    connection = scene.add_connection(
        source.output_ports[output], target.input_ports[input_name], record_undo=False
    )
    assert connection is not None


def write_asset(scene: GraphScene, path: Path, *, name: str = "Graph Asset") -> Path:
    data = scene.to_dict()
    data["graph_asset"] = {
        "name": name,
        "category": "Tests",
        "description": "Nested graph asset regression fixture.",
        "version": "1.0.0",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def evaluate_display(evaluator: GraphEvaluator, scene: GraphScene, node, output: str, size: int = 32):
    return evaluator.evaluate(
        node.uid,
        size,
        size,
        snapshot=GraphSnapshot.from_scene(scene),
        output_name=output,
        prepare_display=True,
        display_width=size,
        display_height=size,
    )


def main() -> int:
    app = QApplication.instance() or QApplication([])
    del app
    registry = build_registry()

    # Public contracts: one adaptive Graph Input, one inheriting Graph Output,
    # and a hidden dynamic Graph Instance base definition.
    graph_input = registry.get(GRAPH_INPUT_TYPE)
    graph_output = registry.get(GRAPH_OUTPUT_TYPE)
    graph_instance = registry.get(GRAPH_INSTANCE_TYPE)
    assert graph_input.output_kind("Value") == "any"
    assert graph_output.input_kind("Value") == "any"
    assert graph_instance.hidden
    assert graph_input.parameter_spec("data_type").options == (
        "Greyscale", "Colour", "Vector / Normal", "Signal", "Material", "Geometry"
    )

    temp = Path(tempfile.mkdtemp(prefix="vfx-graph-assets-"))

    # Author a graph with an adaptive input, exposed parameter and inherited
    # output type. Its internal seed must collapse into one public Random Seed.
    child = GraphScene(registry)
    graph_in = child.create_node(
        GRAPH_INPUT_TYPE,
        QPointF(),
        parameters={"name": "Source", "data_type": "Greyscale", "default_value": 0.25, "required": True},
        record_undo=False,
    )
    noise = child.create_node("noise.perlin", QPointF(180, 0), record_undo=False)
    child.set_parameter_socket_exposed(noise, "scale", True)
    child.set_parameter_socket_exposed(noise, "seed", True)
    child.set_parameter_asset_metadata(
        noise, "scale",
        {
            "name": "Rock Scale",
            "description": "Public scale control used by parent graphs.",
            "group": "Shape",
            "order": 12,
        },
    )
    blend = child.create_node("math.blend", QPointF(360, 0), parameters={"opacity": 0.5}, record_undo=False)
    connect(child, graph_in, "Value", blend, "Background")
    connect(child, noise, "Image", blend, "Foreground")
    out = child.create_node(
        GRAPH_OUTPUT_TYPE,
        QPointF(560, 0),
        parameters={"name": "Height", "primary_preview": True},
        record_undo=False,
    )
    connect(child, blend, "Image", out, "Value")
    # Graph Output is a terminal interface declaration but remains directly
    # previewable while authoring the source graph. It forwards to its connected
    # typed source instead of producing a false missing-evaluator error.
    direct_output = evaluate_display(
        GraphEvaluator(child, backend_preference="cpu"), child, out, "Image"
    )
    assert direct_output.error is None
    assert direct_output.display_rgba is not None

    # A Material Graph Output is likewise a transparent preview target and is
    # recognised by the 3D preview resolver as the connected material producer.
    material_scene = GraphScene(registry)
    material = material_scene.create_node("material.pbr", QPointF(), record_undo=False)
    material_out = material_scene.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(220, 0),
        parameters={"name": "Material Preview"}, record_undo=False,
    )
    connect(material_scene, material, "Material", material_out, "Value")
    direct_material = evaluate_display(
        GraphEvaluator(material_scene, backend_preference="cpu"),
        material_scene, material_out, "Image"
    )
    assert direct_material.error is None
    window = MainWindow.__new__(MainWindow)
    window.scene = material_scene
    window.MATERIAL_NODE_TYPE = "material.pbr"
    window.MATERIAL_NODE_TYPES = {
        "material.pbr", "material.blend", "material.override", "material.switch"
    }
    window.TEXTURE_SET_NODE_TYPE = "output.texture_set"
    assert MainWindow._resolve_material_node(window, material_out) is material
    assert MainWindow._is_material_preview_node(window, material_out)

    asset_path = write_asset(child, temp / "noise_mix.vfxgraph", name="Noise Mix")

    data = json.loads(asset_path.read_text(encoding="utf-8"))
    interface = parse_graph_asset_interface(data, registry, source_path=asset_path)
    assert interface["inputs"][0]["kind"] == "grayscale"
    assert interface["outputs"][0]["kind"] == "grayscale"
    published_names = {entry["parameter"] for entry in interface["parameters"]}
    assert "scale" in published_names
    assert "seed" not in published_names
    published_scale = next(entry for entry in interface["parameters"] if entry["parameter"] == "scale")
    assert published_scale["name"] == "Rock Scale"
    assert published_scale["group"] == "Shape"
    assert published_scale["order"] == 12

    # Publication now lives in the Graph Asset Parameter dialogue alongside
    # public naming/group metadata, without changing animation exposure itself.
    child.set_parameter_asset_metadata(
        noise, "scale",
        {
            "name": "Rock Scale",
            "description": "Public scale control used by parent graphs.",
            "group": "Shape",
            "order": 12,
            "published": False,
        },
    )
    hidden_path = write_asset(child, temp / "hidden_scale.vfxgraph", name="Hidden Scale")
    hidden_interface = parse_graph_asset_interface(
        json.loads(hidden_path.read_text(encoding="utf-8")), registry, source_path=hidden_path
    )
    assert not hidden_interface["parameters"]
    child.set_parameter_asset_metadata(
        noise, "scale",
        {
            "name": "Rock Scale",
            "description": "Public scale control used by parent graphs.",
            "group": "Shape",
            "order": 12,
            "published": True,
        },
    )
    write_asset(child, asset_path, name="Noise Mix")

    host = GraphScene(registry)
    instance = host.create_graph_instance(asset_path, QPointF(), record_undo=False)
    assert instance.definition.name == "Noise Mix"
    assert len(instance.input_ports) == 1
    assert next(iter(instance.input_ports.values())).display_name == "Source"
    assert instance.definition.output_kind(instance.definition.output_names[0]) == "grayscale"
    parameter_names = [spec.name for spec in instance.definition.parameters]
    assert parameter_names[0] == "random_seed"
    assert sum(spec.is_random_seed for spec in instance.definition.parameters) == 1
    assert len([name for name in parameter_names if "seed" in name.casefold()]) == 1
    assert any(name.startswith("asset_param::") for name in parameter_names)
    assert instance.error_message and "Required input" in instance.error_message

    evaluator = GraphEvaluator(host, backend_preference="cpu")
    public_output = instance.definition.output_names[0]
    default_result = evaluate_display(evaluator, host, instance, public_output)
    assert default_result.error is None
    assert default_result.display_rgba is not None
    assert np.std(default_result.display_rgba[..., 0]) > 5.0

    constant = host.create_node(
        "generator.constant", QPointF(-180, 0), parameters={"value": 0.8}, record_undo=False
    )
    connect(host, constant, "Image", instance, instance.definition.inputs[0])
    assert not instance.error_message
    connected_result = evaluate_display(evaluator, host, instance, public_output)
    assert connected_result.error is None
    assert not np.array_equal(default_result.display_rgba, connected_result.display_rgba)

    # One seed coherently shifts all internal randomness while remaining deterministic.
    host.change_node_parameter(instance, "random_seed", 913)
    seeded_a = evaluate_display(evaluator, host, instance, public_output).display_rgba
    seeded_b = evaluate_display(evaluator, host, instance, public_output).display_rgba
    assert np.array_equal(seeded_a, seeded_b)
    host.change_node_parameter(instance, "random_seed", 914)
    seeded_c = evaluate_display(evaluator, host, instance, public_output).display_rgba
    assert not np.array_equal(seeded_a, seeded_c)

    # Save/load keeps dynamic sockets, published controls and linked source state.
    saved = host.to_dict()
    restored = GraphScene(registry)
    restored.from_dict(saved)
    restored_instance = next(node for node in restored.nodes.values() if node.definition.type_id == GRAPH_INSTANCE_TYPE)
    assert restored_instance.definition.output_names == instance.definition.output_names
    assert restored_instance.definition.inputs == instance.definition.inputs
    assert restored.connection_for_input(restored_instance.uid, restored_instance.definition.inputs[0]) is not None

    # Stable interface IDs preserve connections and explicit overrides across a
    # source rename/reload, while untouched defaults are allowed to update.
    public_parameter = next(spec for spec in instance.definition.parameters if spec.name.startswith("asset_param::"))
    host.change_node_parameter(instance, public_parameter.name, 17.0)
    child.sceneRect()  # Keep the authored scene alive for clarity.
    child.change_node_parameter(graph_in, "name", "Renamed Source")
    child.change_node_parameter(out, "name", "Renamed Height")
    child.change_node_parameter(noise, "scale", 23.0)
    write_asset(child, asset_path, name="Noise Mix Updated")
    assert host.reload_graph_instance(instance, record_undo=False)
    assert next(iter(instance.input_ports.values())).display_name == "Renamed Source"
    assert next(iter(instance.output_ports.values())).display_name == "Renamed Height"
    assert host.connection_for_input(instance.uid, instance.definition.inputs[0]) is not None
    updated_public = next(spec for spec in instance.definition.parameters if spec.name.startswith("asset_param::"))
    assert np.isclose(float(instance.parameters[updated_public.name]), 17.0)

    # Embedded instances continue evaluating after their source file disappears.
    assert host.embed_graph_instance(instance)
    asset_path.unlink()
    evaluator.clear_cache()
    embedded_result = evaluate_display(evaluator, host, instance, instance.definition.output_names[0])
    assert embedded_result.error is None
    assert embedded_result.display_rgba is not None

    # Nested graph assets evaluate lazily and keep separate runtime namespaces.
    leaf = GraphScene(registry)
    leaf_noise = leaf.create_node("noise.value", QPointF(), record_undo=False)
    leaf_out = leaf.create_node(GRAPH_OUTPUT_TYPE, QPointF(240, 0), parameters={"name": "Noise"}, record_undo=False)
    connect(leaf, leaf_noise, "Image", leaf_out, "Value")
    leaf_path = write_asset(leaf, temp / "leaf.vfxgraph", name="Leaf")

    middle = GraphScene(registry)
    leaf_instance = middle.create_graph_instance(leaf_path, QPointF(), record_undo=False)
    middle_out = middle.create_node(GRAPH_OUTPUT_TYPE, QPointF(260, 0), parameters={"name": "Nested"}, record_undo=False)
    connect(middle, leaf_instance, leaf_instance.definition.output_names[0], middle_out, "Value")
    middle_path = write_asset(middle, temp / "middle.vfxgraph", name="Middle")

    nested_host = GraphScene(registry)
    nested = nested_host.create_graph_instance(middle_path, QPointF(), record_undo=False)
    nested_eval = GraphEvaluator(nested_host, backend_preference="cpu")
    nested_result = evaluate_display(nested_eval, nested_host, nested, nested.definition.output_names[0])
    assert nested_result.error is None
    assert nested_result.reachable_nodes == 1

    # Scalar Graph Inputs and Outputs remain scalar rather than being coerced
    # through an image texture. Parent connections override authored defaults.
    scalar_child = GraphScene(registry)
    scalar_input = scalar_child.create_node(
        GRAPH_INPUT_TYPE, QPointF(),
        parameters={"name": "Drive", "data_type": "Signal", "default_value": 0.42},
        record_undo=False,
    )
    scalar_output = scalar_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(220, 0), parameters={"name": "Signal"}, record_undo=False
    )
    connect(scalar_child, scalar_input, "Value", scalar_output, "Value")
    scalar_path = write_asset(scalar_child, temp / "scalar.vfxgraph", name="Scalar Asset")
    scalar_host = GraphScene(registry)
    scalar_instance = scalar_host.create_graph_instance(scalar_path, QPointF(), record_undo=False)
    scalar_evaluator = GraphEvaluator(scalar_host, backend_preference="cpu")
    scalar_result = scalar_evaluator.evaluate(
        scalar_instance.uid, 8, 8, output_name=scalar_instance.definition.output_names[0]
    )
    assert scalar_result.error is None and np.isclose(float(scalar_result.signal_value), 0.42)
    time_node = scalar_host.create_node("signal.time", QPointF(-200, 0), record_undo=False)
    connect(scalar_host, time_node, "Seconds", scalar_instance, scalar_instance.definition.inputs[0])
    driven_scalar = scalar_evaluator.evaluate(
        scalar_instance.uid, 8, 8,
        output_name=scalar_instance.definition.output_names[0], time_seconds=2.75, frame_number=82,
    )
    assert driven_scalar.error is None and np.isclose(float(driven_scalar.signal_value), 2.75)

    # A Material graph asset remains one purple value through portals, 3D
    # material evaluation and Texture Set Output planning. Only authored maps
    # should be resolved/exported.
    material_child = GraphScene(registry)
    base_colour = material_child.create_node(
        "generator.color", QPointF(), parameters={"color": "#804020ff"}, record_undo=False
    )
    roughness = material_child.create_node(
        "generator.constant", QPointF(0, 160), parameters={"value": 0.72}, record_undo=False
    )
    material = material_child.create_node(
        "material.pbr", QPointF(240, 0), parameters={"name": "Nested Rock"}, record_undo=False
    )
    connect(material_child, base_colour, "Image", material, "Base Colour")
    connect(material_child, roughness, "Image", material, "Roughness")
    material_output = material_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(480, 0),
        parameters={"name": "Material", "primary_preview": True}, record_undo=False,
    )
    connect(material_child, material, "Material", material_output, "Value")
    material_path = write_asset(material_child, temp / "nested_material.vfxgraph", name="Nested Rock")

    material_host = GraphScene(registry)
    material_instance = material_host.create_graph_instance(material_path, QPointF(), record_undo=False)
    material_port = material_instance.definition.output_names[0]
    assert material_instance.definition.output_kind(material_port) == "material"
    send = material_host.create_node(
        "graph.send", QPointF(220, 0), parameters={"channel_name": "Nested Material"}, record_undo=False
    )
    receive = material_host.create_node(
        "graph.receive", QPointF(420, 0), parameters={"sender_uid": send.uid}, record_undo=False
    )
    channels = material_host.create_node("material.channels", QPointF(620, 0), record_undo=False)
    connect(material_host, material_instance, material_port, send, "Input")
    connect(material_host, receive, "Output", channels, "Material")
    material_eval = GraphEvaluator(material_host, backend_preference="cpu")
    nested_colour = material_eval.evaluate(channels.uid, 8, 8, output_name="Base Colour")
    assert nested_colour.error is None
    assert np.allclose(nested_colour.image[0, 0], (0.5019608, 0.2509804, 0.1254902, 1.0), atol=2e-3)

    worker = _MaterialWorker(
        1, material_eval, GraphSnapshot.from_scene(material_host), material_instance.uid,
        8, 8, 8, 8, TextureFormat.RGBA16F, "Linear", {}, threading.Event(),
        output_port=material_port,
    )
    worker_results = []
    worker_errors = []
    worker.signals.finished.connect(lambda _request, result: worker_results.append(result))
    worker.signals.failed.connect(lambda _request, message: worker_errors.append(message))
    worker.run()
    assert not worker_errors and len(worker_results) == 1
    assert worker_results[0].connected == frozenset({"Base Colour", "Roughness"})

    texture_set = material_host.create_node(
        "output.texture_set", QPointF(820, 0), parameters={"name": "Nested"}, record_undo=False
    )
    connect(material_host, receive, "Output", texture_set, "Material")
    material_snapshot = GraphSnapshot.from_scene(material_host)
    expanded_snapshot, _uid, _output = material_eval._expand_graph_instances(
        material_snapshot, texture_set.uid, "Image"
    )
    artifacts = build_export_artifacts(
        expanded_snapshot, [texture_set.uid], DocumentSettings(width=64, height=64)
    )
    labels = {artifact.label for artifact in artifacts}
    assert labels == {"Nested · BaseColor", "Nested · Roughness"}

    # Stateful nodes inside separate instances own separate runtime namespaces.
    # Advancing A must never prime the Frame Delay state used by B.
    state_child = GraphScene(registry)
    state_input = state_child.create_node(
        GRAPH_INPUT_TYPE, QPointF(),
        parameters={"name": "Source", "data_type": "Greyscale", "default_value": 0.0},
        record_undo=False,
    )
    delay = state_child.create_node("simulation.frame_delay", QPointF(220, 0), record_undo=False)
    state_output = state_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(440, 0), parameters={"name": "Delayed"}, record_undo=False
    )
    connect(state_child, state_input, "Value", delay, "Image")
    connect(state_child, delay, "Image", state_output, "Value")
    state_path = write_asset(state_child, temp / "stateful.vfxgraph", name="Stateful")
    state_host = GraphScene(registry)
    state_a = state_host.create_graph_instance(state_path, QPointF(), record_undo=False)
    state_b = state_host.create_graph_instance(state_path, QPointF(300, 0), record_undo=False)
    constant_a = state_host.create_node(
        "generator.constant", QPointF(-200, 0), parameters={"value": 0.2}, record_undo=False
    )
    constant_b = state_host.create_node(
        "generator.constant", QPointF(100, 180), parameters={"value": 0.8}, record_undo=False
    )
    connect(state_host, constant_a, "Image", state_a, state_a.definition.inputs[0])
    connect(state_host, constant_b, "Image", state_b, state_b.definition.inputs[0])
    state_eval = GraphEvaluator(state_host, backend_preference="cpu")
    output_a = state_a.definition.output_names[0]
    output_b = state_b.definition.output_names[0]
    state_eval.evaluate(state_a.uid, 4, 4, output_name=output_a, frame_number=0)
    a_frame_1 = state_eval.evaluate(state_a.uid, 4, 4, output_name=output_a, frame_number=1)
    b_frame_1 = state_eval.evaluate(state_b.uid, 4, 4, output_name=output_b, frame_number=1)
    assert np.allclose(a_frame_1.image[..., 0], 0.2, atol=1e-6)
    assert np.allclose(b_frame_1.image[..., 0], 0.8, atol=1e-6)

    # Reloading an asset follows a changed default only for untouched instance
    # parameters. Explicit parent overrides retain their values.
    defaults_child = GraphScene(registry)
    defaults_noise = defaults_child.create_node("noise.value", QPointF(), record_undo=False)
    defaults_child.set_parameter_socket_exposed(defaults_noise, "scale", True)
    defaults_out = defaults_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(240, 0), parameters={"name": "Image"}, record_undo=False
    )
    connect(defaults_child, defaults_noise, "Image", defaults_out, "Value")
    defaults_path = write_asset(defaults_child, temp / "defaults.vfxgraph", name="Defaults")
    defaults_host = GraphScene(registry)
    untouched = defaults_host.create_graph_instance(defaults_path, QPointF(), record_undo=False)
    overridden = defaults_host.create_graph_instance(defaults_path, QPointF(300, 0), record_undo=False)
    untouched_key = next(name for name in untouched.parameters if name.startswith("asset_param::"))
    overridden_key = next(name for name in overridden.parameters if name.startswith("asset_param::"))
    defaults_host.change_node_parameter(overridden, overridden_key, 19.0)
    defaults_child.change_node_parameter(defaults_noise, "scale", 27.0)
    write_asset(defaults_child, defaults_path, name="Defaults")
    defaults_host.reload_graph_instance(untouched, record_undo=False)
    defaults_host.reload_graph_instance(overridden, record_undo=False)
    assert np.isclose(float(untouched.parameters[untouched_key]), 27.0)
    assert np.isclose(float(overridden.parameters[overridden_key]), 19.0)

    # Stable output IDs preserve parent wiring through renames. If an output is
    # actually removed, its connected socket remains visible and clearly marked
    # missing instead of silently deleting the wire.
    interface_child = GraphScene(registry)
    one = interface_child.create_node(
        "generator.constant", QPointF(), parameters={"value": 0.25}, record_undo=False
    )
    two = interface_child.create_node(
        "generator.constant", QPointF(0, 180), parameters={"value": 0.75}, record_undo=False
    )
    first_out = interface_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(240, 0), parameters={"name": "First"}, record_undo=False
    )
    second_out = interface_child.create_node(
        GRAPH_OUTPUT_TYPE, QPointF(240, 180), parameters={"name": "Second"}, record_undo=False
    )
    connect(interface_child, one, "Image", first_out, "Value")
    connect(interface_child, two, "Image", second_out, "Value")
    interface_path = write_asset(interface_child, temp / "interface.vfxgraph", name="Interface")
    interface_host = GraphScene(registry)
    interface_instance = interface_host.create_graph_instance(interface_path, QPointF(), record_undo=False)
    first_port = next(
        port for port in interface_instance.definition.output_names
        if interface_instance.output_ports[port].display_name == "First"
    )
    sink = interface_host.create_node("output.image", QPointF(300, 0), record_undo=False)
    connect(interface_host, interface_instance, first_port, sink, "Image")
    changed_interface_data = interface_child.to_dict()
    changed_interface_data["graph_asset"] = {
        "name": "Interface", "category": "Tests",
        "description": "Removed-port reload fixture.", "version": "1.0.1",
    }
    changed_interface_data["nodes"] = [
        entry for entry in changed_interface_data["nodes"]
        if str(entry.get("uid", "")) != first_out.uid
    ]
    changed_interface_data["connections"] = [
        entry for entry in changed_interface_data["connections"]
        if str(entry.get("target", "")) != first_out.uid
        and str(entry.get("source", "")) != first_out.uid
    ]
    interface_path.write_text(json.dumps(changed_interface_data, indent=2), encoding="utf-8")
    interface_host.reload_graph_instance(interface_instance, record_undo=False)
    assert first_port in interface_instance.output_ports
    assert interface_instance.output_ports[first_port].display_name.endswith("(missing)")
    assert interface_host.connection_for_input(sink.uid, "Image") is not None
    assert interface_instance.error_message and "removed" in interface_instance.error_message

    # A linked instance retains its cached last-known-good graph when the file is missing.
    cached_host = GraphScene(registry)
    cached = cached_host.create_graph_instance(leaf_path, QPointF(), record_undo=False)
    leaf_path.unlink()
    changes = cached_host.refresh_linked_graph_assets()
    assert changes and changes[0][1] == "missing"
    cached_result = evaluate_display(
        GraphEvaluator(cached_host, backend_preference="cpu"),
        cached_host,
        cached,
        cached.definition.output_names[0],
    )
    assert cached_result.error is None

    # Direct recursive dependencies are rejected cleanly rather than hanging.
    recursive = GraphScene(registry)
    seed_out = recursive.create_node(GRAPH_OUTPUT_TYPE, QPointF(300, 0), parameters={"name": "Out"}, record_undo=False)
    seed_constant = recursive.create_node("generator.constant", QPointF(), record_undo=False)
    connect(recursive, seed_constant, "Image", seed_out, "Value")
    recursive_path = write_asset(recursive, temp / "recursive.vfxgraph", name="Recursive")
    self_instance = recursive.create_graph_instance(recursive_path, QPointF(120, 120), record_undo=False)
    # Replace the output source with the self-instance and save the cycle.
    existing = recursive.connection_for_input(seed_out.uid, "Value")
    assert existing is not None
    recursive.remove_connection(existing, record_undo=False)
    connect(recursive, self_instance, self_instance.definition.output_names[0], seed_out, "Value")
    write_asset(recursive, recursive_path, name="Recursive")
    recursive_host = GraphScene(registry)
    recursive_instance = recursive_host.create_graph_instance(recursive_path, QPointF(), record_undo=False)
    recursive_result = evaluate_display(
        GraphEvaluator(recursive_host, backend_preference="cpu"),
        recursive_host,
        recursive_instance,
        recursive_instance.definition.output_names[0],
    )
    assert recursive_result.error and "Recursive graph asset" in recursive_result.error

    print(
        "graph assets test passed: adaptive interfaces, public exposed parameters, one coherent seed, "
        "linked/embedded instances, stable reloads, nested evaluation, cached missing sources and cycle safety"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
