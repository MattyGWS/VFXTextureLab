from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .base import NodeDefinition, ParameterSpec


class NodeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, NodeDefinition] = {}
        self._package_type_ids: set[str] = set()

    def register(self, definition: NodeDefinition, *, package: bool = False, replace: bool = False) -> None:
        if definition.type_id in self._definitions and not replace:
            raise ValueError(f"Node type already registered: {definition.type_id}")
        self._definitions[definition.type_id] = definition
        if package:
            self._package_type_ids.add(definition.type_id)

    def replace_package_definitions(self, definitions: Iterable[NodeDefinition]) -> None:
        for type_id in tuple(self._package_type_ids):
            self._definitions.pop(type_id, None)
        self._package_type_ids.clear()
        for definition in definitions:
            existing = self._definitions.get(definition.type_id)
            if existing is not None and not existing.missing:
                # A package may never replace an application built-in silently.
                continue
            self.register(definition, package=True, replace=existing is not None)

    def get(self, type_id: str) -> NodeDefinition:
        return self._definitions[type_id]

    def get_optional(self, type_id: str) -> NodeDefinition | None:
        return self._definitions.get(type_id)

    def contains(self, type_id: str) -> bool:
        return type_id in self._definitions

    def all(self, *, include_hidden: bool = False) -> list[NodeDefinition]:
        definitions = self._definitions.values()
        if not include_hidden:
            definitions = (definition for definition in definitions if not definition.hidden)
        return sorted(definitions, key=lambda d: (d.category, d.name))

    def package_definitions(self) -> dict[str, NodeDefinition]:
        return {
            type_id: self._definitions[type_id]
            for type_id in self._package_type_ids
            if type_id in self._definitions
        }

    def categories(self) -> dict[str, list[NodeDefinition]]:
        grouped: dict[str, list[NodeDefinition]] = defaultdict(list)
        for definition in self.all():
            grouped[definition.category].append(definition)
        return dict(grouped)

    def search(self, text: str) -> list[NodeDefinition]:
        terms = [term.lower() for term in text.split() if term.strip()]
        if not terms:
            return [definition for definition in self.all() if not definition.missing]
        results: list[NodeDefinition] = []
        for definition in self._definitions.values():
            if definition.missing or definition.hidden:
                continue
            package = definition.package
            package_text = ""
            if package is not None:
                package_text = f"{package.package_id} {package.version} {package.library_name}"
            haystack = " ".join(
                (definition.name, definition.category, definition.type_id, package_text, *definition.tags)
            ).lower()
            if all(term in haystack for term in terms):
                results.append(definition)
        return sorted(results, key=lambda d: (d.category, d.name))

    def ensure_placeholder(
        self,
        type_id: str,
        snapshot: dict[str, Any] | None = None,
        inferred_inputs: Iterable[str] = (),
    ) -> NodeDefinition:
        existing = self._definitions.get(type_id)
        if existing is not None:
            return existing
        data = dict(snapshot or {})
        inputs = tuple(str(item) for item in data.get("inputs", ()) if str(item))
        if not inputs:
            inputs = tuple(dict.fromkeys(str(item) for item in inferred_inputs if str(item)))
        name = str(data.get("name", "Missing Node")) or "Missing Node"
        package_version = data.get("package_version")
        reason = f"Required node package is not installed: {type_id}"
        if package_version:
            reason += f" (project used version {package_version})"
        definition = NodeDefinition(
            type_id=type_id,
            name=f"Missing · {name}",
            category="Missing Nodes",
            evaluator=None,
            inputs=inputs,
            parameters=(),
            description=reason,
            accent="#a54652",
            tags=("missing", "package"),
            output_format=str(data.get("output_format", "rgba16f")),
            output_name=str(data.get("output_name", "Image")),
            terminal=bool(data.get("terminal", False)),
            missing=True,
            missing_reason=reason,
        )
        self._definitions[type_id] = definition
        return definition


def build_registry() -> NodeRegistry:
    from .generators import register_generator_nodes
    from .graph_utilities import register_graph_utility_nodes
    from .flood_fill import register_flood_fill_nodes
    from .distance import register_distance_nodes
    from .coordinates import register_coordinate_nodes
    from .input_nodes import register_input_nodes
    from .noise import register_noise_nodes
    from .noise_expansion import register_foundational_noise_nodes
    from .processing import register_processing_nodes
    from .photogrammetry import register_photogrammetry_nodes
    from .surface_analysis import register_surface_analysis_nodes
    from .normal_height import register_normal_height_nodes
    from .signals import register_signal_nodes
    from .simulation import register_simulation_nodes
    from .terrain import register_terrain_nodes
    from .geometry import register_geometry_nodes

    registry = NodeRegistry()
    register_input_nodes(registry)
    register_graph_utility_nodes(registry)
    register_generator_nodes(registry)
    register_flood_fill_nodes(registry)
    register_distance_nodes(registry)
    register_noise_nodes(registry)
    register_foundational_noise_nodes(registry)
    register_processing_nodes(registry)
    register_photogrammetry_nodes(registry)
    register_surface_analysis_nodes(registry)
    register_normal_height_nodes(registry)
    register_coordinate_nodes(registry)
    register_terrain_nodes(registry)
    register_geometry_nodes(registry)
    register_signal_nodes(registry)
    register_simulation_nodes(registry)
    registry.register(
        NodeDefinition(
            type_id="graph.reroute",
            name="Reroute",
            category="Graph",
            evaluator=None,
            inputs=("Input",),
            description="A zero-cost typed wire routing point.",
            accent="#667080",
            output_name="Output",
            input_kinds=(("Input", "image_any"),),
            output_kinds=(("Output", "image_any"),),
            type_policy="fixed",
            default_image_kind="grayscale",
            hidden=True,
        )
    )
    return registry
