#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.engine import GraphEvaluator
from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.preview import array_to_qimage


def assert_typed_connections(registry) -> None:
    scene = GraphScene(registry)
    gray = scene.create_node("noise.fractal", QPointF(), record_undo=False)
    colour = scene.create_node("generator.color", QPointF(), record_undo=False)
    gradient = scene.create_node("convert.gradient_map", QPointF(), record_undo=False)
    to_gray = scene.create_node("convert.color_to_grayscale", QPointF(), record_undo=False)
    normal = scene.create_node("convert.height_normal", QPointF(), record_undo=False)
    blend = scene.create_node("math.blend", QPointF(), record_undo=False)

    assert gray.output_port.kind == "grayscale"
    assert colour.output_port.kind == "color"
    assert normal.output_port.kind == "vector"

    assert scene.can_connect(gray.output_port, gradient.input_ports["Image"])[0]
    ok, reason = scene.can_connect(colour.output_port, gradient.input_ports["Image"])
    assert not ok and "conversion" in reason.lower()
    assert scene.can_connect(colour.output_port, to_gray.input_ports["Colour"])[0]
    assert not scene.can_connect(gray.output_port, to_gray.input_ports["Colour"])[0]

    assert scene.add_connection(colour.output_port, to_gray.input_ports["Colour"], record_undo=False)
    assert scene.add_connection(to_gray.output_port, blend.input_ports["Background"], record_undo=False)
    assert blend.resolved_image_kind == "grayscale"
    assert scene.add_connection(gray.output_port, blend.input_ports["Foreground"], record_undo=False)

    # A colour branch locks both Blend image inputs to colour while Opacity stays greyscale.
    colour_blend = scene.create_node("math.blend", QPointF(), record_undo=False)
    colour_b = scene.create_node("convert.gradient_map", QPointF(), record_undo=False)
    assert scene.add_connection(gray.output_port, colour_b.input_ports["Image"], record_undo=False)
    assert scene.add_connection(colour.output_port, colour_blend.input_ports["Background"], record_undo=False)
    ok, _ = scene.can_connect(gray.output_port, colour_blend.input_ports["Foreground"])
    assert not ok
    assert scene.add_connection(colour_b.output_port, colour_blend.input_ports["Foreground"], record_undo=False)
    assert scene.add_connection(gray.output_port, colour_blend.input_ports["Opacity"], record_undo=False)
    assert colour_blend.output_port.kind == "color"

    # Signal sockets remain a separate green data flow.
    time_node = scene.create_node("signal.time", QPointF(), record_undo=False)
    transform = scene.create_node("transform.basic", QPointF(), record_undo=False)
    scene.set_parameter_socket_exposed(transform, "offset_x", True)
    scalar_port = transform.input_ports[transform.parameter_port_name("offset_x")]
    assert time_node.output_ports["Loop Phase"].kind == "scalar"
    assert scalar_port.kind == "scalar"
    assert scene.can_connect(time_node.output_ports["Loop Phase"], scalar_port)[0]
    assert not scene.can_connect(gray.output_port, scalar_port)[0]

    # Connection order cannot create a silently invalid typed branch.
    late_typed = scene.create_node("transform.basic", QPointF(), record_undo=False)
    gray_only = scene.create_node("filter.threshold", QPointF(), record_undo=False)
    assert scene.add_connection(late_typed.output_port, gray_only.input_ports["Image"], record_undo=False)
    ok, reason = scene.can_connect(colour.output_port, late_typed.input_ports["Image"])
    assert not ok and "explicit conversion" in reason.lower()

    # Disconnecting the primary input cannot leave an invalid typed wire behind.
    colour_transform = scene.create_node("transform.basic", QPointF(), record_undo=False)
    colour_only = scene.create_node("convert.color_to_grayscale", QPointF(), record_undo=False)
    upstream = scene.add_connection(colour.output_port, colour_transform.input_ports["Image"], record_undo=False)
    assert upstream is not None
    downstream = scene.add_connection(colour_transform.output_port, colour_only.input_ports["Colour"], record_undo=False)
    assert downstream is not None
    scene.remove_connection(upstream, record_undo=False)
    assert downstream not in scene.connections

    # Extract Channels is intentionally universal: it accepts colour, greyscale
    # and vector images while every named channel output remains greyscale.
    extractor = scene.create_node("convert.extract_channel", QPointF(), record_undo=False)
    assert extractor.input_ports["Image"].kind == "image_any"
    assert scene.can_connect(colour.output_port, extractor.input_ports["Image"])[0]
    assert scene.can_connect(gray.output_port, extractor.input_ports["Image"])[0]
    assert scene.can_connect(normal.output_port, extractor.input_ports["Image"])[0]
    assert all(port.kind == "grayscale" for port in extractor.output_ports.values())

    # The universal socket remains semantically polymorphic, but visually
    # follows the concrete connected type and returns to neutral when unplugged.
    vector_link = scene.add_connection(normal.output_port, extractor.input_ports["Image"], record_undo=False)
    assert vector_link is not None
    assert extractor.input_ports["Image"].declared_kind == "image_any"
    assert extractor.input_ports["Image"].kind == "vector"
    scene.remove_connection(vector_link, record_undo=False)
    assert extractor.input_ports["Image"].kind == "image_any"
    colour_link = scene.add_connection(colour.output_port, extractor.input_ports["Image"], record_undo=False)
    assert colour_link is not None
    assert extractor.input_ports["Image"].kind == "color"
    scene.remove_connection(colour_link, record_undo=False)

    # Explicit semantic reinterpretation nodes change socket meaning without
    # altering channel data.
    to_vector = scene.create_node("convert.color_to_vector", QPointF(), record_undo=False)
    to_colour = scene.create_node("convert.vector_to_color", QPointF(), record_undo=False)
    assert scene.can_connect(colour.output_port, to_vector.input_ports["Image"])[0]
    assert to_vector.output_port.kind == "vector"
    assert scene.can_connect(to_vector.output_port, to_colour.input_ports["Image"])[0]
    assert to_colour.output_port.kind == "color"

    # Channel Pack can explicitly author either colour or vector output.
    pack = scene.create_node("convert.channel_pack", QPointF(), record_undo=False)
    assert pack.output_port.kind == "color"
    scene.change_node_parameter(pack, "output_data_type", "Vector / Normal")
    assert pack.output_port.kind == "vector"


