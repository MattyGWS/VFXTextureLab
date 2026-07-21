from __future__ import annotations

import math
from typing import Any, Mapping

from .base import EvalContext, NodeDefinition, ParameterSpec, SignalValueType
from .registry import NodeRegistry


def _scalar(value: SignalValueType | None, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, tuple):
        return float(value[0]) if value else float(default)
    return float(value)


def eval_time(_inputs: Mapping[str, SignalValueType], _params: Mapping[str, Any], context: EvalContext):
    return {
        "Seconds": float(context.time_seconds),
        "Frame": float(context.frame_position),
        "Document Phase": float(context.normalised_time),
        "Loop Phase": float(context.loop_phase),
        "Delta Seconds": float(context.delta_time),
    }


def _phase_for_range(context: EvalContext, range_mode: str, start: int, end: int) -> tuple[float, float, int]:
    if range_mode == "Entire Document":
        start = 0
        end = max(int(context.document_frame_count) - 1, 0)
    elif range_mode == "Document Loop":
        start = int(context.loop_start_frame)
        end = int(context.loop_end_frame)
    else:
        start = max(int(start), 0)
        end = max(int(end), start)
    count = max(end - start + 1, 1)
    local = float(context.frame_position) - float(start)
    return (local / float(count)) % 1.0, local, count


def eval_loop_phase(_inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], context: EvalContext):
    base, local, frame_count = _phase_for_range(
        context,
        str(params.get("range", "Document Loop")),
        int(params.get("start_frame", 0)),
        int(params.get("end_frame", 63)),
    )
    cycles = float(params.get("cycles", 1.0))
    offset = float(params.get("phase_offset", 0.0))
    raw = base * cycles + offset
    phase = raw % 1.0
    if bool(params.get("reverse", False)):
        phase = (-phase) % 1.0
    if bool(params.get("ping_pong", False)):
        phase = 1.0 - abs(phase * 2.0 - 1.0)
    # Pulse is one only at a mathematically exact cycle boundary. On ordinary
    # integer timeline frames this yields a clean one-frame restart trigger.
    pulse = 1.0 if abs(raw - round(raw)) < 1e-7 else 0.0
    frame_index = local % float(frame_count)
    return {
        "Phase": phase,
        "Angle": phase * math.tau,
        "Frame Index": frame_index,
        "Pulse": pulse,
    }


def eval_cycle(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], context: EvalContext):
    source = _scalar(inputs.get("Time"), context.time_seconds)
    duration = max(float(params.get("duration", 1.0)), 1e-6)
    phase = float(params.get("phase", 0.0))
    value = (source / duration + phase) % 1.0
    if bool(params.get("reverse", False)):
        value = 1.0 - value
    if bool(params.get("ping_pong", False)):
        value = 1.0 - abs(value * 2.0 - 1.0)
    return value


def eval_wave(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], context: EvalContext):
    source = _scalar(inputs.get("Signal"), context.time_seconds)
    frequency = float(params.get("frequency", 1.0))
    phase = float(params.get("phase", 0.0))
    angle = (source * frequency + phase) * math.tau
    waveform = str(params.get("waveform", "Sine"))
    if waveform == "Cosine":
        base = math.cos(angle)
    elif waveform == "Triangle":
        t = (source * frequency + phase) % 1.0
        base = 1.0 - 4.0 * abs(t - 0.5)
    elif waveform == "Sawtooth":
        base = ((source * frequency + phase) % 1.0) * 2.0 - 1.0
    elif waveform == "Square":
        base = 1.0 if math.sin(angle) >= 0.0 else -1.0
    elif waveform == "Pulse":
        duty = min(max(float(params.get("duty", 0.5)), 0.001), 0.999)
        base = 1.0 if ((source * frequency + phase) % 1.0) < duty else -1.0
    else:
        base = math.sin(angle)
    return base * float(params.get("amplitude", 1.0)) + float(params.get("offset", 0.0))


