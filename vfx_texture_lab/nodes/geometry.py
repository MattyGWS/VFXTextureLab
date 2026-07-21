from __future__ import annotations

from .base import NodeDefinition, ParameterSpec
from .registry import NodeRegistry
from ..geometry import (
    evaluate_box_geometry, evaluate_combine_geometry, evaluate_cylinder_geometry,
    evaluate_disc_ring_geometry, evaluate_displace_geometry, evaluate_normals_geometry,
    evaluate_plane_geometry, evaluate_subdivide_geometry, evaluate_transform_geometry,
)


def register_geometry_nodes(registry: NodeRegistry) -> None:
    p = ParameterSpec
    registry.register(
        NodeDefinition(
            type_id="geometry.plane",
            name="Geometry Plane",
            category="Geometry/Generators",
            evaluator=None,
            parameters=(
                p("name", "Geometry name", "string", "Geometry Plane", group="Geometry", group_order=0),
                p("width", "Width", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("height", "Height", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("subdivisions_x", "Subdivisions X", "int", 16, 1, 512, 1, group="Topology", group_order=20),
                p("subdivisions_y", "Subdivisions Y", "int", 16, 1, 512, 1, group="Topology", group_order=20),
                p(
                    "orientation", "Orientation", "enum", "Horizontal (XZ)",
                    options=("Horizontal (XZ)", "Vertical (XY)", "Vertical (YZ)"),
                    group="Geometry", group_order=0,
                ),
                p("origin_x", "Origin X", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_y", "Origin Y", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_z", "Origin Z", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("rotation_x", "Rotation X", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the X axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_y", "Rotation Y", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Y axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_z", "Rotation Z", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Z axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uv_tiles_u", "UV Tiles U", "int", 1, 1, 64, 1, group="UV", group_order=40),
                p("uv_tiles_v", "UV Tiles V", "int", 1, 1, 64, 1, group="UV", group_order=40),
            ),
            description=(
                "Generate a centred, indexed triangle plane with consistent normals and UVs. "
                "Origin controls reposition the export pivot, XYZ rotation turns the mesh around that pivot, and integer UV tiles keep repeated textures seamless."
            ),
            accent="#d2684a",
            tags=("mesh", "plane", "card", "uv", "procedural", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_plane_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.box",
            name="Geometry Box",
            category="Geometry/Generators",
            evaluator=None,
            parameters=(
                p("name", "Geometry name", "string", "Geometry Box", group="Geometry", group_order=0),
                p("width", "Width", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("height", "Height", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("depth", "Depth", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("subdivisions_x", "Subdivisions X", "int", 1, 1, 256, 1, group="Topology", group_order=20),
                p("subdivisions_y", "Subdivisions Y", "int", 1, 1, 256, 1, group="Topology", group_order=20),
                p("subdivisions_z", "Subdivisions Z", "int", 1, 1, 256, 1, group="Topology", group_order=20),
                p("origin_x", "Origin X", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_y", "Origin Y", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_z", "Origin Z", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("rotation_x", "Rotation X", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the X axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_y", "Rotation Y", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Y axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_z", "Rotation Z", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Z axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uv_tiles_u", "UV Tiles U", "int", 1, 1, 64, 1, group="UV", group_order=40),
                p("uv_tiles_v", "UV Tiles V", "int", 1, 1, 64, 1, group="UV", group_order=40),
            ),
            description=(
                "Generate a hard-edged box with separate UVs on every face. "
                "Origin controls reposition the export pivot, XYZ rotation turns the box around it, and UV tile counts repeat seamlessly across each face."
            ),
            accent="#d2684a",
            tags=("mesh", "box", "cube", "uv", "procedural", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_box_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.cylinder",
            name="Geometry Cylinder",
            category="Geometry/Generators",
            evaluator=None,
            parameters=(
                p("name", "Geometry name", "string", "Geometry Cylinder", group="Geometry", group_order=0),
                p("radius", "Radius", "float", 1.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("height", "Height", "float", 2.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("top_radius_offset", "Top Radius Offset", "float", 0.0, -10000.0, 10000.0, 0.05, description="Added to Radius. A final radius of zero forms a cone tip.", slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.25, group="Dimensions", group_order=10),
                p("bottom_radius_offset", "Bottom Radius Offset", "float", 0.0, -10000.0, 10000.0, 0.05, description="Added to Radius. A final radius of zero forms a cone tip.", slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.25, group="Dimensions", group_order=10),
                p("radial_segments", "Radial segments", "int", 32, 3, 512, 1, group="Topology", group_order=20),
                p("height_segments", "Height segments", "int", 1, 1, 512, 1, group="Topology", group_order=20),
                p("caps", "Generate caps", "bool", True, group="Topology", group_order=20),
                p("cap_segments", "Cap segments", "int", 1, 1, 128, 1, group="Topology", group_order=20),
                p("smooth_sides", "Smooth sides", "bool", True, group="Shading", group_order=25),
                p(
                    "orientation",
                    "Orientation",
                    "enum",
                    "Axis Y",
                    options=("Axis Y", "Axis X", "Axis Z"),
                    group="Geometry",
                    group_order=0,
                ),
                p("origin_x", "Origin X", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_y", "Origin Y", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_z", "Origin Z", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("rotation_x", "Rotation X", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the X axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_y", "Rotation Y", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Y axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_z", "Rotation Z", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate around the selected origin on the Z axis. The slider covers one full turn; typed values may accumulate additional turns.", group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uv_tiles_u", "UV Tiles U", "int", 1, 1, 64, 1, group="UV", group_order=40),
                p("uv_tiles_v", "UV Tiles V", "int", 1, 1, 64, 1, group="UV", group_order=40),
            ),
            description=(
                "Generate a cylinder, cone or frustum with independent additive top/bottom radius offsets, pivot-based XYZ rotation, a clean UV seam, optional caps and smooth or faceted side normals."
            ),
            accent="#d2684a",
            tags=("mesh", "cylinder", "tube", "cone", "frustum", "taper", "uv", "procedural", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_cylinder_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.disc_ring",
            name="Geometry Disc / Ring",
            category="Geometry/Generators",
            evaluator=None,
            parameters=(
                p("name", "Geometry name", "string", "Geometry Disc / Ring", group="Geometry", group_order=0),
                p("outer_radius", "Outer Radius", "float", 1.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("inner_radius", "Inner Radius", "float", 0.0, 0.0, 10000.0, 0.05, description="Zero creates a disc; positive values create a ring and clamp below Outer Radius.", group="Dimensions", group_order=10),
                p("radial_segments", "Radial Segments", "int", 64, 3, 1024, 1, group="Topology", group_order=20),
                p("ring_segments", "Ring Segments", "int", 1, 1, 512, 1, group="Topology", group_order=20),
                p("arc_start", "Arc Start", "float", 0.0, -3600.0, 3600.0, 1.0, group="Arc", group_order=25, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("arc_spread", "Arc Spread", "float", 360.0, 0.001, 360.0, 1.0, group="Arc", group_order=25, slider_minimum=0.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uv_mode", "UV Mode", "enum", "Planar", options=("Planar", "Radial Strip"), group="UV", group_order=40),
                p("orientation", "Orientation", "enum", "Axis Y", options=("Axis Y", "Axis X", "Axis Z"), group="Geometry", group_order=0),
                p("origin_x", "Origin X", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_y", "Origin Y", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("origin_z", "Origin Z", "float", 0.0, -1.0, 1.0, 0.05, group="Origin", group_order=30),
                p("rotation_x", "Rotation X", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_y", "Rotation Y", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_z", "Rotation Z", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=35, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uv_tiles_u", "UV Tiles U", "int", 1, 1, 64, 1, group="UV", group_order=40),
                p("uv_tiles_v", "UV Tiles V", "int", 1, 1, 64, 1, group="UV", group_order=40),
            ),
            description=(
                "Generate a complete or partial disc/ring for shockwaves, portals and radial VFX. "
                "Planar UVs suit projected textures; Radial Strip UVs run around and across the ring."
            ),
            accent="#d2684a",
            tags=("mesh", "disc", "ring", "annulus", "arc", "shockwave", "portal", "uv", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_disc_ring_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.transform",
            name="Geometry Transform",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Transformed Geometry", group="Geometry", group_order=0),
                p("pivot_mode", "Transform Around", "enum", "Current Origin", options=("Current Origin", "Bounds Centre"), group="Transform", group_order=0),
                p("translate_x", "Translate X", "float", 0.0, -10000.0, 10000.0, 0.05, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=1.0, group="Translation", group_order=10),
                p("translate_y", "Translate Y", "float", 0.0, -10000.0, 10000.0, 0.05, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=1.0, group="Translation", group_order=10),
                p("translate_z", "Translate Z", "float", 0.0, -10000.0, 10000.0, 0.05, slider_minimum=-10.0, slider_maximum=10.0, fine_step=0.01, coarse_step=1.0, group="Translation", group_order=10),
                p("rotation_x", "Rotation X", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=20, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_y", "Rotation Y", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=20, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("rotation_z", "Rotation Z", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=20, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("uniform_scale", "Uniform Scale", "float", 1.0, 0.001, 1000.0, 0.01, slider_minimum=0.01, slider_maximum=10.0, fine_step=0.01, coarse_step=0.25, group="Scale", group_order=30),
                p("scale_x", "Scale X", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-4.0, slider_maximum=4.0, fine_step=0.01, coarse_step=0.25, group="Scale", group_order=30),
                p("scale_y", "Scale Y", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-4.0, slider_maximum=4.0, fine_step=0.01, coarse_step=0.25, group="Scale", group_order=30),
                p("scale_z", "Scale Z", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-4.0, slider_maximum=4.0, fine_step=0.01, coarse_step=0.25, group="Scale", group_order=30),
            ),
            description=(
                "Translate, rotate and scale any geometry without changing its export origin. "
                "Transforms can operate around the current origin or the mesh bounds centre; mirrored scales correct triangle winding automatically."
            ),
            accent="#c45f44",
            tags=("mesh", "transform", "translate", "rotate", "scale", "mirror", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_transform_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.subdivide",
            name="Geometry Subdivide",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Subdivided Geometry", group="Geometry", group_order=0),
                p("levels", "Subdivision Levels", "int", 1, 0, 6, 1, group="Topology", group_order=10),
                p("smooth_surface", "Smooth Surface", "bool", False, description="Relax the subdivided positions and rebuild smooth normals. Leave disabled to add topology without changing the authored shape.", group="Surface", group_order=20),
            ),
            description=(
                "Split every triangle into four per level. Shape-preserving subdivision is ideal before Geometry Displace; Smooth Surface progressively relaxes closed meshes."
            ),
            accent="#c45f44",
            tags=("mesh", "subdivide", "tessellate", "smooth", "topology", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_subdivide_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.normals",
            name="Geometry Normals",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Geometry Normals", group="Geometry", group_order=0),
                p("mode", "Normal Mode", "enum", "Smooth", options=("Smooth", "Smoothing Angle", "Flat"), group="Normals", group_order=10),
                p("smoothing_angle", "Smoothing Angle", "float", 60.0, 0.0, 180.0, 1.0, group="Normals", group_order=10, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0, visible_when=(("mode", ("Smoothing Angle",)),)),
                p("flip_normals", "Flip Normals", "bool", False, group="Orientation", group_order=20),
                p("reverse_winding", "Reverse Triangle Winding", "bool", False, group="Orientation", group_order=20),
            ),
            description=(
                "Explicitly rebuild smooth, angle-limited or flat mesh normals. Angle and Flat modes split vertices where one position needs several shading normals; winding and normal direction can be corrected independently."
            ),
            accent="#c45f44",
            tags=("mesh", "normal", "normals", "smooth", "flat", "winding", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_normals_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.combine",
            name="Geometry Combine",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Top Geometry", "Bottom Geometry"),
            input_kinds=(("Top Geometry", "geometry"), ("Bottom Geometry", "geometry")),
            parameters=(
                p("name", "Geometry name", "string", "Combined Geometry", group="Geometry", group_order=0),
            ),
            description=(
                "Combine the Top Geometry into the Bottom Geometry without moving either mesh. "
                "The output uses the Bottom Geometry origin as the shared export pivot and exports as one mesh; vertices are joined without welding or boolean operations."
            ),
            accent="#c45f44",
            tags=("mesh", "combine", "merge", "join", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_combine_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.displace",
            name="Geometry Displace",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry", "Height"),
            input_kinds=(("Geometry", "geometry"), ("Height", "grayscale")),
            parameters=(
                p("name", "Geometry name", "string", "Displaced Geometry", group="Geometry", group_order=0),
                p(
                    "amount", "Multiplier", "float", 1.0, -1000.0, 1000.0, 0.05,
                    description="Height 0 produces no movement; Height 1 moves by this distance along the vertex normal.",
                    slider_minimum=-2.0, slider_maximum=2.0, fine_step=0.01, coarse_step=0.25,
                    group="Displacement", group_order=10,
                ),
            ),
            description=(
                "Sample the grayscale Height input through the mesh UVs and move every vertex along its stored normal. "
                "Positive and negative multipliers displace in opposite directions while preserving the incoming mesh normals; use Geometry Normals when explicit recalculation is desired."
            ),
            accent="#c45f44",
            tags=("mesh", "displace", "heightmap", "height", "deform", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_displace_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="output.geometry",
            name="Geometry Output",
            category="Inputs & Outputs",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Output name", "string", "Geometry", group="Output", group_order=0),
                p("export_filename", "File name", "string", "{name}", description="Supports the {name} token.", group="Output", group_order=0),
                p("export_format", "Mesh format", "enum", "Wavefront OBJ", options=("Wavefront OBJ",), group="Encoding", group_order=10),
                p("include_uvs", "Include UV coordinates", "bool", True, group="Encoding", group_order=10),
                p("include_normals", "Include vertex normals", "bool", True, group="Encoding", group_order=10),
                p("flip_v", "Flip UV V coordinate", "bool", False, group="Encoding", group_order=10),
            ),
            description="Export connected procedural geometry as an indexed UV-mapped Wavefront OBJ mesh.",
            accent="#bc5b3f",
            tags=("mesh", "export", "obj", "geometry", "output"),
            terminal=True,
        )
    )
