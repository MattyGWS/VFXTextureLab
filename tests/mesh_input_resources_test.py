from __future__ import annotations

import base64
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.geometry import (
    evaluate_mesh_input_geometry,
    load_obj_geometry,
    refresh_mesh_metadata,
)
from vfx_texture_lab.graph_assets import asset_graph_data
from vfx_texture_lab.graph_resources import GraphResource, GraphResourceLibrary, migrate_project_resources
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.portable_graph import (
    build_self_contained_graph,
    recovery_summary,
    validate_self_contained_graph,
)
from vfx_texture_lab.vfx_package import create_vfxpackage, inspect_vfxpackage


QUAD_OBJ = """\
# One n-gon, deliberately without authored normals.
o Imported Quad
v -1 0 -1
v  1 0 -1
v  1 0  1
v -1 0  1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
f 1/1 2/2 3/3 4/4 # inline OBJ comments are legal
"""

NEGATIVE_INDEX_OBJ = """\
o Negative Indices
v 0 0 0
v 1 0 0
v 0 1 0
vt 0 0
vt 1 0
vt 0 1
vn 0 0 2
f -3/-3/-1 -2/-2/-1 -1/-1/-1
"""

UV_SEAM_OBJ = """\
o Seam Test
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt 0.25 0
vt 0.75 1
f 1/1 2/2 3/3
f 1/5 3/6 4/4
"""


def _graph(nodes: list[dict]) -> dict:
    return {
        "format": "vfx-texture-lab-graph",
        "version": 18,
        "document": {},
        "graph_asset": {
            "asset_id": "mesh-resource-test",
            "name": "Mesh Resource Test",
            "description": "Regression fixture",
            "category": "Tests",
            "tags": ["mesh", "resources"],
            "author": "Tests",
            "version": "1.0.0",
            "created_with": "0.51.0",
        },
        "nodes": nodes,
        "connections": [],
        "groups": [],
    }


def assert_mesh_node_contract() -> None:
    registry = build_registry()
    definition = registry.get("input.mesh")
    assert definition.name == "Mesh Input"
    assert definition.category == "Inputs & Outputs"
    assert definition.output_kind(definition.output_name) == "geometry"
    assert definition.geometry_evaluator is evaluate_mesh_input_geometry
    path_parameter = next(item for item in definition.parameters if item.name == "path")
    embedded_parameter = next(item for item in definition.parameters if item.name == "embedded")
    assert path_parameter.kind == "mesh_file"
    assert embedded_parameter.kind == "bool"


def assert_obj_import(root: Path) -> Path:
    quad_path = root / "quad.obj"
    quad_path.write_text(QUAD_OBJ, encoding="utf-8")

    geometry, metadata = load_obj_geometry({"path": str(quad_path)})
    assert geometry.name == "Imported Quad"
    assert geometry.vertex_count == 4
    assert geometry.triangle_count == 2
    expected_metadata = {
        "vertex_count": 4,
        "triangle_count": 2,
        "has_uvs": True,
        "has_normals": False,
        "object_count": 1,
        "name": "Imported Quad",
    }
    assert all(metadata.get(key) == value for key, value in expected_metadata.items())
    assert metadata["unique_position_count"] == 4
    assert metadata["boundary_edges"] == 4
    assert metadata["non_manifold_edges"] == 0
    assert metadata["degenerate_triangles"] == 0
    assert np.isfinite(geometry.vertices).all()
    assert np.allclose(np.linalg.norm(geometry.vertices[:, 3:6], axis=1), 1.0)
    assert set(np.unique(geometry.vertices[:, 4]).round(6)) == {-1.0}

    renamed = evaluate_mesh_input_geometry({}, {"path": str(quad_path), "name": "Hero Mesh"})
    assert renamed.name == "Hero Mesh"

    parameters = {"path": str(quad_path)}
    refresh_mesh_metadata(parameters)
    assert parameters["_source_vertex_count"] == 4
    assert parameters["_source_triangle_count"] == 2
    assert parameters["_source_has_uvs"] is True
    assert parameters["_source_has_normals"] is False
    assert parameters["_source_name"] == "Imported Quad"
    assert "_source_error" not in parameters

    encoded = base64.b64encode(QUAD_OBJ.encode("utf-8")).decode("ascii")
    embedded, embedded_metadata = load_obj_geometry(
        {"path": "", "_embedded_data": encoded, "_embedded_name": "embedded-quad.obj"}
    )
    assert embedded.vertex_count == 4
    assert embedded.triangle_count == 2
    assert embedded_metadata["name"] == "Imported Quad"

    negative_path = root / "negative.obj"
    negative_path.write_text(NEGATIVE_INDEX_OBJ, encoding="utf-8")
    negative, negative_metadata = load_obj_geometry({"path": str(negative_path)})
    assert negative.vertex_count == 3
    assert negative.triangle_count == 1
    assert negative_metadata["has_normals"] is True
    assert np.allclose(negative.vertices[:, 3:6], (0.0, 0.0, 1.0))

    seam_path = root / "seam.obj"
    seam_path.write_text(UV_SEAM_OBJ, encoding="utf-8")
    seam, seam_metadata = load_obj_geometry({"path": str(seam_path)})
    assert seam.triangle_count == 2
    assert seam.vertex_count == 6, "UV seams must duplicate interleaved vertices"
    assert seam_metadata["has_uvs"] is True

    return quad_path


