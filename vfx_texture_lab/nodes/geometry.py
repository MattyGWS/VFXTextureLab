from __future__ import annotations

from .base import NodeDefinition, ParameterSpec
from .registry import NodeRegistry
from ..geometry import (
    evaluate_bend_geometry, evaluate_box_geometry, evaluate_clean_weld_geometry,
    evaluate_combine_geometry, evaluate_cylinder_geometry, evaluate_disc_ring_geometry,
    evaluate_decimate_geometry, evaluate_displace_geometry, evaluate_mesh_input_geometry, evaluate_normals_geometry, evaluate_plane_geometry,
    evaluate_ribbon_geometry, evaluate_subdivide_geometry, evaluate_transform_geometry,
    evaluate_twist_geometry, evaluate_unsubdivide_geometry, evaluate_uv_transform_geometry,
)
from ..uv_unwrap import evaluate_manual_uv_unwrap, UNWRAP_SIGNATURE_PARAMETERS
from ..mesh_remesh import evaluate_manual_remesh, REMESH_SIGNATURE_PARAMETERS
from ..mesh_components import evaluate_delete_small_parts
from ..geometry_bake import evaluate_manual_high_to_low_bake, BAKE_PARAMETER_NAMES



def register_geometry_nodes(registry: NodeRegistry) -> None:
    p = ParameterSpec
    registry.register(
        NodeDefinition(
            type_id="input.mesh",
            name="Mesh Input",
            category="Inputs & Outputs",
            evaluator=None,
            parameters=(
                p("path", "OBJ Mesh", "mesh_file", "", description="Wavefront OBJ mesh file. Polygon faces are triangulated during import.", group="Source", group_order=0),
                p("embedded", "Embed in project", "bool", False, description="Store the original OBJ bytes inside the .vfxgraph when saving.", group="Source", group_order=0),
                p("name", "Geometry name", "string", "", description="Optional output name. Leave blank to use the first OBJ object/group name or the file name.", group="Geometry", group_order=10),
            ),
            description=(
                "Import a Wavefront OBJ as Geometry. Position, UV and normal seams are preserved, polygon faces are triangulated, "
                "and smooth normals are generated when the source does not contain them. Linked and embedded sources are managed as graph resources."
            ),
            accent="#d7a449",
            tags=("mesh", "obj", "import", "file", "geometry", "input", "model"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_mesh_input_geometry,
        )
    )
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
            type_id="geometry.ribbon",
            name="Geometry Ribbon",
            category="Geometry/Generators",
            evaluator=None,
            parameters=(
                p("name", "Geometry name", "string", "Geometry Ribbon", group="Geometry", group_order=0),
                p("length", "Length", "float", 4.0, 0.001, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("width_start", "Width Start", "float", 1.0, 0.0, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("width_end", "Width End", "float", 1.0, 0.0, 10000.0, 0.05, group="Dimensions", group_order=10),
                p("length_segments", "Length Segments", "int", 16, 1, 2048, 1, group="Topology", group_order=20),
                p("width_segments", "Width Segments", "int", 1, 1, 256, 1, group="Topology", group_order=20),
                p(
                    "orientation", "Orientation", "enum", "Horizontal (XZ)",
                    options=("Horizontal (XZ)", "Vertical (XY)", "Vertical (YZ)"),
                    group="Geometry", group_order=0,
                ),
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
                "Generate a straight, optionally tapered VFX ribbon with U across its width and V along its length. "
                "Shared origin, XYZ rotation and integer UV tiling match the other Geometry generators."
            ),
            accent="#d2684a",
            tags=("mesh", "ribbon", "trail", "beam", "slash", "card", "uv", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_ribbon_geometry,
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
            type_id="geometry.bend",
            name="Geometry Bend",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Bent Geometry", group="Geometry", group_order=0),
                p("amount", "Bend Amount", "float", 90.0, -3600.0, 3600.0, 1.0, group="Bend", group_order=10, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("deformation_axis", "Deformation Axis", "enum", "Axis Z", options=("Axis X", "Axis Y", "Axis Z"), group="Bend", group_order=10),
                p("direction", "Bend Direction", "float", 0.0, -3600.0, 3600.0, 1.0, description="Rotate the bend plane around the deformation axis.", group="Bend", group_order=10, slider_minimum=-180.0, slider_maximum=180.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("pivot_mode", "Bend Around", "enum", "Current Origin", options=("Current Origin", "Bounds Centre"), group="Pivot", group_order=20),
                p("range_start", "Range Start", "float", 0.0, 0.0, 1.0, 0.01, group="Range", group_order=30),
                p("range_end", "Range End", "float", 1.0, 0.0, 1.0, 0.01, group="Range", group_order=30),
                p("clamp_outside", "Clamp Outside Range", "bool", True, description="Keep geometry beyond the selected section rigid and continue it along the end tangents.", group="Range", group_order=30),
            ),
            description=(
                "Bend any sufficiently segmented mesh into a circular arc. Direction rotates the bend plane, while the normalised range can deform only part of the mesh without breaking continuity."
            ),
            accent="#c45f44",
            tags=("mesh", "bend", "curve", "arc", "deform", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_bend_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.twist",
            name="Geometry Twist",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Twisted Geometry", group="Geometry", group_order=0),
                p("amount", "Twist Amount", "float", 180.0, -7200.0, 7200.0, 1.0, group="Twist", group_order=10, slider_minimum=-720.0, slider_maximum=720.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("axis", "Twist Axis", "enum", "Axis Z", options=("Axis X", "Axis Y", "Axis Z"), group="Twist", group_order=10),
                p("pivot_mode", "Twist Around", "enum", "Current Origin", options=("Current Origin", "Bounds Centre"), group="Pivot", group_order=20),
                p("range_start", "Range Start", "float", 0.0, 0.0, 1.0, 0.01, group="Range", group_order=30),
                p("range_end", "Range End", "float", 1.0, 0.0, 1.0, 0.01, group="Range", group_order=30),
                p("clamp_outside", "Clamp Outside Range", "bool", True, group="Range", group_order=30),
            ),
            description="Twist any mesh around its current origin or bounds centre, with a normalised deformation range and matching normal rotation.",
            accent="#c45f44",
            tags=("mesh", "twist", "spiral", "deform", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_twist_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.uv_transform",
            name="Geometry UV Transform",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "UV Transformed Geometry", group="Geometry", group_order=0),
                p("scale_u", "Scale U", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-8.0, slider_maximum=8.0, group="Scale", group_order=10),
                p("scale_v", "Scale V", "float", 1.0, -1000.0, 1000.0, 0.01, slider_minimum=-8.0, slider_maximum=8.0, group="Scale", group_order=10),
                p("offset_u", "Offset U", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-4.0, slider_maximum=4.0, group="Offset", group_order=20),
                p("offset_v", "Offset V", "float", 0.0, -1000.0, 1000.0, 0.01, slider_minimum=-4.0, slider_maximum=4.0, group="Offset", group_order=20),
                p("rotation", "Rotation", "float", 0.0, -3600.0, 3600.0, 1.0, group="Rotation", group_order=30, slider_minimum=-360.0, slider_maximum=360.0, editor="angle", unit="degrees", angle_wrap=False, fine_step=1.0, coarse_step=15.0),
                p("pivot_u", "Pivot U", "float", 0.5, -1000.0, 1000.0, 0.01, slider_minimum=0.0, slider_maximum=1.0, group="Pivot", group_order=40),
                p("pivot_v", "Pivot V", "float", 0.5, -1000.0, 1000.0, 0.01, slider_minimum=0.0, slider_maximum=1.0, group="Pivot", group_order=40),
                p("flip_u", "Flip U", "bool", False, group="Orientation", group_order=50),
                p("flip_v", "Flip V", "bool", False, group="Orientation", group_order=50),
                p("swap_uv", "Swap U / V", "bool", False, group="Orientation", group_order=50),
            ),
            description="Scale, offset, rotate, flip or swap mesh UV coordinates without changing positions, normals or topology.",
            accent="#c45f44",
            tags=("mesh", "uv", "transform", "tile", "offset", "rotate", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_uv_transform_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.uv_unwrap",
            name="Geometry UV Unwrap",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry", "Preview Texture"),
            input_kinds=(("Geometry", "geometry"), ("Preview Texture", "image_any")),
            parameters=(
                p("name", "Geometry name", "string", "UV Unwrapped Geometry", group="Geometry", group_order=0),
                p(
                    "mode", "Mode", "enum", "Automatic Charts",
                    options=("Automatic Charts", "Box Projection", "Planar Projection", "Cylindrical Projection", "Spherical Projection"),
                    description="Automatic Charts uses native xatlas charting and packing. Projection modes are deterministic fallbacks.",
                    group="Unwrap", group_order=10,
                ),
                p(
                    "chart_angle", "Chart Angle", "float", 66.0, 1.0, 180.0, 1.0,
                    description="Lower values prefer more seams and smaller charts; higher values allow charts to bend farther across the surface.",
                    slider_minimum=1.0, slider_maximum=180.0, unit="°", group="Charts", group_order=20,
                    visible_when=(("mode", ("Automatic Charts",)),),
                ),
                p(
                    "chart_iterations", "Chart Quality", "int", 2, 1, 8, 1,
                    description="Additional chart-growth refinement passes. Higher settings can improve difficult meshes but take longer.",
                    group="Charts", group_order=20, visible_when=(("mode", ("Automatic Charts",)),),
                ),
                p(
                    "preserve_existing_seams", "Preserve Existing Seams", "bool", True,
                    description="Keep imported UV and hard-normal vertex splits available to the automatic chart generator.",
                    group="Charts", group_order=20, visible_when=(("mode", ("Automatic Charts",)),),
                ),
                p(
                    "pack_resolution", "Pack Resolution", "int", 2048, 64, 16384, 64,
                    description="Atlas resolution used to calculate padding and packing density.",
                    group="Packing", group_order=30,
                ),
                p(
                    "island_padding", "Island Padding", "int", 8, 0, 256, 1,
                    description="Padding between packed UV islands in pixels at Pack Resolution.",
                    group="Packing", group_order=30,
                ),
                p(
                    "rotate_islands", "Rotate Islands", "bool", True,
                    description="Allow the packer to rotate charts to improve atlas usage.",
                    group="Packing", group_order=30, visible_when=(("mode", ("Automatic Charts",)),),
                ),
                p(
                    "quality_pack", "Best Packing", "bool", False,
                    description="Use xatlas brute-force chart placement. This is slower but can improve atlas coverage.",
                    group="Packing", group_order=30, visible_when=(("mode", ("Automatic Charts",)),),
                ),
            ),
            description=(
                "Create or replace mesh UVs. Expensive unwrap work is manual: adjust settings freely, then press Unwrap in the Inspector. "
                "The previous successful result remains available while settings are out of date. Preview Texture is presentation-only and appears beneath the UVs in 2D and on the mesh in 3D."
            ),
            accent="#c45f44",
            tags=("mesh", "uv", "unwrap", "atlas", "charts", "pack", "xatlas", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_manual_uv_unwrap,
            manual_action_label="Unwrap",
            manual_action_relevant_parameters=UNWRAP_SIGNATURE_PARAMETERS,
            presentation_only_inputs=("Preview Texture",),
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.bake_high_to_low",
            name="Geometry Bake High to Low",
            category="Geometry/Baking",
            evaluator=None,
            inputs=("High Geometry", "Low Geometry", "High Albedo", "Cage Geometry"),
            input_kinds=(("High Geometry", "geometry"), ("Low Geometry", "geometry"),
                         ("High Albedo", "color"), ("Cage Geometry", "geometry")),
            parameters=(
                p("name", "Bake name", "string", "High to Low Bake",
                  description="Name used by the baked Material, preview and future graph resources.",
                  group="Bake", group_order=0),
                p("preview_output", "2D Preview", "enum", "Albedo",
                  options=("Albedo", "Normal", "Height", "Ambient Occlusion", "Projection Mask"),
                  description="Choose the completed map shown in the 2D Preview. This never invalidates the bake.",
                  group="Bake", group_order=0),
                p("resolution", "Resolution", "int", 1024, 64, 4096, 64,
                  description="Square output resolution. 1024 is a practical one-click default; larger maps need more memory and bake time.",
                  group="Output", group_order=10),
                p("supersampling", "Supersampling", "enum", "1x", options=("1x", "2x", "4x"),
                  description="Bake at a larger internal resolution and downsample for cleaner edges.",
                  group="Output", group_order=10),
                p("padding", "Island Padding", "int", 16, 0, 256, 1,
                  description="Extend completed pixels beyond UV island borders to prevent mip-map seams.",
                  group="Output", group_order=10),
                p("bake_albedo", "Albedo", "bool", True,
                  description="Transfer High Albedo through the high-poly UVs. If no texture is connected this map is skipped without blocking the other maps.",
                  group="Maps", group_order=20),
                p("bake_normal", "Tangent Normal", "bool", True,
                  description="Bake high-poly surface normals directly into the low-poly tangent basis.",
                  group="Maps", group_order=20),
                p("bake_height", "Signed Height", "bool", True,
                  description="Bake signed projection distance, centred at 0.5 by default.",
                  group="Maps", group_order=20),
                p("bake_ambient_occlusion", "Ambient Occlusion", "bool", True,
                  description="Ray-traced high-poly ambient occlusion. This is normally the slowest enabled map.",
                  group="Maps", group_order=20),
                p("projection_mode", "Projection", "enum", "Bidirectional Normals",
                  options=("Bidirectional Normals", "Outward Only", "Inward Only", "Custom Cage"),
                  description="Bidirectional projection is the safest default for a decimated scan. Custom Cage requires matching low/cage topology.",
                  group="Projection", group_order=30),
                p("distance_mode", "Ray Distance", "enum", "Automatic", options=("Automatic", "Manual"),
                  description="Automatic derives a conservative range from the high/low bounds. Use Manual to avoid rays crossing nearby surfaces.",
                  group="Projection", group_order=30,
                  visible_when=(("projection_mode", ("Bidirectional Normals", "Outward Only", "Inward Only")),)),
                p("automatic_distance_percent", "Automatic Margin", "float", 5.0, 0.01, 100.0, 0.1,
                  description="Minimum front/back ray range as a percentage of the combined mesh bounds diagonal.",
                  slider_minimum=0.1, slider_maximum=25.0, unit="%",
                  group="Projection", group_order=30,
                  visible_when=(("distance_mode", ("Automatic",)),
                                ("projection_mode", ("Bidirectional Normals", "Outward Only", "Inward Only")))),
                p("front_distance", "Front Distance", "float", 0.1, 0.000001, 1000000.0, 0.001,
                  description="Maximum distance searched outside the low-poly surface.",
                  slider_minimum=0.001, slider_maximum=10.0,
                  group="Projection", group_order=30,
                  visible_when=(("distance_mode", ("Manual",)),
                                ("projection_mode", ("Bidirectional Normals", "Outward Only", "Inward Only")))),
                p("back_distance", "Back Distance", "float", 0.1, 0.000001, 1000000.0, 0.001,
                  description="Maximum distance searched inside the low-poly surface.",
                  slider_minimum=0.001, slider_maximum=10.0,
                  group="Projection", group_order=30,
                  visible_when=(("distance_mode", ("Manual",)),
                                ("projection_mode", ("Bidirectional Normals", "Outward Only", "Inward Only")))),
                p("ray_bias_percent", "Ray Bias", "float", 0.01, 0.0, 1.0, 0.001,
                  description="Small origin offset as a percentage of mesh bounds, preventing immediate self-hits.",
                  slider_minimum=0.0, slider_maximum=0.25, unit="%",
                  group="Projection", group_order=30),
                p("albedo_filter", "Albedo Filtering", "enum", "Bilinear", options=("Bilinear", "Nearest"),
                  group="Albedo", group_order=40, visible_when=(("bake_albedo", (True,)),)),
                p("preserve_alpha", "Preserve Alpha", "bool", True,
                  group="Albedo", group_order=40, visible_when=(("bake_albedo", (True,)),)),
                p("normal_y", "Normal Y", "enum", "OpenGL (+Y)", options=("OpenGL (+Y)", "DirectX (-Y)"),
                  description="Choose the target renderer convention without rebaking projection hits in a future incremental baker.",
                  group="Normal", group_order=50, visible_when=(("bake_normal", (True,)),)),
                p("height_range", "Height Range", "enum", "Automatic Symmetric",
                  options=("Automatic Symmetric", "Manual"),
                  description="Automatic Symmetric keeps the unchanged low surface at 0.5 and fits the largest inward/outward detail.",
                  group="Height", group_order=60, visible_when=(("bake_height", (True,)),)),
                p("height_manual_min", "Minimum Distance", "float", -0.1, -1000000.0, 1000000.0, 0.001,
                  group="Height", group_order=60,
                  visible_when=(("bake_height", (True,)), ("height_range", ("Manual",)))),
                p("height_manual_max", "Maximum Distance", "float", 0.1, -1000000.0, 1000000.0, 0.001,
                  group="Height", group_order=60,
                  visible_when=(("bake_height", (True,)), ("height_range", ("Manual",)))),
                p("height_invert", "Invert", "bool", False, group="Height", group_order=60,
                  visible_when=(("bake_height", (True,)),)),
                p("ao_quality", "Quality", "enum", "Draft", options=("Draft", "Medium", "High", "Custom"),
                  description="Draft uses 16 rays per projected texel and is the sane one-click default. Medium and High are intended for final bakes.",
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)),)),
                p("ao_samples", "Samples", "int", 64, 1, 2048, 1,
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)), ("ao_quality", ("Custom",)))),
                p("ao_distance_mode", "Occlusion Distance", "enum", "Automatic", options=("Automatic", "Manual"),
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)),)),
                p("ao_distance_percent", "Automatic Distance", "float", 10.0, 0.01, 100.0, 0.1,
                  slider_minimum=0.1, slider_maximum=50.0, unit="%",
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)), ("ao_distance_mode", ("Automatic",)))),
                p("ao_distance", "Maximum Distance", "float", 0.25, 0.000001, 1000000.0, 0.001,
                  slider_minimum=0.001, slider_maximum=10.0,
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)), ("ao_distance_mode", ("Manual",)))),
                p("ao_intensity", "Intensity", "float", 1.0, 0.0, 4.0, 0.05,
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)),)),
                p("ao_contrast", "Contrast", "float", 1.0, 0.1, 4.0, 0.05,
                  group="Ambient Occlusion", group_order=70,
                  visible_when=(("bake_ambient_occlusion", (True,)),)),
            ),
            description=(
                "Project a textured high-poly mesh onto an unwrapped low-poly mesh and publish a reusable Baked Material plus individual maps. "
                "Configure freely, then press Bake in the Inspector; previous successful maps remain available until the next bake completes. "
                "The versioned bake-result container is designed for additional Substance-style outputs in future releases."
            ),
            accent="#c45f44",
            tags=("mesh", "bake", "high poly", "low poly", "photogrammetry", "normal", "height", "ao", "albedo", "geometry"),
            output_name="Albedo",
            outputs=("Baked Material", "Albedo", "Normal", "Height", "Ambient Occlusion", "Projection Mask", "Low Geometry"),
            output_kinds=(("Baked Material", "material"), ("Albedo", "color"), ("Normal", "vector"),
                          ("Height", "grayscale"), ("Ambient Occlusion", "grayscale"),
                          ("Projection Mask", "grayscale"), ("Low Geometry", "geometry")),
            geometry_evaluator=evaluate_manual_high_to_low_bake,
            manual_action_label="Bake",
            manual_action_relevant_parameters=BAKE_PARAMETER_NAMES,
            default_image_kind="color",
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.remesh",
            name="Geometry Remesh",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Remeshed Geometry", group="Geometry", group_order=0),
                p(
                    "voxel_size_mode", "Voxel Size Mode", "enum", "Relative to Bounds",
                    options=("Relative to Bounds", "Absolute Units"),
                    description="Relative mode scales consistently across imported meshes with arbitrary units; Absolute Units matches Blender-style object-space voxel sizing.",
                    group="Resolution", group_order=10,
                ),
                p(
                    "relative_voxel_size", "Voxel Size", "float", 1.0, 0.05, 50.0, 0.05,
                    description="Voxel edge length as a percentage of the mesh's longest bounds dimension. Lower values preserve more detail and use substantially more memory.",
                    slider_minimum=0.1, slider_maximum=10.0, fine_step=0.05, coarse_step=0.5, unit="%",
                    group="Resolution", group_order=10, visible_when=(("voxel_size_mode", ("Relative to Bounds",)),),
                ),
                p(
                    "absolute_voxel_size", "Voxel Size", "float", 0.05, 0.000001, 100000.0, 0.001,
                    description="Object-space voxel edge length. Lower values preserve more detail and use substantially more memory.",
                    slider_minimum=0.001, slider_maximum=1.0, fine_step=0.001, coarse_step=0.05,
                    group="Resolution", group_order=10, visible_when=(("voxel_size_mode", ("Absolute Units",)),),
                ),
                p(
                    "fill_interior", "Fill Interior", "bool", True,
                    description="Fill enclosed voxel regions before extracting the new surface. Recommended for scan cleanup and watertight assets.",
                    group="Surface", group_order=20,
                ),
                p(
                    "surface_smoothing", "Surface Smoothness", "float", 0.75, 0.0, 3.0, 0.05,
                    description="Smooth the voxel field before extracting the surface. Higher values reduce voxel stepping but can soften fine detail.",
                    slider_minimum=0.0, slider_maximum=3.0, fine_step=0.05, coarse_step=0.25,
                    group="Surface", group_order=20,
                ),
                p(
                    "preserve_volume", "Preserve Volume", "bool", True,
                    description="Scale the rebuilt surface to preserve the closed source volume, or the filled voxel volume for open inputs.",
                    group="Surface", group_order=20,
                ),
                p(
                    "adaptivity", "Adaptivity", "float", 0.0, 0.0, 1.0, 0.01,
                    description="Reduce triangles in flatter areas after remeshing. Zero keeps the most uniform topology; one applies the strongest shape-aware reduction.",
                    slider_minimum=0.0, slider_maximum=1.0, fine_step=0.01, coarse_step=0.1,
                    group="Topology", group_order=30,
                ),
            ),
            description=(
                "Rebuild geometry through a uniform voxel volume, similar to Blender's Voxel Remesh workflow. "
                "The operation is manual and transactional: adjust settings, then press Remesh in the Inspector. "
                "New topology receives smooth normals and no UVs, ready for Geometry Decimate and Geometry UV Unwrap."
            ),
            accent="#c45f44",
            tags=("mesh", "remesh", "voxel", "scan", "photogrammetry", "uniform", "manifold", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_manual_remesh,
            manual_action_label="Remesh",
            manual_action_relevant_parameters=REMESH_SIGNATURE_PARAMETERS,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.delete_small_parts",
            name="Geometry Delete Small Parts",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Largest Mesh Part", group="Geometry", group_order=0),
                p(
                    "mode", "Keep", "enum", "Keep Largest Only",
                    options=("Keep Largest Only", "Keep Parts Above Relative Size"),
                    description="Keep only the dominant connected mesh part, or retain every part above a percentage of the largest one.",
                    group="Components", group_order=10,
                ),
                p(
                    "measure", "Size Measure", "enum", "Vertex Count",
                    options=("Vertex Count", "Triangle Count", "Surface Area"),
                    description="How disconnected parts are ranked. Vertex Count matches the common scan-cleanup workflow of selecting the largest object by geometry density.",
                    group="Components", group_order=10,
                ),
                p(
                    "minimum_relative_size", "Minimum Relative Size", "float", 2.0, 0.0, 100.0, 0.1,
                    description="Keep parts at least this large relative to the largest connected part.",
                    slider_minimum=0.0, slider_maximum=100.0, fine_step=0.1, coarse_step=5.0, unit="%",
                    group="Components", group_order=10, visible_when=(("mode", ("Keep Parts Above Relative Size",)),),
                ),
            ),
            description=(
                "Detect disconnected geometric components across UV and normal seams, then remove scan fragments and floating islands automatically. "
                "Keep Largest Only reproduces the usual select-largest, invert-selection, delete workflow in one node."
            ),
            accent="#c45f44",
            tags=("mesh", "delete", "small parts", "components", "islands", "scan", "cleanup", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_delete_small_parts,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.clean_weld",
            name="Geometry Clean / Weld",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Cleaned Geometry", group="Geometry", group_order=0),
                p("remove_degenerate", "Remove Degenerate Triangles", "bool", True, group="Cleanup", group_order=10),
                p("remove_unused", "Remove Unused Vertices", "bool", True, group="Cleanup", group_order=10),
                p("merge_vertices", "Merge Compatible Vertices", "bool", True, group="Weld", group_order=20),
                p("weld_distance", "Weld Distance", "float", 0.0, 0.0, 1000.0, 0.0001, description="Zero merges exact duplicates. Positive values use a spatial tolerance.", slider_minimum=0.0, slider_maximum=1.0, fine_step=0.0001, coarse_step=0.01, group="Weld", group_order=20, visible_when=(("merge_vertices", (True,)),)),
                p("preserve_uv_seams", "Preserve UV Seams", "bool", True, group="Preservation", group_order=30, visible_when=(("merge_vertices", (True,)),)),
                p("preserve_hard_edges", "Preserve Hard Normal Edges", "bool", True, group="Preservation", group_order=30, visible_when=(("merge_vertices", (True,)),)),
            ),
            description=(
                "Remove unused vertices and degenerate triangles, then merge compatible duplicates or weld within a tolerance. UV seams and hard normal boundaries are preserved by default."
            ),
            accent="#c45f44",
            tags=("mesh", "clean", "weld", "merge", "duplicate", "degenerate", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_clean_weld_geometry,
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
            type_id="geometry.decimate",
            name="Geometry Decimate",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Decimated Geometry", group="Geometry", group_order=0),
                p(
                    "percentage", "Percentage", "float", 100.0, 1.0, 100.0, 1.0,
                    description="Target percentage of input triangles to retain. 100% leaves the mesh unchanged; 1% keeps at least one triangle where topology permits.",
                    slider_minimum=1.0, slider_maximum=100.0, fine_step=0.1, coarse_step=5.0,
                    unit="%", group="Reduction", group_order=10,
                ),
            ),
            description=(
                "Reduce a mesh toward a target triangle percentage with native quadric-error simplification. "
                "UV and hard-normal copies are welded into one geometric topology during reduction, then restored at exactly coincident positions so attribute seams cannot tear open the mesh."
            ),
            accent="#c45f44",
            tags=("mesh", "decimate", "simplify", "reduce", "lod", "polygon", "triangle", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_decimate_geometry,
        )
    )
    registry.register(
        NodeDefinition(
            type_id="geometry.unsubdivide",
            name="Geometry Un-Subdivide",
            category="Geometry/Operations",
            evaluator=None,
            inputs=("Geometry",),
            input_kinds=(("Geometry", "geometry"),),
            parameters=(
                p("name", "Geometry name", "string", "Un-Subdivided Geometry", group="Geometry", group_order=0),
                p(
                    "iterations", "Iterations", "int", 1, 1, 6, 1,
                    description="Number of reversible subdivision or structured UV-grid passes to remove. Extra iterations stop automatically when no simpler compatible level remains.",
                    group="Topology", group_order=10,
                ),
            ),
            description=(
                "Reverse Geometry Subdivide topology and reduce regular UV-grid meshes such as Geometry Plane, Box and Ribbon. "
                "Arbitrary imported or scanned triangle meshes do not contain an earlier control mesh; use Geometry Decimate for those."
            ),
            accent="#c45f44",
            tags=("mesh", "unsubdivide", "un-subdivide", "reverse", "subdivision", "reduce", "topology", "geometry"),
            output_name="Geometry",
            output_kinds=(("Geometry", "geometry"),),
            geometry_evaluator=evaluate_unsubdivide_geometry,
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