def assert_native_image_precision_and_preview(registry, root: Path) -> None:
    values = np.array(
        [[0, 4096, 16384, 32768], [49152, 57344, 65534, 65535]],
        dtype=np.uint16,
    )
    path = root / "native_16bit_gray.png"
    Image.fromarray(values).save(path)

    scene = GraphScene(registry)
    node = scene.create_node(
        "input.image", QPointF(),
        parameters={"path": str(path), "fit": "Stretch", "wrap": "Clamp"},
        record_undo=False,
    )
    assert node.parameters["_source_precision"] == "16-bit"
    assert node.parameters["_detected_kind"] == "grayscale"
    assert node.output_port.kind == "grayscale"

    evaluator = GraphEvaluator(scene, backend_preference="cpu")
    result = evaluator.evaluate(node.uid, 4, 2)
    assert result.error is None, result.error
    assert result.data_kind == "grayscale"
    assert result.precision == "16-bit"
    # The important regression: values are divided by 65535, not clamped through RGBA8.
    assert 0.45 < float(result.image[0, 3, 0]) < 0.55
    assert float(result.image[0, 1, 0]) < 0.2
    assert np.allclose(result.image[..., 0], result.image[..., 1])
    assert np.allclose(result.image[..., 1], result.image[..., 2])

    display = array_to_qimage(result.image, result.data_kind)
    display.save(str(root / "native_16bit_preview.png"))
    rgb = np.asarray(Image.open(root / "native_16bit_preview.png").convert("RGB"))
    assert np.array_equal(rgb[..., 0], rgb[..., 1])
    assert np.array_equal(rgb[..., 1], rgb[..., 2])

    # An ordinary RGB image is interpreted as sRGB colour, converted to linear for
    # processing, then converted back to display sRGB without changing its appearance.
    colour_values = np.array(
        [[[12, 64, 190], [240, 80, 25]], [[5, 180, 90], [128, 128, 128]]],
        dtype=np.uint8,
    )
    colour_path = root / "colour_8bit.png"
    Image.fromarray(colour_values, mode="RGB").save(colour_path)
    colour_node = scene.create_node(
        "input.image", QPointF(),
        parameters={"path": str(colour_path), "fit": "Stretch", "wrap": "Clamp"},
        record_undo=False,
    )
    colour_result = evaluator.evaluate(colour_node.uid, 2, 2)
    assert colour_result.error is None
    assert colour_result.data_kind == "color"
    qimage = array_to_qimage(colour_result.image, "color")
    qimage.save(str(root / "colour_roundtrip.png"))
    roundtrip = np.asarray(Image.open(root / "colour_roundtrip.png").convert("RGB"))
    assert np.abs(roundtrip.astype(np.int16) - colour_values.astype(np.int16)).max() <= 1

    # Extract Channels remains valid when an Image Input changes semantic type.
    extractor = scene.create_node("convert.extract_channel", QPointF(), record_undo=False)
    connection = scene.add_connection(colour_node.output_port, extractor.input_ports["Image"], record_undo=False)
    assert connection is not None
    assert extractor.input_ports["Image"].kind == "color"
    scene.change_node_parameter(colour_node, "data_type", "Greyscale")
    assert colour_node.output_port.kind == "grayscale"
    assert extractor.input_ports["Image"].kind == "grayscale"
    assert connection in scene.connections

    # A conventional tangent-space normal map is conservatively detected as
    # vector data, remains linear, and supports an in-node Green/Y flip.
    normal_values = np.zeros((2, 2, 3), dtype=np.uint8)
    normal_values[..., 0] = np.array([[64, 128], [192, 128]], dtype=np.uint8)
    normal_values[..., 1] = np.array([[96, 160], [128, 128]], dtype=np.uint8)
    normal_values[..., 2] = 255
    normal_path = root / "rock_normal.png"
    Image.fromarray(normal_values, mode="RGB").save(normal_path)
    normal_input = scene.create_node(
        "input.image", QPointF(),
        parameters={"path": str(normal_path), "fit": "Stretch", "wrap": "Clamp"},
        record_undo=False,
    )
    assert normal_input.parameters["_detected_kind"] == "vector"
    assert normal_input.output_port.kind == "vector"
    normal_result = evaluator.evaluate(normal_input.uid, 2, 2)
    assert normal_result.error is None
    assert normal_result.data_kind == "vector"
    original_green = normal_result.image[..., 1].copy()
    scene.change_node_parameter(normal_input, "flip_y", True)
    evaluator.clear_cache()
    flipped_result = evaluator.evaluate(normal_input.uid, 2, 2)
    assert flipped_result.error is None
    assert np.allclose(flipped_result.image[..., 1], 1.0 - original_green, atol=1e-6)