def assert_resource_migration(root: Path, mesh_path: Path) -> GraphResourceLibrary:
    image_path = root / "source.png"
    image_path.write_bytes(b"not-decoded-by-resource-migration")
    data = _graph(
        [
            {
                "uid": "image-a",
                "type": "input.image",
                "parameters": {"path": str(image_path), "embedded": False, "name": "Image A"},
            },
            {
                "uid": "image-b",
                "type": "input.image",
                "parameters": {"path": str(image_path), "embedded": False, "name": "Image B"},
            },
            {
                "uid": "mesh-a",
                "type": "input.mesh",
                "parameters": {"path": str(mesh_path), "embedded": False, "name": ""},
            },
            {
                "uid": "blank-mesh",
                "type": "input.mesh",
                "parameters": {"path": "", "embedded": False, "name": ""},
            },
        ]
    )

    library = migrate_project_resources(data)
    assert data["resources"] == library.to_dict()
    assert len(library.resources) == 2
    assert sorted(resource.kind for resource in library.resources) == ["image", "mesh"]
    assert {folder.name for folder in library.folders} == {"Images", "Meshes"}

    image_a = data["nodes"][0]["parameters"]
    image_b = data["nodes"][1]["parameters"]
    mesh_a = data["nodes"][2]["parameters"]
    blank = data["nodes"][3]["parameters"]
    assert image_a["_resource_id"] == image_b["_resource_id"]
    assert image_a["_resource_id"] != mesh_a["_resource_id"]
    assert "_resource_id" not in blank

    # Migration is idempotent and does not multiply records.
    migrated_again = migrate_project_resources(data)
    assert len(migrated_again.resources) == 2
    assert data["nodes"][0]["parameters"]["path"] == str(image_path)

    # A per-node portability-mode change also splits shared uses. It must not
    # silently make every node embedding the same linked file local.
    mode_data = _graph(
        [
            {
                "uid": "mode-a",
                "type": "input.image",
                "parameters": {"path": str(image_path), "embedded": False},
            },
            {
                "uid": "mode-b",
                "type": "input.image",
                "parameters": {"path": str(image_path), "embedded": False},
            },
        ]
    )
    mode_library = migrate_project_resources(mode_data)
    mode_a = mode_data["nodes"][0]["parameters"]
    mode_b = mode_data["nodes"][1]["parameters"]
    assert mode_a["_resource_id"] == mode_b["_resource_id"]
    mode_b["embedded"] = True
    mode_library.capture_serialized_nodes(mode_data["nodes"])
    assert mode_a["_resource_id"] != mode_b["_resource_id"]

    # Editing only one of two shared nodes splits that use rather than silently
    # replacing the source for both nodes.
    alternate_image = root / "alternate.png"
    alternate_image.write_bytes(b"alternate-resource")
    image_b["path"] = str(alternate_image)
    migrated_again.capture_serialized_nodes(data["nodes"])
    assert image_a["_resource_id"] != image_b["_resource_id"]
    assert len(migrated_again.resources) == 3
    assert migrated_again.by_id(image_a["_resource_id"]).source_path == str(image_path)
    assert migrated_again.by_id(image_b["_resource_id"]).source_path == str(alternate_image)

    # When all uses of one shared record change together, update that record in
    # place rather than manufacturing an unused duplicate.
    shared_uid = image_a["_resource_id"]
    image_c = {
        "uid": "image-c",
        "type": "input.image",
        "parameters": dict(image_a),
    }
    data["nodes"].append(image_c)
    group_image = root / "group-replaced.png"
    group_image.write_bytes(b"group-replaced")
    image_a["path"] = str(group_image)
    image_c["parameters"]["path"] = str(group_image)
    migrated_again.capture_serialized_nodes(data["nodes"])
    assert image_a["_resource_id"] == shared_uid
    assert image_c["parameters"]["_resource_id"] == shared_uid
    assert migrated_again.by_id(shared_uid).source_path == str(group_image)

    mesh_resource = migrated_again.by_id(mesh_a["_resource_id"])
    assert mesh_resource is not None
    folder = migrated_again.add_folder("Production")
    nested = migrated_again.add_folder("High Poly", folder.uid)
    assert migrated_again.move_resource(mesh_resource.uid, nested.uid)
    assert mesh_resource.folder_uid == nested.uid
    assert migrated_again.rename_folder(nested.uid, "Meshes To Bake")
    assert migrated_again.rename_resource(mesh_resource.uid, "Hero Quad")
    assert mesh_resource.name == "Hero Quad"

    replacement = root / "replacement.obj"
    replacement.write_text(NEGATIVE_INDEX_OBJ, encoding="utf-8")
    migrated_again.relink(mesh_resource.uid, replacement)
    assert mesh_resource.name == "Hero Quad", "A custom resource name survives relinking"
    assert mesh_resource.source_path == str(replacement.resolve())
    assert not mesh_resource.embedded_data

    migrated_again.embed(mesh_resource.uid)
    assert mesh_resource.source_path == ""
    assert mesh_resource.embedded is True
    assert base64.b64decode(mesh_resource.embedded_data) == replacement.read_bytes()

    restored = root / "restored.obj"
    migrated_again.restore_embedded(mesh_resource.uid, restored, relink=True)
    assert restored.read_bytes() == replacement.read_bytes()
    assert mesh_resource.source_path == str(restored.resolve())
    assert mesh_resource.embedded_data == ""

    # Removing a virtual folder reparents its contents without touching disk.
    assert migrated_again.remove_folder(nested.uid)
    assert mesh_resource.folder_uid == folder.uid
    assert restored.is_file()

    unused = GraphResource(kind="mesh", name="Unused", source_path=str(mesh_path))
    migrated_again.resources.append(unused)
    assert not migrated_again.remove_resource(unused.uid, referenced=1)
    assert migrated_again.remove_resource(unused.uid, referenced=0)
    return migrated_again


