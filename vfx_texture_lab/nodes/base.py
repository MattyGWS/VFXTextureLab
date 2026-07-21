from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

ImageArray = np.ndarray
SignalValueType = float | tuple[float, ...]

# Public graph-port kinds. Image kinds are deliberately semantic rather than
# merely channel counts: a packed colour texture and a greyscale mask are not
# interchangeable without an explicit conversion node.
IMAGE_KINDS = frozenset({"grayscale", "color", "vector", "image_any"})
SIGNAL_KINDS = frozenset({"scalar", "vector2", "vector3", "material"})
GEOMETRY_KINDS = frozenset({"geometry"})
PUBLIC_PORT_KINDS = frozenset((*IMAGE_KINDS, *SIGNAL_KINDS, *GEOMETRY_KINDS, "any"))


def is_image_kind(kind: str) -> bool:
    return str(kind) in IMAGE_KINDS or str(kind) == "image"


def normalise_port_kind(kind: str) -> str:
    value = str(kind or "").strip().lower()
    aliases = {
        "image": "image_any",
        "grey": "grayscale",
        "gray": "grayscale",
        "greyscale": "grayscale",
        "colour": "color",
        "normal": "vector",
        "signal": "scalar",
        "pbr_material": "material",
        "mesh": "geometry",
    }
    return aliases.get(value, value or "image_any")


def port_kinds_compatible(source: str, target: str) -> bool:
    source = normalise_port_kind(source)
    target = normalise_port_kind(target)
    if source == target:
        return True
    if source == "any" or target == "any":
        return source in PUBLIC_PORT_KINDS and target in PUBLIC_PORT_KINDS
    if source == "image_any" and target in IMAGE_KINDS:
        return True
    if target == "image_any" and source in IMAGE_KINDS:
        return True
    return False


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    label: str
    kind: str
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    options: tuple[str, ...] = ()
    description: str = ""
    # When true, the Parameters panel can expose this value as a graph socket.
    animatable: bool = False
    # Optional author-facing section name. Built-in nodes without explicit
    # metadata are grouped consistently by the Parameters panel.
    group: str = ""
    group_order: int = 100
    # Optional interaction metadata. ``minimum``/``maximum`` remain the hard
    # accepted numeric bounds, while slider bounds can describe a narrower,
    # artist-friendly everyday range. Values typed outside the slider range
    # remain valid and simply pin the slider handle to the nearest end.
    slider_minimum: float | int | None = None
    slider_maximum: float | int | None = None
    # Modifier snapping used by shared numeric controls. Ctrl selects the fine
    # step and Shift selects the coarse step while dragging or stepping.
    fine_step: float | int | None = None
    coarse_step: float | int | None = None
    # Specialised presentation hint. ``angle`` adds the reusable direction dial
    # while preserving the ordinary slider and precise numeric editor.
    editor: str = ""
    unit: str = ""
    # Direction dials wrap through their soft range by default. Multi-turn
    # operations such as Rotate and Swirl opt out so accumulated degrees remain
    # meaningful in the numeric value.
    angle_wrap: bool = True
    # Optional conditional UI visibility. Every entry names another parameter
    # and the values for which this parameter should be shown. Evaluation and
    # serialisation are unaffected; hidden controls retain their authored value.
    visible_when: tuple[tuple[str, tuple[Any, ...]], ...] = ()
    # Random seed parameters are remapped by Graph Instance so one public seed
    # can coherently vary all stochastic nodes inside a nested graph asset.
    is_random_seed: bool = False
    # Technical/internal parameters can opt out of graph-asset publication even
    # when they are exposed as ordinary animation sockets.
    graph_asset_publishable: bool = True


@dataclass(frozen=True, slots=True)
class EvalContext:
    width: int
    height: int
    time_seconds: float = 0.0
    frame_number: int = 0
    frame_position: float = 0.0
    delta_time: float = 1.0 / 30.0
    duration_seconds: float = 4.0
    normalised_time: float = 0.0
    loop_phase: float = 0.0
    frames_per_second: float = 30.0
    document_frame_count: int = 120
    loop_start_frame: int = 0
    loop_end_frame: int = 119
    # "interactive" is a deliberately reduced-cost live drag, "preview" and
    # "preview_3d" use authored preview settings, and "final" uses final/export
    # settings. Nodes that do not vary by render mode simply ignore this field.
    render_mode: str = "preview"


