from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.vfx_package import (
    PACKAGE_MANIFEST,
    VFXPackageError,
    create_vfxpackage,
    extract_vfxpackage,
    inspect_vfxpackage,
    install_vfxpackage,
    installed_packages,
    read_package_entry_graph,
    write_packaged_custom_node_archives,
)


def fixture_graph() -> dict:
    png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"thumbnail-fixture"
    ).decode("ascii")
    return {
        "format": "vfx-texture-lab-graph",
        "version": 16,
        "document": {},
        "graph_asset": {
            "asset_id": "test-vfxpackage-asset",
            "name": "Packaged Grass",
            "description": "A test asset package.",
            "category": "Environment",
            "tags": ["grass", "terrain"],
            "author": "Tests",
            "version": "1.2.3",
            "created_with": "0.44.3",
            "thumbnail_png": png,
            "thumbnail_source": "imported",
        },
        "nodes": [],
        "connections": [],
        "groups": [],
    }



class FixtureRegistry:
    def __init__(self, root: Path) -> None:
        package = SimpleNamespace(
            package_id="com.example.sine_waves",
            version="1.0.0",
            api_version=2,
            root=str(root),
            source_kind="library",
            revision="fixture-revision",
        )
        self.definition = SimpleNamespace(name="Sine Waves", package=package)

    def get_optional(self, type_id: str):
        return self.definition if type_id == "com.example.sine_waves" else None


def custom_node_graph() -> dict:
    data = fixture_graph()
    data["nodes"] = [{
        "uid": "custom",
        "type": "com.example.sine_waves",
        "parameters": {},
        "definition": {
            "name": "Sine Waves",
            "package_id": "com.example.sine_waves",
            "package_version": "1.0.0",
            "api_version": 2,
        },
    }]
    return data


def image_source_graph(path: Path) -> dict:
    data = fixture_graph()
    data["nodes"] = [
        {
            "uid": "image-a",
            "type": "input.image",
            "parameters": {"path": str(path), "embedded": False, "name": "Grass Source"},
        },
        {
            "uid": "image-b",
            "type": "input.image",
            "parameters": {"path": str(path), "embedded": False, "name": "Grass Source Copy"},
        },
    ]
    return data

