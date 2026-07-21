from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .nodes.base import EvalContext, NodeDefinition, ParameterSpec, normalise_port_kind

GRAPH_INPUT_TYPE = "graph.input"
GRAPH_OUTPUT_TYPE = "graph.output"
GRAPH_INSTANCE_TYPE = "graph.instance"
GRAPH_ASSET_FORMAT = "vfx-texture-lab-graph"
GRAPH_ASSET_INTERFACE_VERSION = 1

DATA_TYPE_TO_KIND = {
    "Greyscale": "grayscale",
    "Grayscale": "grayscale",
    "Colour": "color",
    "Color": "color",
    "Vector / Normal": "vector",
    "Vector": "vector",
    "Signal": "scalar",
    "Scalar": "scalar",
    "Material": "material",
    "Geometry": "geometry",
}
KIND_TO_DATA_TYPE = {
    "grayscale": "Greyscale",
    "color": "Colour",
    "vector": "Vector / Normal",
    "scalar": "Signal",
    "material": "Material",
    "geometry": "Geometry",
}
CONCRETE_PUBLIC_KINDS = frozenset(KIND_TO_DATA_TYPE)


def stable_interface_id(prefix: str, node_uid: str, suffix: str = "") -> str:
    text = f"{prefix}:{node_uid}:{suffix}".encode("utf-8")
    return hashlib.blake2b(text, digest_size=12).hexdigest()