def assert_precision_propagation(registry) -> None:
    scene = GraphScene(registry)
    constant = scene.create_node("generator.constant", QPointF(), record_undo=False)
    constant.parameters["value"] = 0.501
    levels = scene.create_node("filter.levels", QPointF(), record_undo=False)
    output = scene.create_node("output.image", QPointF(), record_undo=False)
    assert scene.add_connection(constant.output_port, levels.input_ports["Image"], record_undo=False)
    assert scene.add_connection(levels.output_port, output.input_ports["Image"], record_undo=False)

    cpu = GraphEvaluator(scene, backend_preference="cpu")
    inherited = cpu.evaluate(output.uid, 8, 8)
    assert inherited.error is None
    assert inherited.precision == "16-bit"
    assert inherited.data_kind == "grayscale"

    constant.parameters["_precision"] = "8-bit"
    cpu.clear_cache()
    eight = cpu.evaluate(output.uid, 8, 8)
    assert eight.error is None
    assert eight.precision == "8-bit"
    expected = round(0.501 * 255.0) / 255.0
    assert np.allclose(eight.image[..., 0], expected, atol=1e-7)

    levels.parameters["_precision"] = "16-bit"
    cpu.clear_cache()
    promoted = cpu.evaluate(output.uid, 8, 8)
    assert promoted.error is None
    assert promoted.precision == "16-bit"

    output.parameters["_precision"] = "32-bit float"
    cpu.clear_cache()
    thirty_two = cpu.evaluate(output.uid, 8, 8)
    assert thirty_two.error is None
    assert thirty_two.precision == "32-bit float"

    # Exercise the WGSL 8-bit quantisation path when a WebGPU adapter is present.
    gpu = GraphEvaluator(scene, backend_preference="gpu")
    if gpu.gpu_available:
        constant.parameters["_precision"] = "8-bit"
        levels.parameters["_precision"] = "Inherit"
        output.parameters["_precision"] = "Inherit"
        gpu.clear_cache()
        gpu_result = gpu.evaluate(output.uid, 8, 8)
        assert gpu_result.error is None, gpu_result.error
        assert gpu_result.precision == "8-bit"
        assert np.allclose(gpu_result.image[..., 0], expected, atol=2e-3)

    saved = scene.to_dict()
    restored = GraphScene(registry)
    restored.from_dict(saved)
    restored_constant = next(n for n in restored.nodes.values() if n.definition.type_id == "generator.constant")
    assert restored_constant.parameters["_precision"] == "8-bit"
    assert restored_constant.output_port.kind == "grayscale"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    assert_typed_connections(registry)
    with tempfile.TemporaryDirectory(prefix="vfxtl-typed-") as directory:
        assert_native_image_precision_and_preview(registry, Path(directory))
    assert_precision_propagation(registry)
    print(
        "Typed pipeline test passed: semantic greyscale/colour/vector/signal ports, "
        "explicit conversions, normal-map detection/Y flipping, universal channel extraction, "
        "typed Channel Pack output, invalid-connection rejection, native 16-bit image decoding, "
        "display colour management and inherited 8/16/32-bit precision"
    )
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