def rewrite_archive(source: Path, destination: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED
    ) as changed:
        for info in original.infolist():
            if info.is_dir():
                continue
            changed.writestr(info.filename, replacements.get(info.filename, original.read(info)))


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="vfx-package-test-"))
    package = root / "grass.vfxpackage"
    info, report = create_vfxpackage(
        package, fixture_graph(), owner_path=root / "grass.vfxgraph", app_version="0.44.3"
    )
    assert package.is_file()
    assert info.asset_id == "test-vfxpackage-asset"
    assert info.asset_version == "1.2.3"
    assert info.thumbnail_path == "thumbnail.png"
    assert len(info.files) == 2
    assert report.graph_instances == 0
    assert report.images == 0

    source_image = root / "grass-source.png"
    source_bytes = b"\x89PNG\r\n\x1a\n" + b"exact-source-image-bytes"
    source_image.write_bytes(source_bytes)
    source_package = root / "grass-with-source.vfxpackage"
    source_info, source_report = create_vfxpackage(
        source_package,
        image_source_graph(source_image),
        owner_path=root / "grass-with-source.vfxgraph",
        app_version="0.44.3.1",
        include_image_sources=True,
    )
    assert source_report.images == 2
    assert len(source_info.image_sources) == 1
    assert len(source_info.image_sources[0]["uses"]) == 2
    assert any(entry.kind == "image-source" for entry in source_info.files)
    with zipfile.ZipFile(source_package, "r") as archive:
        image_member = source_info.image_sources[0]["path"]
        assert archive.read(image_member) == source_bytes
        packaged_graph = json.loads(archive.read(source_info.entry_graph).decode("utf-8"))
    for node in packaged_graph["nodes"]:
        parameters = node["parameters"]
        assert parameters["embedded"] is True
        assert parameters["path"] == ""
        assert parameters["_packaged_source_path"].startswith("../resources/images/")

    tampered_source_package = root / "grass-with-tampered-source.vfxpackage"
    rewrite_archive(source_package, tampered_source_package, {image_member: b"changed"})
    try:
        inspect_vfxpackage(tampered_source_package)
    except VFXPackageError as exc:
        assert "integrity" in str(exc).lower() or "size mismatch" in str(exc).lower()
    else:
        raise AssertionError("Tampered packaged image source should fail validation")

    compact_package = root / "grass-embedded-only.vfxpackage"
    compact_info, _ = create_vfxpackage(
        compact_package,
        image_source_graph(source_image),
        owner_path=root / "grass-embedded-only.vfxgraph",
        app_version="0.44.3.1",
        include_image_sources=False,
    )
    assert compact_info.image_sources == []
    assert not any(entry.kind == "image-source" for entry in compact_info.files)

    inspected = inspect_vfxpackage(package)
    assert inspected.name == "Packaged Grass"
    assert inspected.tags == ["grass", "terrain"]
    graph = read_package_entry_graph(package, inspected)
    assert graph["portable_export"]["mode"] == "single-file"

    extracted = root / "editable"
    _, entry = extract_vfxpackage(package, extracted)
    assert entry.is_file()
    assert (extracted / PACKAGE_MANIFEST).is_file()
    assert json.loads(entry.read_text(encoding="utf-8"))["graph_asset"]["asset_id"] == inspected.asset_id

    library = root / "library"
    installed_info, installed_entry = install_vfxpackage(package, library)
    assert installed_entry.is_file()
    matches = installed_packages(library, asset_id=inspected.asset_id)
    assert len(matches) == 1
    assert matches[0].asset_version == "1.2.3"

    side_info, side_entry = install_vfxpackage(package, library, side_by_side=True)
    assert side_info.asset_id == installed_info.asset_id
    assert side_entry.is_file()
    assert len(installed_packages(library, asset_id=inspected.asset_id)) == 2

    replacement_graph = fixture_graph()
    replacement_graph["graph_asset"]["version"] = "1.2.4"
    replacement_package = root / "grass-update.vfxpackage"
    create_vfxpackage(
        replacement_package,
        replacement_graph,
        owner_path=root / "grass-update.vfxgraph",
        app_version="0.44.3",
    )
    stale_file = matches[0].source_path / "stale-file.txt"
    stale_file.write_text("old package debris", encoding="utf-8")
    updated_info, updated_entry = install_vfxpackage(
        replacement_package,
        library,
        replace_directory=matches[0].source_path,
    )
    assert updated_info.asset_version == "1.2.4"
    assert updated_entry.is_file()

    custom_root = Path(__file__).resolve().parents[1] / "examples" / "custom_node_template"
    custom_package = root / "custom-node.vfxpackage"
    custom_info, _ = create_vfxpackage(
        custom_package,
        custom_node_graph(),
        owner_path=root / "custom.vfxgraph",
        app_version="0.44.3",
        registry=FixtureRegistry(custom_root),
    )
    assert len(custom_info.custom_nodes) == 1
    assert any(entry.kind == "custom-node" for entry in custom_info.files)
    custom_archives = write_packaged_custom_node_archives(
        custom_package, root / "node-archives", custom_info
    )
    assert len(custom_archives) == 1
    with zipfile.ZipFile(custom_archives[0][1], "r") as node_archive:
        assert "node.toml" in node_archive.namelist()
        assert "kernel.wgsl" in node_archive.namelist()

    tampered = root / "tampered.vfxpackage"
    rewrite_archive(package, tampered, {inspected.entry_graph: b"{}"})
    try:
        inspect_vfxpackage(tampered)
    except VFXPackageError as exc:
        assert "integrity" in str(exc).lower() or "size mismatch" in str(exc).lower()
    else:
        raise AssertionError("Tampered package should fail hash validation")
    protected_destination = root / "protected-existing-project"
    protected_destination.mkdir()
    sentinel = protected_destination / "keep-me.txt"
    sentinel.write_text("original", encoding="utf-8")
    try:
        extract_vfxpackage(tampered, protected_destination, overwrite=True)
    except VFXPackageError:
        pass
    else:
        raise AssertionError("Tampered package should not replace an existing project")
    assert sentinel.read_text(encoding="utf-8") == "original"

    unsafe = root / "unsafe.vfxpackage"
    with zipfile.ZipFile(unsafe, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../outside.txt", b"nope")
        archive.writestr(PACKAGE_MANIFEST, b"{}")
    try:
        inspect_vfxpackage(unsafe)
    except VFXPackageError as exc:
        assert "root" in str(exc).lower() or "unsafe" in str(exc).lower()
    else:
        raise AssertionError("Path traversal package should be rejected")

    unsupported = root / "unsupported.vfxpackage"
    with zipfile.ZipFile(package, "r") as original:
        manifest = json.loads(original.read(PACKAGE_MANIFEST).decode("utf-8"))
        manifest["version"] = 999
        rewrite_archive(
            package,
            unsupported,
            {PACKAGE_MANIFEST: json.dumps(manifest).encode("utf-8")},
        )
    try:
        inspect_vfxpackage(unsupported)
    except VFXPackageError as exc:
        assert "unsupported" in str(exc).lower()
    else:
        raise AssertionError("Unsupported package version should be rejected")

    print(
        "vfxpackage test passed: creation, manifest/hash validation, safe extraction, "
        "managed install/update/side-by-side and malicious archive rejection"
    )


if __name__ == "__main__":
    main()
