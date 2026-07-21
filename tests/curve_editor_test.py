from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.nodes.base import EvalContext


def main() -> None:
    registry = build_registry()
    tone = registry.get("filter.curve")
    animation = registry.get("signal.curve")

    # Display names remove the old duplicate "Curve" ambiguity while stable IDs
    # preserve saved-project compatibility.
    assert tone.name == "Tone Curve"
    assert animation.name == "Animation Curve"
    assert tone.type_id == "filter.curve"
    assert animation.type_id == "signal.curve"

    source = (ROOT / "vfx_texture_lab" / "ui" / "parameters.py").read_text()
    ast.parse(source)
    assert "class CurveGraphWidget(VisualEditorCanvas):" in source
    assert "class CurveControl(QWidget):" in source
    assert "Edit curve…" not in source
    assert '"filter.curve": "tone"' in source
    assert '"signal.curve": "animation"' in source
    assert "super().__init__(editor_height=250" in source
    assert "mouseDoubleClickEvent" in source
    assert "Qt.Key.Key_Delete" in source

    # Tone Curve remains neutral at its default and still accepts eight authored
    # response points through the existing evaluator contract.
    ramp = np.linspace(0.0, 1.0, 9, dtype=np.float32)
    image = np.stack((ramp, ramp, ramp, np.ones_like(ramp)), axis=1)[None, ...]
    context = EvalContext(width=image.shape[1], height=image.shape[0])
    neutral = tone.evaluator({"Image": image}, tone.default_parameters(), context)
    assert np.allclose(neutral, image, atol=1e-6)

    linear_params = tone.default_parameters()
    linear_params.update({
        "interpolation": "Linear",
        "points": [
            {"x": 0.0, "y": 0.0},
            {"x": 0.5, "y": 1.0},
            {"x": 1.0, "y": 0.0},
        ],
    })
    shaped = tone.evaluator({"Image": image}, linear_params, context)
    assert np.isclose(shaped[0, 4, 0], 1.0, atol=1e-6)
    assert np.isclose(shaped[0, -1, 0], 0.0, atol=1e-6)

    # Animation Curve keeps the original wide coordinate semantics.
    signal_params = animation.default_parameters()
    signal_params.update({
        "interpolation": "Linear",
        "points": [{"x": -2.0, "y": -4.0}, {"x": 2.0, "y": 4.0}],
    })
    output = animation.signal_evaluator({"Value": 1.0}, signal_params, context)
    assert np.isclose(output, 2.0, atol=1e-6)

    print("curve editor test passed")


if __name__ == "__main__":
    main()