Evaluator = Callable[[Mapping[str, ImageArray], Mapping[str, Any], EvalContext], ImageArray]
SignalEvaluator = Callable[[Mapping[str, SignalValueType], Mapping[str, Any], EvalContext], Mapping[str, SignalValueType] | SignalValueType]
GeometryEvaluator = Callable[[Mapping[str, Any], Mapping[str, Any]], Any]


@dataclass(slots=True)
class StatefulFrame:
    """CPU reference result for one deterministic simulation frame.

    ``state`` contains the private textures required by the following frame.
    ``output`` is the image exposed through the node's public output socket.
    Keeping these separate permits nodes such as Frame Delay to store the
    current input while exposing the previous input.
    """

    state: dict[str, ImageArray]
    output: ImageArray


StateInitializer = Callable[[Mapping[str, ImageArray], Mapping[str, Any], EvalContext], StatefulFrame]
StateStepper = Callable[[Mapping[str, ImageArray], Mapping[str, ImageArray], Mapping[str, Any], EvalContext], StatefulFrame]


@dataclass(frozen=True, slots=True)
class StatefulNodeSpec:
    """Declarative contract for a node whose frame depends on prior state.

    The evaluator owns checkpoints, cancellation, backend resources and
    invalidation. Node implementations only describe deterministic frame-zero
    initialisation and a single subsequent step.
    """

    state_slots: tuple[str, ...]
    initializer: StateInitializer
    stepper: StateStepper
    checkpoint_interval: int = 15
    gpu_supported: bool = False


@dataclass(frozen=True, slots=True)
class ShaderParameterBinding:
    """How a declarative package parameter is packed into the public WGSL ABI."""

    name: str
    kind: str
    offset: int
    width: int = 1
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NodePackageInfo:
    """Source metadata for a declarative WGSL node package."""

    package_id: str
    version: str
    api_version: int
    root: str
    manifest_path: str
    shader_path: str
    source_kind: str
    library_name: str
    revision: str
    icon_path: str | None = None

    @property
    def root_path(self) -> Path:
        return Path(self.root)

    @property
    def shader_file(self) -> Path:
        return Path(self.shader_path)