def eval_scalar_math(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    a = _scalar(inputs.get("A"), float(params.get("a", 0.0)))
    b = _scalar(inputs.get("B"), float(params.get("b", 1.0)))
    mode = str(params.get("operation", "Add"))
    if mode == "Subtract":
        return a - b
    if mode == "Multiply":
        return a * b
    if mode == "Divide":
        return a / b if abs(b) > 1e-12 else 0.0
    if mode == "Minimum":
        return min(a, b)
    if mode == "Maximum":
        return max(a, b)
    if mode == "Power":
        try:
            return math.pow(a, b)
        except (ValueError, OverflowError):
            return 0.0
    if mode == "Modulo":
        return a % b if abs(b) > 1e-12 else 0.0
    if mode == "Absolute":
        return abs(a)
    return a + b


def eval_remap(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    value = _scalar(inputs.get("Value"), 0.0)
    in_min = float(params.get("in_min", 0.0))
    in_max = float(params.get("in_max", 1.0))
    out_min = float(params.get("out_min", 0.0))
    out_max = float(params.get("out_max", 1.0))
    span = in_max - in_min
    t = 0.0 if abs(span) < 1e-12 else (value - in_min) / span
    if bool(params.get("clamp", False)):
        t = min(max(t, 0.0), 1.0)
    return out_min + (out_max - out_min) * t


def eval_clamp(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    value = _scalar(inputs.get("Value"), 0.0)
    return min(max(value, float(params.get("minimum", 0.0))), float(params.get("maximum", 1.0)))


def eval_smoothstep(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    value = _scalar(inputs.get("Value"), 0.0)
    edge0 = float(params.get("edge0", 0.0))
    edge1 = float(params.get("edge1", 1.0))
    if abs(edge1 - edge0) < 1e-12:
        return 0.0
    t = min(max((value - edge0) / (edge1 - edge0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def eval_curve(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    value = _scalar(inputs.get("Value"), 0.0)
    raw = params.get("points")
    points: list[tuple[float, float]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                try:
                    points.append((float(item.get("x", 0.0)), float(item.get("y", 0.0))))
                except (TypeError, ValueError):
                    pass
    if not points:
        points = [(0.0, 0.0), (1.0, 1.0)]
    points.sort()
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for index in range(len(points) - 1):
        x0, y0 = points[index]
        x1, y1 = points[index + 1]
        if x0 <= value <= x1:
            t = 0.0 if abs(x1 - x0) < 1e-12 else (value - x0) / (x1 - x0)
            if str(params.get("interpolation", "Smooth")) == "Smooth":
                t = t * t * (3.0 - 2.0 * t)
            return y0 + (y1 - y0) * t
    return value



def eval_combine_vector2(inputs: Mapping[str, SignalValueType], params: Mapping[str, Any], _context: EvalContext):
    return (
        _scalar(inputs.get("X"), float(params.get("x", 0.0))),
        _scalar(inputs.get("Y"), float(params.get("y", 0.0))),
    )


def eval_split_vector2(inputs: Mapping[str, SignalValueType], _params: Mapping[str, Any], _context: EvalContext):
    value = inputs.get("Vector", (0.0, 0.0))
    if isinstance(value, tuple):
        x = float(value[0]) if value else 0.0
        y = float(value[1]) if len(value) > 1 else 0.0
    else:
        x = y = float(value)
    return {"X": x, "Y": y}

def register_signal_nodes(registry: NodeRegistry) -> None:
    p = ParameterSpec
    scalar_in = lambda *names: tuple((name, "scalar") for name in names)
    scalar_out = lambda *names: tuple((name, "scalar") for name in names)
    vector_in = lambda *names: tuple((name, "vector2") for name in names)
    vector_out = lambda *names: tuple((name, "vector2") for name in names)
    definitions = [
        NodeDefinition(
            "signal.time", "Time", "Animation", None,
            outputs=("Seconds", "Frame", "Document Phase", "Loop Phase", "Delta Seconds"),
            output_kinds=scalar_out("Seconds", "Frame", "Document Phase", "Loop Phase", "Delta Seconds"),
            signal_evaluator=eval_time, uses_time=True,
            description="Global document time values. Loop Phase is a seamless exclusive-end 0–1 ramp over the document loop.",
            accent="#d05e91", tags=("animation", "frame", "seconds", "delta", "loop phase"),
        ),
        NodeDefinition(
            "signal.loop_phase", "Loop Phase", "Animation", None,
            outputs=("Phase", "Angle", "Frame Index", "Pulse"),
            output_kinds=scalar_out("Phase", "Angle", "Frame Index", "Pulse"),
            signal_evaluator=eval_loop_phase, uses_time=True,
            parameters=(
                p("range", "Range", "enum", "Document Loop", options=("Document Loop", "Entire Document", "Custom Frame Range")),
                p("start_frame", "Custom Start", "int", 0, 0, 100000, 1, slider_maximum=1000, fine_step=1, coarse_step=10),
                p("end_frame", "Custom End", "int", 63, 0, 100000, 1, slider_maximum=1000, fine_step=1, coarse_step=10),
                p("cycles", "Cycles", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("phase_offset", "Phase Offset", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("reverse", "Reverse", "bool", False),
                p("ping_pong", "Ping-pong", "bool", False),
            ),
            description="Artist-friendly loop signal independent of flipbook grid size and document FPS.",
            accent="#d05e91", tags=("loop", "phase", "flipbook", "cycle", "angle"),
        ),
        NodeDefinition(
            "signal.cycle", "Cycle", "Animation", None, inputs=("Time",),
            input_kinds=scalar_in("Time"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_cycle, uses_time=True,
            parameters=(
                p("duration", "Duration", "float", 1.0, 0.001, 120.0, 0.01, animatable=True, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("phase", "Phase", "float", 0.0, -10.0, 10.0, 0.01, animatable=True),
                p("reverse", "Reverse", "bool", False),
                p("ping_pong", "Ping-pong", "bool", False),
            ),
            description="Repeating 0–1 ramp. Unconnected Time uses document seconds.",
            accent="#d05e91", tags=("loop", "ramp", "mod cycle"),
        ),
        NodeDefinition(
            "signal.wave", "Wave", "Animation", None, inputs=("Signal",),
            input_kinds=scalar_in("Signal"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_wave, uses_time=True,
            parameters=(
                p("waveform", "Waveform", "enum", "Sine", options=("Sine", "Cosine", "Triangle", "Sawtooth", "Square", "Pulse")),
                p("frequency", "Frequency", "float", 1.0, -100.0, 100.0, 0.01, animatable=True, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("amplitude", "Amplitude", "float", 1.0, -100.0, 100.0, 0.01, animatable=True, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("offset", "Offset", "float", 0.0, -100.0, 100.0, 0.01, animatable=True, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("phase", "Phase", "float", 0.0, -10.0, 10.0, 0.01, animatable=True),
                p("duty", "Pulse Duty", "float", 0.5, 0.001, 0.999, 0.01),
            ),
            description="Waveform oscillator. Unconnected Signal uses document seconds.",
            accent="#d05e91", tags=("sin", "cos", "triangle", "saw", "oscillator"),
        ),
        NodeDefinition(
            "signal.math", "Scalar Math", "Animation", None, inputs=("A", "B"),
            input_kinds=scalar_in("A", "B"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_scalar_math,
            parameters=(
                p("operation", "Operation", "enum", "Add", options=("Add", "Subtract", "Multiply", "Divide", "Minimum", "Maximum", "Power", "Modulo", "Absolute")),
                p("a", "A Default", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("b", "B Default", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
            ),
            accent="#d05e91", tags=("add", "multiply", "modulate"),
        ),
        NodeDefinition(
            "signal.remap", "Remap", "Animation", None, inputs=("Value",),
            input_kinds=scalar_in("Value"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_remap,
            parameters=(
                p("in_min", "Input Min", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("in_max", "Input Max", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("out_min", "Output Min", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("out_max", "Output Max", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("clamp", "Clamp", "bool", True),
            ),
            accent="#d05e91", tags=("range", "map", "scale"),
        ),
        NodeDefinition(
            "signal.clamp", "Clamp", "Animation", None, inputs=("Value",),
            input_kinds=scalar_in("Value"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_clamp,
            parameters=(
                p("minimum", "Minimum", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("maximum", "Maximum", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
            ),
            accent="#d05e91", tags=("limit", "range"),
        ),
        NodeDefinition(
            "signal.smoothstep", "Smoothstep", "Animation", None, inputs=("Value",),
            input_kinds=scalar_in("Value"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_smoothstep,
            parameters=(
                p("edge0", "Lower Edge", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("edge1", "Upper Edge", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
            ),
            accent="#d05e91", tags=("ease", "soft threshold"),
        ),
        NodeDefinition(
            "signal.combine_vector2", "Combine Vector2", "Animation", None, inputs=("X", "Y"),
            input_kinds=scalar_in("X", "Y"), output_kinds=vector_out("Vector"), output_name="Vector",
            signal_evaluator=eval_combine_vector2,
            parameters=(
                p("x", "X Default", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
                p("y", "Y Default", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=0.1),
            ),
            description="Combine two scalar signals into a Vector2 signal.",
            accent="#d05e91", tags=("vector", "xy", "combine"),
        ),
        NodeDefinition(
            "signal.split_vector2", "Split Vector2", "Animation", None, inputs=("Vector",),
            input_kinds=vector_in("Vector"), outputs=("X", "Y"), output_kinds=scalar_out("X", "Y"),
            signal_evaluator=eval_split_vector2,
            description="Split a Vector2 signal into independent X and Y scalars.",
            accent="#d05e91", tags=("vector", "xy", "split"),
        ),
        NodeDefinition(
            "signal.curve", "Animation Curve", "Animation", None, inputs=("Value",),
            input_kinds=scalar_in("Value"), output_kinds=scalar_out("Value"), output_name="Value",
            signal_evaluator=eval_curve,
            parameters=(
                p("points", "Curve", "curve", [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]),
                p("interpolation", "Interpolation", "enum", "Smooth", options=("Linear", "Smooth")),
            ),
            description="Remap a scalar signal with an inline editable animation curve.",
            accent="#d05e91", tags=("ease", "animation curve", "ramp"),
        ),
    ]
    for definition in definitions:
        registry.register(definition)