def source_revision(data: Mapping[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.blake2b(encoded, digest_size=20).hexdigest()


def _serialisable_parameter_spec(spec: ParameterSpec) -> dict[str, Any]:
    result = asdict(spec)
    result["options"] = list(spec.options)
    result["visible_when"] = [[name, list(values)] for name, values in spec.visible_when]
    return result


def parameter_spec_from_dict(data: Mapping[str, Any], *, name: str | None = None, label: str | None = None, default: Any = None) -> ParameterSpec:
    allowed = {field.name for field in fields(ParameterSpec)}
    payload = {key: deepcopy(value) for key, value in data.items() if key in allowed}
    payload["name"] = str(name if name is not None else payload.get("name", "value"))
    payload["label"] = str(label if label is not None else payload.get("label", payload["name"]))
    if default is not None:
        payload["default"] = deepcopy(default)
    payload.setdefault("kind", "float")
    payload.setdefault("default", 0.0)
    payload["options"] = tuple(str(value) for value in payload.get("options", ()))
    visible = []
    for entry in payload.get("visible_when", ()):
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            visible.append((str(entry[0]), tuple(entry[1])))
    payload["visible_when"] = tuple(visible)
    return ParameterSpec(**payload)


def graph_input_kind(parameters: Mapping[str, Any]) -> str:
    return DATA_TYPE_TO_KIND.get(str(parameters.get("data_type", "Greyscale")), "grayscale")


def _definition_for_node(registry, node_data: Mapping[str, Any]) -> NodeDefinition | None:
    type_id = str(node_data.get("type", ""))
    if type_id == GRAPH_INSTANCE_TYPE:
        try:
            return graph_instance_definition(dict(node_data.get("parameters", {})))
        except Exception:
            return None
    definition = registry.get_optional(type_id)
    if definition is not None:
        return definition
    snapshot = node_data.get("definition")
    if not isinstance(snapshot, Mapping):
        return None
    inputs = tuple(str(value) for value in snapshot.get("inputs", ()))
    outputs = tuple(str(value) for value in snapshot.get("outputs", ()))
    return NodeDefinition(
        type_id=type_id,
        name=str(snapshot.get("name", type_id or "Missing Node")),
        category=str(snapshot.get("category", "Missing Nodes")),
        evaluator=None,
        inputs=inputs,
        description=str(snapshot.get("description", "")),
        accent=str(snapshot.get("accent", "#a54652")),
        output_name=str(snapshot.get("output_name", "Image")),
        outputs=outputs,
        input_kinds=tuple((str(a), str(b)) for a, b in snapshot.get("input_kinds", ())),
        output_kinds=tuple((str(a), str(b)) for a, b in snapshot.get("output_kinds", ())),
        input_labels=tuple((str(a), str(b)) for a, b in snapshot.get("input_labels", ())),
        output_labels=tuple((str(a), str(b)) for a, b in snapshot.get("output_labels", ())),
        terminal=bool(snapshot.get("terminal", False)),
        missing=True,
    )


def _source_map(data: Mapping[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for connection in data.get("connections", ()):
        if not isinstance(connection, Mapping):
            continue
        target = str(connection.get("target", ""))
        input_name = str(connection.get("input", ""))
        source = str(connection.get("source", ""))
        output_name = str(connection.get("source_output", "Image") or "Image")
        if target and input_name and source:
            result[(target, input_name)] = (source, output_name)
    return result


def _resolve_serialised_output_kind(
    registry,
    nodes: Mapping[str, Mapping[str, Any]],
    sources: Mapping[tuple[str, str], tuple[str, str]],
    node_uid: str,
    output_name: str,
    visiting: set[tuple[str, str]] | None = None,
) -> str:
    key = (str(node_uid), str(output_name))
    visiting = set() if visiting is None else visiting
    if key in visiting:
        return "any"
    visiting.add(key)
    node_data = nodes.get(str(node_uid))
    if node_data is None:
        return "any"
    type_id = str(node_data.get("type", ""))
    params = dict(node_data.get("parameters", {}))
    if type_id == GRAPH_INPUT_TYPE:
        return graph_input_kind(params)
    if type_id == "graph.receive":
        sender_uid = str(params.get("sender_uid", ""))
        source = sources.get((sender_uid, "Input"))
        if source is not None:
            return _resolve_serialised_output_kind(registry, nodes, sources, source[0], source[1], visiting)
    definition = _definition_for_node(registry, node_data)
    if definition is None:
        return normalise_port_kind(str(params.get("_resolved_kind", "any")))
    kind = definition.output_kind(output_name)
    if kind == "image_any":
        resolved = normalise_port_kind(str(params.get("_resolved_kind", definition.default_image_kind)))
        return resolved if resolved in CONCRETE_PUBLIC_KINDS else definition.default_image_kind
    return kind


def _public_parameter_metadata(node_data: Mapping[str, Any], parameter_name: str, spec: ParameterSpec) -> dict[str, Any]:
    params = dict(node_data.get("parameters", {}))
    all_meta = params.get("_graph_asset_parameter_meta", {})
    meta = dict(all_meta.get(parameter_name, {})) if isinstance(all_meta, Mapping) else {}
    node_uid = str(node_data.get("uid", ""))
    interface_id = str(meta.get("interface_id") or stable_interface_id("parameter", node_uid, parameter_name))
    return {
        "id": interface_id,
        "node": node_uid,
        "parameter": parameter_name,
        "name": str(meta.get("name") or spec.label),
        "description": str(meta.get("description") or spec.description),
        "group": str(meta.get("group") or spec.group or "Parameters"),
        "order": int(meta.get("order", spec.group_order)),
        "default": deepcopy(params.get(parameter_name, spec.default)),
        "spec": _serialisable_parameter_spec(spec),
    }


def parse_graph_asset_interface(data: Mapping[str, Any], registry, *, source_path: str | Path | None = None) -> dict[str, Any]:
    if str(data.get("format", "")) != GRAPH_ASSET_FORMAT:
        raise ValueError("The selected file is not a VFX Texture Lab graph.")
    node_entries = [entry for entry in data.get("nodes", ()) if isinstance(entry, Mapping)]
    nodes = {str(entry.get("uid", "")): entry for entry in node_entries if str(entry.get("uid", ""))}
    sources = _source_map(data)
    asset_meta = dict(data.get("graph_asset", {})) if isinstance(data.get("graph_asset"), Mapping) else {}
    source = Path(source_path).expanduser() if source_path else None
    default_name = source.stem if source is not None else "Graph Asset"

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    warnings: list[str] = []

    for node_data in node_entries:
        uid = str(node_data.get("uid", ""))
        type_id = str(node_data.get("type", ""))
        params = dict(node_data.get("parameters", {}))
        if type_id == GRAPH_INPUT_TYPE:
            interface_id = str(params.get("interface_id") or stable_interface_id("input", uid))
            kind = graph_input_kind(params)
            inputs.append({
                "id": interface_id,
                "port": f"input::{interface_id}",
                "node": uid,
                "name": str(params.get("name", "Input") or "Input"),
                "description": str(params.get("description", "")),
                "kind": kind,
                "required": bool(params.get("required", False)) or kind == "geometry",
                "order": int(params.get("order", 100)),
                "default": graph_input_default(params, kind),
            })
        elif type_id == GRAPH_OUTPUT_TYPE:
            interface_id = str(params.get("interface_id") or stable_interface_id("output", uid))
            source_ref = sources.get((uid, "Value"))
            if source_ref is None:
                warnings.append(f"Graph Output '{params.get('name', 'Output')}' is not connected and will not be published.")
                continue
            kind = _resolve_serialised_output_kind(registry, nodes, sources, source_ref[0], source_ref[1])
            if kind not in CONCRETE_PUBLIC_KINDS:
                warnings.append(f"Graph Output '{params.get('name', 'Output')}' has an unresolved data type.")
                continue
            outputs.append({
                "id": interface_id,
                "port": f"output::{interface_id}",
                "node": uid,
                "name": str(params.get("name", "Output") or "Output"),
                "description": str(params.get("description", "")),
                "kind": kind,
                "order": int(params.get("order", 100)),
                "primary_preview": bool(params.get("primary_preview", False)),
                "source_node": source_ref[0],
                "source_output": source_ref[1],
            })

    connected_inputs = {(str(entry.get("target", "")), str(entry.get("input", ""))) for entry in data.get("connections", ()) if isinstance(entry, Mapping)}
    for node_data in node_entries:
        definition = _definition_for_node(registry, node_data)
        if definition is None:
            continue
        params = dict(node_data.get("parameters", {}))
        exposed = {str(value) for value in params.get("_exposed_inputs", ())}
        unpublished = {str(value) for value in params.get("_graph_asset_unpublished_inputs", ())}
        for parameter_name in sorted(exposed):
            spec = definition.parameter_spec(parameter_name)
            if spec is None or not spec.graph_asset_publishable:
                continue
            if parameter_name in unpublished:
                continue
            if (str(node_data.get("uid", "")), f"@param:{parameter_name}") in connected_inputs:
                continue
            if spec.is_random_seed or parameter_name == "seed":
                continue
            parameters.append(_public_parameter_metadata(node_data, parameter_name, spec))

    inputs.sort(key=lambda item: (int(item["order"]), str(item["name"]).casefold(), str(item["id"])))
    outputs.sort(key=lambda item: (int(item["order"]), str(item["name"]).casefold(), str(item["id"])))
    parameters.sort(key=lambda item: (int(item["order"]), str(item["group"]).casefold(), str(item["name"]).casefold(), str(item["id"])))
    if outputs and not any(bool(entry.get("primary_preview")) for entry in outputs):
        outputs[0]["primary_preview"] = True

    revision = source_revision(data)
    identity = str(asset_meta.get("asset_id") or (source.resolve() if source is not None else revision))
    return {
        "version": GRAPH_ASSET_INTERFACE_VERSION,
        "asset_id": identity,
        "name": str(asset_meta.get("name") or default_name),
        "description": str(asset_meta.get("description", "Reusable VFX Texture Lab graph asset.")),
        "category": str(asset_meta.get("category", "Graph Assets") or "Graph Assets"),
        "tags": [str(value).strip() for value in asset_meta.get("tags", ()) if str(value).strip()],
        "author": str(asset_meta.get("author", "")),
        "asset_version": str(asset_meta.get("version", "1.0.0")),
        "created_with": str(asset_meta.get("created_with", "")),
        "thumbnail_png": str(asset_meta.get("thumbnail_png", "")),
        "thumbnail_source": str(asset_meta.get("thumbnail_source", "")),
        "revision": revision,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters,
        "warnings": warnings,
    }


def graph_input_default(parameters: Mapping[str, Any], kind: str | None = None) -> Any:
    kind = normalise_port_kind(kind or graph_input_kind(parameters))
    if kind == "color":
        return str(parameters.get("default_color", "#808080"))
    if kind == "vector":
        return [
            float(parameters.get("default_x", 0.5)),
            float(parameters.get("default_y", 0.5)),
            float(parameters.get("default_z", 1.0)),
        ]
    if kind == "scalar":
        return float(parameters.get("default_value", 0.0))
    if kind in {"material", "geometry"}:
        return None
    return float(parameters.get("default_value", 0.0))


def load_graph_asset(path: str | Path, registry) -> tuple[dict[str, Any], dict[str, Any]]:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    interface = parse_graph_asset_interface(data, registry, source_path=source)
    if not interface["outputs"]:
        raise ValueError("This graph has no connected Graph Output nodes.")
    return data, interface


def _external_parameter_name(interface_id: str) -> str:
    return f"asset_param::{interface_id}"


def graph_instance_definition(parameters: Mapping[str, Any]) -> NodeDefinition:
    interface = dict(parameters.get("_asset_interface", {}))
    inputs = tuple(str(entry["port"]) for entry in interface.get("inputs", ()))
    outputs = tuple(str(entry["port"]) for entry in interface.get("outputs", ()))
    specs: list[ParameterSpec] = [
        ParameterSpec(
            "random_seed", "Random Seed", "int", 0,
            0, 2147483647, 1,
            description="Coherently shifts every random seed inside this graph asset.",
            animatable=True,
            group="Variation", group_order=5,
            slider_maximum=1000, fine_step=1, coarse_step=10,
            is_random_seed=True,
        )
    ]
    for entry in interface.get("parameters", ()):
        if not isinstance(entry, Mapping):
            continue
        external_name = _external_parameter_name(str(entry.get("id", "")))
        spec = parameter_spec_from_dict(
            dict(entry.get("spec", {})),
            name=external_name,
            label=str(entry.get("name", external_name)),
            default=deepcopy(entry.get("default")),
        )
        # The public graph-asset grouping/description takes precedence over the
        # internal node's organisational metadata.
        spec = ParameterSpec(
            **{
                **asdict(spec),
                "options": tuple(spec.options),
                "visible_when": tuple(spec.visible_when),
                "description": str(entry.get("description") or spec.description),
                "group": str(entry.get("group") or spec.group or "Parameters"),
                "group_order": int(entry.get("order", spec.group_order)),
                "is_random_seed": False,
            }
        )
        specs.append(spec)
    output_name = outputs[0] if outputs else "Output"
    category = str(interface.get("category", "Graph Assets") or "Graph Assets")
    if not category.casefold().startswith("graph assets"):
        category = f"Graph Assets/{category}"
    return NodeDefinition(
        type_id=GRAPH_INSTANCE_TYPE,
        name=str(interface.get("name", "Graph Asset")),
        category=category,
        evaluator=None,
        inputs=inputs,
        parameters=tuple(specs),
        description=str(interface.get("description", "Nested VFX Texture Lab graph asset.")),
        accent="#8c61d8",
        tags=("graph", "asset", "nested", "subgraph", "instance"),
        output_name=output_name,
        outputs=outputs,
        input_kinds=tuple((str(entry["port"]), str(entry["kind"])) for entry in interface.get("inputs", ())),
        output_kinds=tuple((str(entry["port"]), str(entry["kind"])) for entry in interface.get("outputs", ())),
        input_labels=tuple((str(entry["port"]), str(entry["name"])) for entry in interface.get("inputs", ())),
        output_labels=tuple((str(entry["port"]), str(entry["name"])) for entry in interface.get("outputs", ())),
        default_image_kind="grayscale",
    )


def instance_parameters_for_asset(
    data: Mapping[str, Any], interface: Mapping[str, Any], *, source_path: str | Path | None, embedded: bool = False
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "_asset_mode": "Embedded" if embedded else "Linked",
        "_asset_path": str(Path(source_path).expanduser().resolve()) if source_path else "",
        "_asset_interface": deepcopy(dict(interface)),
        "_asset_revision": str(interface.get("revision", source_revision(data))),
        "_asset_identity": str(interface.get("asset_id", "")),
        "_asset_embedded_graph": deepcopy(dict(data)) if embedded else None,
        # A linked node keeps a last-known-good copy so missing files can still
        # render and can later be embedded or relinked without data loss.
        "_asset_cached_graph": deepcopy(dict(data)),
        "_asset_parameter_overrides": [],
        "random_seed": 0,
    }
    for entry in interface.get("parameters", ()):
        params[_external_parameter_name(str(entry.get("id", "")))] = deepcopy(entry.get("default"))
    return params


def graph_input_image(_inputs: Mapping[str, np.ndarray], parameters: Mapping[str, Any], context: EvalContext) -> np.ndarray:
    kind = graph_input_kind(parameters)
    result = np.zeros((context.height, context.width, 4), dtype=np.float32)
    result[..., 3] = 1.0
    if kind == "color":
        text = str(parameters.get("default_color", "#808080")).lstrip("#")
        try:
            if len(text) == 6:
                rgb = [int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
            else:
                rgb = [0.5, 0.5, 0.5]
        except ValueError:
            rgb = [0.5, 0.5, 0.5]
        result[..., :3] = np.asarray(rgb, dtype=np.float32)
    elif kind == "vector":
        result[..., 0] = float(parameters.get("default_x", 0.5))
        result[..., 1] = float(parameters.get("default_y", 0.5))
        result[..., 2] = float(parameters.get("default_z", 1.0))
    else:
        value = float(parameters.get("default_value", 0.0))
        result[..., :3] = value
    return result


def graph_input_signal(_inputs, parameters: Mapping[str, Any], _context: EvalContext):
    return {"Value": float(parameters.get("default_value", 0.0))}


def derive_seed(instance_seed: int, original_seed: int, identity: str) -> int:
    payload = f"{int(instance_seed)}:{int(original_seed)}:{identity}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=4).digest(), "little") & 0x7FFFFFFF


def asset_graph_data(parameters: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(parameters.get("_asset_mode", "Linked"))
    if mode == "Embedded" and isinstance(parameters.get("_asset_embedded_graph"), Mapping):
        return deepcopy(dict(parameters["_asset_embedded_graph"]))
    cached = parameters.get("_asset_cached_graph")
    if isinstance(cached, Mapping):
        return deepcopy(dict(cached))
    path = str(parameters.get("_asset_path", ""))
    if path:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    raise ValueError("The Graph Instance has no linked or embedded source graph.")


def graph_asset_dependency_paths(data: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for node in data.get("nodes", ()):
        if not isinstance(node, Mapping) or str(node.get("type", "")) != GRAPH_INSTANCE_TYPE:
            continue
        params = dict(node.get("parameters", {}))
        path = str(params.get("_asset_path", ""))
        if path:
            paths.append(path)
    return paths

# Public alias used by the nested evaluator and migration code.
def definition_for_serialised_node(registry, node_data: Mapping[str, Any]) -> NodeDefinition | None:
    return _definition_for_node(registry, node_data)


def external_parameter_name(interface_id: str) -> str:
    return _external_parameter_name(interface_id)
