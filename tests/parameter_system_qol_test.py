from __future__ import annotations

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.nodes.base import ParameterSpec
from vfx_texture_lab.nodes.registry import build_registry


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    spec = ParameterSpec(
        "amount",
        "Amount",
        "float",
        1.0,
        0.0,
        100.0,
        0.01,
        group="Shape",
        group_order=25,
        slider_minimum=0.0,
        slider_maximum=4.0,
        fine_step=0.01,
        coarse_step=0.1,
    )
    assert spec.group == "Shape"
    assert spec.group_order == 25
    assert spec.maximum == 100.0 and spec.slider_maximum == 4.0
    assert spec.fine_step == 0.01 and spec.coarse_step == 0.1

    registry = build_registry()
    seed_specs = [
        parameter
        for definition in registry.all(include_hidden=True)
        for parameter in definition.parameters
        if parameter.name in {"seed", "random_seed", "randomseed"}
    ]
    assert seed_specs
    assert all(parameter.kind == "int" for parameter in seed_specs)
    assert all(parameter.slider_maximum is not None for parameter in seed_specs)

    expected_direction_dials = {
        ("generator.linear_gradient", "angle"),
        ("pattern.tile_sampler", "rotation"),
        ("pattern.tile_sampler", "displacement_angle"),
        ("transform.basic", "angle"),
        ("transform.rotate", "angle"),
        ("coordinates.cartesian_to_polar", "angle_offset"),
        ("coordinates.polar_to_cartesian", "angle_offset"),
        ("distortion.swirl", "angle"),
        ("org.vfxtexturelab.directional_warp", "angle"),
        ("noise.turbulence", "flow_direction"),
    }
    for type_id, parameter_name in expected_direction_dials:
        parameter = next(item for item in registry.get(type_id).parameters if item.name == parameter_name)
        assert parameter.editor == "angle", (type_id, parameter_name)
        assert parameter.unit == "degrees"
        assert parameter.fine_step == 1.0 and parameter.coarse_step == 5.0
        if type_id in {"transform.basic", "transform.rotate", "distortion.swirl"}:
            assert not parameter.angle_wrap
        else:
            assert parameter.angle_wrap

    random_rotation = next(
        item for item in registry.get("pattern.tile_sampler").parameters if item.name == "rotation_random"
    )
    assert random_rotation.editor == ""
    assert random_rotation.maximum == 180.0
    assert "-180° to +180°" in random_rotation.description

    scalar_default = next(item for item in registry.get("signal.math").parameters if item.name == "a")
    assert scalar_default.minimum == -1000.0 and scalar_default.maximum == 1000.0
    assert scalar_default.slider_minimum == -10.0 and scalar_default.slider_maximum == 10.0
    tiles_x = next(item for item in registry.get("transform.tile").parameters if item.name == "tiles_x")
    assert tiles_x.maximum == 100.0 and tiles_x.slider_maximum == 16.0

    spinboxes = (ROOT / "vfx_texture_lab" / "ui" / "spinboxes.py").read_text(encoding="utf-8")
    parameters = (ROOT / "vfx_texture_lab" / "ui" / "parameters.py").read_text(encoding="utf-8")
    timeline = (ROOT / "vfx_texture_lab" / "ui" / "timeline.py").read_text(encoding="utf-8")
    custom_loader = (ROOT / "vfx_texture_lab" / "custom_nodes.py").read_text(encoding="utf-8")
    template = tomllib.loads((ROOT / "examples" / "custom_node_template" / "node.toml").read_text(encoding="utf-8"))
    template_angle = next(item for item in template["parameters"] if item["id"] == "angle")

    assert 'text = text.rstrip("0").rstrip(".")' in spinboxes
    assert 'text += ".0"' in spinboxes
    assert "setKeyboardTracking(False)" in spinboxes
    assert "SC_SpinBoxUp" in spinboxes and "SC_SpinBoxDown" in spinboxes
    assert "CompactDoubleSpinBox" in parameters
    assert "class AngleDial(QWidget)" in parameters
    assert "def _value_for_pointer_angle" in parameters
    assert "clicking a direction moves the" in parameters
    assert "Angle controls span the form" in parameters
    assert "spec.slider_minimum" in parameters and "spec.slider_maximum" in parameters
    assert "spec.angle_wrap" in parameters and "wrap_minimum" in parameters
    assert "QApplication.keyboardModifiers()" in parameters
    assert "ShiftModifier" in parameters and "ControlModifier" in parameters
    assert "setInteractionSteps" in spinboxes and "def stepBy" in spinboxes
    assert 'entry.get("slider_minimum")' in custom_loader
    assert 'entry.get("fine_step")' in custom_loader and 'entry.get("editor", "")' in custom_loader
    assert 'entry.get("angle_wrap", True)' in custom_loader
    assert template_angle["editor"] == "angle" and template_angle["unit"] == "degrees"
    assert template_angle["slider_minimum"] == -180.0 and template_angle["slider_maximum"] == 180.0
    assert "CompactSpinBox" in timeline
    assert '"Base Settings"' in parameters
    assert '"Transform"' in parameters
    assert '"Animation"' in parameters
    assert '"Tiling / Boundaries"' in parameters
    assert '"Quality"' in parameters
    assert "ParameterGroupWidget" in parameters
    print("parameter system QoL test passed: soft ranges, angle dials, degree units and modifier snapping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