@dataclass(frozen=True, slots=True)
class GpuNodeSpec:
    """Declarative GPU execution metadata used by external node packages."""

    shader_path: str
    parameter_bindings: tuple[ShaderParameterBinding, ...] = ()
    input_defaults: tuple[tuple[str, float], ...] = ()
    format_policy: str = "declared"
    package: NodePackageInfo | None = None
    uses_time: bool = False

    def input_default(self, name: str) -> float:
        for input_name, value in self.input_defaults:
            if input_name == name:
                return float(value)
        return 0.0


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    type_id: str
    name: str
    category: str
    evaluator: Evaluator | None
    inputs: tuple[str, ...] = ()
    parameters: tuple[ParameterSpec, ...] = ()
    description: str = ""
    accent: str = "#6876df"
    tags: tuple[str, ...] = field(default_factory=tuple)
    output_format: str = "rgba16f"
    gpu_kernel: str | None = None
    gpu_spec: GpuNodeSpec | None = None
    output_name: str = "Image"
    outputs: tuple[str, ...] = ()
    # Nodes with several logical outputs may render one output at a time by
    # overriding a hidden/preview parameter. This keeps the public WGSL ABI
    # simple while still providing proper named output sockets.
    named_output_parameter: str | None = None
    named_output_values: tuple[tuple[str, Any], ...] = ()
    missing: bool = False
    missing_reason: str = ""
    # Graph-only helper definitions (for example reroute dots) remain
    # serializable/evaluable but are hidden from the ordinary node library.
    hidden: bool = False
    # Stateful simulations are evaluated sequentially and checkpointed by the
    # engine rather than entering the ordinary per-frame content cache.
    stateful: StatefulNodeSpec | None = None

    # Typed graph metadata. image_any is resolved from the connected branch.
    input_kinds: tuple[tuple[str, str], ...] = ()
    output_kinds: tuple[tuple[str, str], ...] = ()
    # Stable internal socket names can keep parent connections intact while
    # these labels change in a graph asset interface.
    input_labels: tuple[tuple[str, str], ...] = ()
    output_labels: tuple[tuple[str, str], ...] = ()
    signal_evaluator: SignalEvaluator | None = None
    # Geometry nodes evaluate resolution-independent indexed mesh values.  They
    # are kept separate from image and signal execution so adding geometry does
    # not disturb the mature texture cache/backend pipeline.
    geometry_evaluator: GeometryEvaluator | None = None
    uses_time: bool = False
    # fixed: declared kinds are final. preserve_primary: image_any ports follow
    # primary_input. blend_match: Foreground/Background/output resolve to the first connected one.
    # image_input: output follows the Image Input Data type control.
    # parameter_output: output follows an explicit Output data type parameter.
    # accept_any_input: wildcard image inputs accept greyscale, colour or vector
    # while fixed outputs retain their declared semantic kinds.
    type_policy: str = "fixed"
    primary_input: str | None = None
    default_image_kind: str = "grayscale"
    # Terminal sinks consume graph data without exposing an output socket.
    # They remain ordinary snapshot nodes so branch revision and dependency
    # traversal continue to work, but cannot be connected downstream.
    terminal: bool = False

    @property
    def output_names(self) -> tuple[str, ...]:
        if self.terminal:
            return ()
        return self.outputs or (self.output_name,)

    def named_output_value(self, output_name: str) -> Any | None:
        for name, value in self.named_output_values:
            if name == output_name:
                return value
        return None

    def default_parameters(self) -> dict[str, Any]:
        values = {spec.name: spec.default for spec in self.parameters}
        if any(is_image_kind(self.output_kind(name)) for name in self.output_names):
            values.setdefault("_precision", "Inherit")
            values.setdefault("_resolved_kind", self.default_image_kind)
        return values

    @property
    def package(self) -> NodePackageInfo | None:
        return self.gpu_spec.package if self.gpu_spec is not None else None

    @property
    def is_external(self) -> bool:
        return self.package is not None

    @property
    def is_signal_node(self) -> bool:
        return self.signal_evaluator is not None

    @property
    def is_stateful(self) -> bool:
        return self.stateful is not None

    @property
    def is_geometry_node(self) -> bool:
        return self.geometry_evaluator is not None

    def input_kind(self, name: str) -> str:
        for candidate, kind in self.input_kinds:
            if candidate == name:
                return normalise_port_kind(kind)
        return "image_any"

    def output_kind(self, name: str) -> str:
        for candidate, kind in self.output_kinds:
            if candidate == name:
                return normalise_port_kind(kind)
        return "image_any"

    def input_label(self, name: str) -> str:
        for candidate, label in self.input_labels:
            if candidate == name:
                return str(label)
        return str(name)

    def output_label(self, name: str) -> str:
        for candidate, label in self.output_labels:
            if candidate == name:
                return str(label)
        return str(name)

    def parameter_spec(self, name: str) -> ParameterSpec | None:
        return next((spec for spec in self.parameters if spec.name == name), None)

    def snapshot(self) -> dict[str, Any]:
        """Minimal interface metadata embedded in graph files for placeholders."""
        package = self.package
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "accent": self.accent,
            "inputs": list(self.inputs),
            "input_kinds": [list(item) for item in self.input_kinds],
            "input_labels": [list(item) for item in self.input_labels],
            "output_format": self.output_format,
            "output_name": self.output_name,
            "outputs": list(self.output_names),
            "output_kinds": [list(item) for item in self.output_kinds],
            "output_labels": [list(item) for item in self.output_labels],
            "named_output_parameter": self.named_output_parameter,
            "named_output_values": [list(item) for item in self.named_output_values],
            "terminal": self.terminal,
            "package_id": package.package_id if package else self.type_id,
            "package_version": package.version if package else None,
            "api_version": package.api_version if package else None,
        }
