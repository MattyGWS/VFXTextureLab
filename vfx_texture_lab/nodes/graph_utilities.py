from __future__ import annotations

from .base import NodeDefinition, ParameterSpec
from .registry import NodeRegistry
from ..graph_assets import (
    GRAPH_INPUT_TYPE, GRAPH_OUTPUT_TYPE, GRAPH_INSTANCE_TYPE, graph_input_image,
)


def register_graph_utility_nodes(registry: NodeRegistry) -> None:
    p = ParameterSpec
    registry.register(
        NodeDefinition(
            type_id=GRAPH_INPUT_TYPE,
            name="Graph Input",
            category="Graph Assets",
            evaluator=graph_input_image,
            parameters=(
                p("name", "Name", "string", "Input", description="Public socket name on a nested Graph Instance.", group="Interface", group_order=10),
                p(
                    "data_type", "Data Type", "enum", "Greyscale",
                    options=("Greyscale", "Colour", "Vector / Normal", "Signal", "Material", "Geometry"),
                    description="The typed value accepted by this graph asset input. Geometry inputs have no implicit mesh default and should normally be required.",
                    group="Interface", group_order=10,
                ),
                p("description", "Description", "string", "", description="Tooltip shown to users of this graph asset.", group="Interface", group_order=10),
                p("required", "Required", "bool", False, description="Warn when an instance leaves this socket unconnected.", group="Interface", group_order=10),
                p("order", "Interface Order", "int", 100, 0, 9999, 1, group="Interface", group_order=10),
                p("default_value", "Default Value", "float", 0.0, -1000000.0, 1000000.0, 0.01, group="Default", group_order=20, visible_when=(("data_type", ("Greyscale", "Signal")),)),
                p("default_color", "Default Colour", "color", "#808080", group="Default", group_order=20, visible_when=(("data_type", ("Colour",)),)),
                p("default_x", "Default X", "float", 0.5, -1000000.0, 1000000.0, 0.01, group="Default", group_order=20, visible_when=(("data_type", ("Vector / Normal",)),)),
                p("default_y", "Default Y", "float", 0.5, -1000000.0, 1000000.0, 0.01, group="Default", group_order=20, visible_when=(("data_type", ("Vector / Normal",)),)),
                p("default_z", "Default Z", "float", 1.0, -1000000.0, 1000000.0, 0.01, group="Default", group_order=20, visible_when=(("data_type", ("Vector / Normal",)),)),
            ),
            description="Declare one typed public input socket for a reusable .vfxgraph asset.",
            accent="#805cc6",
            tags=("subgraph", "asset", "interface", "input"),
            output_name="Value",
            output_kinds=(("Value", "any"),),
            type_policy="graph_input",
        )
    )
    registry.register(
        NodeDefinition(
            type_id=GRAPH_OUTPUT_TYPE,
            name="Graph Output",
            category="Graph Assets",
            evaluator=None,
            inputs=("Value",),
            parameters=(
                p("name", "Name", "string", "Output", description="Public output socket name on a nested Graph Instance.", group="Interface", group_order=10),
                p("description", "Description", "string", "", description="Tooltip shown to users of this graph asset.", group="Interface", group_order=10),
                p("order", "Interface Order", "int", 100, 0, 9999, 1, group="Interface", group_order=10),
                p("primary_preview", "Primary Preview Output", "bool", False, description="Prefer this output when the Graph Instance is double-clicked.", group="Interface", group_order=10),
            ),
            description="Publish one graph result as a typed output on a reusable .vfxgraph asset. The input type is inherited automatically.",
            accent="#805cc6",
            tags=("subgraph", "asset", "interface", "output"),
            input_kinds=(("Value", "any"),),
            terminal=True,
            type_policy="graph_output",
        )
    )
    registry.register(
        NodeDefinition(
            type_id=GRAPH_INSTANCE_TYPE,
            name="Graph Instance",
            category="Graph Assets",
            evaluator=None,
            description="A linked or embedded reusable .vfxgraph asset.",
            accent="#8c61d8",
            hidden=True,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="graph.send",
            name="Send",
            category="Graph Utilities",
            evaluator=None,
            inputs=("Input",),
            parameters=(
                p(
                    "channel_name",
                    "Channel name",
                    "string",
                    "Channel",
                    description="A unique project-wide wireless channel name.",
                ),
            ),
            description="Publish one typed graph value to any number of Receive nodes without drawing a long wire.",
            accent="#7b65c8",
            tags=("wireless", "portal", "send", "broadcast", "graph"),
            input_kinds=(("Input", "image_any"),),
            terminal=True,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="graph.receive",
            name="Receive",
            category="Graph Utilities",
            evaluator=None,
            # The input exists only in the evaluator snapshot. PortalNodeItem
            # hides it from the graph, so the user sees one wireless output.
            inputs=("Input",),
            parameters=(
                p(
                    "sender_uid",
                    "Channel",
                    "portal_channel",
                    "",
                    description="Choose an available Send channel.",
                ),
            ),
            description="Receive the typed value published by a Send node with the selected channel.",
            accent="#6553b2",
            tags=("wireless", "portal", "receive", "listen", "graph"),
            output_name="Output",
            input_kinds=(("Input", "image_any"),),
            output_kinds=(("Output", "image_any"),),
            type_policy="fixed",
            default_image_kind="grayscale",
        )
    )