def assert_embedded_image_migration() -> None:
    payload = b"legacy-embedded-image-payload"
    encoded = base64.b64encode(payload).decode("ascii")
    data = _graph(
        [
            {
                "uid": "legacy-image-a",
                "type": "input.image",
                "parameters": {
                    "path": "",
                    "embedded": True,
                    "_embedded_data": encoded,
                    "_embedded_name": "legacy.png",
                    "data_type": "Colour",
                    "_resolved_kind": "color",
                },
            },
            {
                "uid": "legacy-image-b",
                "type": "input.image",
                "parameters": {
                    "path": "",
                    "embedded": True,
                    "_embedded_data": encoded,
                    "_embedded_name": "legacy.png",
                    "data_type": "Colour",
                    "_resolved_kind": "color",
                },
            },
        ]
    )
    library = migrate_project_resources(data)
    assert len(library.resources) == 1
    first = data["nodes"][0]["parameters"]
    second = data["nodes"][1]["parameters"]
    assert first["_resource_id"] == second["_resource_id"]
    assert first["data_type"] == "Colour" and first["_resolved_kind"] == "color"
    resource = library.by_id(first["_resource_id"])
    assert resource is not None
    assert base64.b64decode(resource.embedded_data) == payload

    assert library.compact_serialized_nodes(data["nodes"]) == 2
    assert "_embedded_data" not in first and "_embedded_data" not in second
    reloaded = json.loads(json.dumps(data))
    GraphResourceLibrary.from_project_data(reloaded)
    for entry in reloaded["nodes"]:
        parameters = entry["parameters"]
        assert base64.b64decode(parameters["_embedded_data"]) == payload
        assert parameters["data_type"] == "Colour"
        assert parameters["_resolved_kind"] == "color"


def assert_cross_graph_resource_copy(root: Path, mesh_path: Path) -> None:
    source_library = GraphResourceLibrary()
    references = source_library.add_folder("References")
    high_poly = source_library.add_folder("High Poly", references.uid)
    source_resource = GraphResource(
        kind="mesh",
        name="Hero High",
        folder_uid=high_poly.uid,
        source_path="assets/hero.obj",
        metadata={"_display_name_custom": True, "nested": {"value": 1}},
    )
    source_library.resources.append(source_resource)

    source_graph = root / "source" / "asset.vfxgraph"
    source_graph.parent.mkdir(parents=True, exist_ok=True)
    linked_mesh = source_graph.parent / "assets" / "hero.obj"
    linked_mesh.parent.mkdir(parents=True, exist_ok=True)
    linked_mesh.write_bytes(mesh_path.read_bytes())

    target_library = GraphResourceLibrary()
    copied = target_library.copy_resource_from(
        source_library, source_resource.uid, source_owner_path=source_graph
    )
    assert copied.uid != source_resource.uid
    assert copied.name == "Hero High"
    assert copied.source_path == str(linked_mesh.resolve())
    copied_folder = target_library.folder_by_id(copied.folder_uid)
    assert copied_folder is not None and copied_folder.name == "High Poly"
    copied_parent = target_library.folder_by_id(copied_folder.parent_uid)
    assert copied_parent is not None and copied_parent.name == "References"
    assert copied.metadata == source_resource.metadata
    copied.metadata["nested"]["value"] = 2
    assert source_resource.metadata["nested"]["value"] == 1, "Cross-graph copies must own metadata"

    parameters = target_library.parameters_for_resource(copied.uid)
    assert parameters["_resource_id"] == copied.uid
    assert parameters["path"] == str(linked_mesh.resolve())
    assert parameters["embedded"] is False

    duplicate = target_library.copy_resource_from(
        source_library, source_resource.uid, source_owner_path=source_graph
    )
    assert duplicate.uid == copied.uid, "Repeated cross-graph drops should reuse the copied resource"
    assert len(target_library.resources) == 1

    embedded_source = GraphResource(
        kind="image",
        name="Embedded Mask",
        embedded=True,
        embedded_data=base64.b64encode(b"mask-bytes").decode("ascii"),
        embedded_name="mask.png",
    )
    source_library.resources.append(embedded_source)
    embedded_copy = target_library.copy_resource_from(source_library, embedded_source.uid)
    embedded_parameters = target_library.parameters_for_resource(embedded_copy.uid)
    assert embedded_copy.uid != embedded_source.uid
    assert embedded_parameters["path"] == ""
    assert embedded_parameters["embedded"] is True
    assert base64.b64decode(embedded_parameters["_embedded_data"]) == b"mask-bytes"


def assert_portable_and_package(root: Path, mesh_path: Path) -> None:
    graph = _graph(
        [
            {
                "uid": "mesh-a",
                "type": "input.mesh",
                "parameters": {"path": str(mesh_path), "embedded": False, "name": "Imported Quad"},
            },
            {
                "uid": "mesh-b",
                "type": "input.mesh",
                "parameters": {"path": str(mesh_path), "embedded": False, "name": "Second Use"},
            },
        ]
    )
    portable, report = build_self_contained_graph(
        graph,
        owner_path=root / "mesh-resource.vfxgraph",
        app_version="0.51.0",
    )
    validate_self_contained_graph(portable)
    parameters = portable["nodes"][0]["parameters"]
    assert parameters["embedded"] is True
    assert parameters["path"] == ""
    assert "_embedded_data" not in parameters, "Embedded bytes are stored once in graph resources"
    assert report.meshes == 2
    assert report.images == 0
    assert recovery_summary(portable)["embedded_meshes"] == 2
    assert len(portable["resources"]["items"]) == 1
    portable_resource = portable["resources"]["items"][0]
    assert portable_resource["kind"] == "mesh"
    assert portable_resource["uid"] == parameters["_resource_id"]
    assert portable["nodes"][1]["parameters"]["_resource_id"] == parameters["_resource_id"]
    assert "_embedded_data" not in portable["nodes"][1]["parameters"]
    assert portable_resource["embedded"] is True
    assert base64.b64decode(portable_resource["embedded_data"]) == mesh_path.read_bytes()

    # Loading format 19 hydrates the compact node parameters for unchanged
    # geometry/image evaluators, while serialising compacts them again.
    hydrated = json.loads(json.dumps(portable))
    hydrated_library = GraphResourceLibrary.from_project_data(hydrated)
    hydrated_parameters = hydrated["nodes"][0]["parameters"]
    assert base64.b64decode(hydrated_parameters["_embedded_data"]) == mesh_path.read_bytes()
    assert hydrated_parameters["_embedded_name"] == portable_resource["embedded_name"]
    assert hydrated_library.compact_serialized_nodes(hydrated["nodes"]) == 2
    assert "_embedded_data" not in hydrated_parameters

    nested = asset_graph_data(
        {
            "_asset_mode": "Embedded",
            "_asset_embedded_graph": portable,
        }
    )
    nested_parameters = nested["nodes"][0]["parameters"]
    assert base64.b64decode(nested_parameters["_embedded_data"]) == mesh_path.read_bytes()

    package_path = root / "mesh-resource.vfxpackage"
    info, package_report = create_vfxpackage(
        package_path,
        graph,
        owner_path=root / "mesh-resource.vfxgraph",
        app_version="0.51.0",
        include_mesh_sources=True,
    )
    assert package_report.meshes == 2
    assert len(info.mesh_sources) == 1
    assert any(entry.kind == "mesh-source" for entry in info.files)
    inspected = inspect_vfxpackage(package_path)
    assert len(inspected.mesh_sources) == 1
    source_record = inspected.mesh_sources[0]
    assert source_record["path"].startswith("resources/meshes/")
    assert source_record["path"].endswith(".obj")
    assert len(source_record["uses"]) == 2
    with zipfile.ZipFile(package_path, "r") as archive:
        assert archive.read(source_record["path"]) == mesh_path.read_bytes()
        packaged_graph = json.loads(archive.read(inspected.entry_graph).decode("utf-8"))
    packaged_parameters = packaged_graph["nodes"][0]["parameters"]
    assert packaged_parameters["embedded"] is True
    assert packaged_parameters["path"] == ""
    assert packaged_parameters["_packaged_source_path"].startswith("../resources/meshes/")

    # Packages produced before 0.51.0 have no mesh_sources manifest field
    # and, naturally, no separate mesh-source archive members. Keep that older
    # package shape valid even though the new reader knows about mesh inventories.
    old_shape_package = root / "old-shape-source.vfxpackage"
    create_vfxpackage(
        old_shape_package,
        graph,
        owner_path=root / "mesh-resource.vfxgraph",
        app_version="0.50.2.1",
        include_mesh_sources=False,
    )
    legacy_package = root / "legacy-without-mesh-manifest.vfxpackage"
    with zipfile.ZipFile(old_shape_package, "r") as source, zipfile.ZipFile(
        legacy_package, "w", compression=zipfile.ZIP_DEFLATED
    ) as destination:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "package.vfxmanifest":
                manifest = json.loads(payload.decode("utf-8"))
                manifest.pop("mesh_sources", None)
                manifest.pop("mesh_source_mode", None)
                payload = json.dumps(manifest, indent=2).encode("utf-8")
            destination.writestr(member, payload)
    legacy_info = inspect_vfxpackage(legacy_package)
    assert legacy_info.mesh_sources == []


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="vfx-mesh-resource-test-"))
    assert_mesh_node_contract()
    mesh_path = assert_obj_import(root)
    assert_resource_migration(root, mesh_path)
    assert_cross_graph_resource_copy(root, mesh_path)
    assert_embedded_image_migration()
    assert_portable_and_package(root, mesh_path)
    print(
        "Mesh Input and graph resources test passed: OBJ triangulation/seams/normals, "
        "linked and embedded sources, transparent Image Input migration, virtual folders, "
        "same-graph reuse and cross-graph resource copying, "
        "self-contained export and packaged mesh source preservation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
