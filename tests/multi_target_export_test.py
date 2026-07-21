from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.export_plan import (
    build_multi_target_artifacts,
    disambiguated_export_filenames,
    export_filename_conflicts,
)
from vfx_texture_lab.export_profiles import (
    ExportProfileLibrary,
    ExportProfileSet,
    ExportTarget,
    NODE_TEMPLATE,
)


def fake_node(type_id: str, parameters: dict, kind: str = "color"):
    return SimpleNamespace(
        definition=SimpleNamespace(type_id=type_id),
        parameters=parameters,
        resolved_kind=kind,
    )


def main() -> None:
    output = fake_node(
        "output.texture_set",
        {
            "name": "Rock",
            "export_filename": "{graph}_{target}_{map}_{width}x{height}",
            "export_preset": "VFX RGBA Masks",
            "export_resolution": "512 × 512",
            "normal_convention": "OpenGL (+Y)",
            "texture_format": "PNG",
            "colour_bit_depth": "8",
            "data_bit_depth": "8",
            "height_format": "PNG 16-bit",
        },
    )
    material = fake_node("material.pbr", {})
    snapshot = SimpleNamespace(
        nodes={"set": output, "material": material},
        inputs={
            ("set", "Material"): ("material", "Material"),
            ("material", "Base Colour"): ("base", "Image"),
            ("material", "Normal"): ("normal", "Image"),
            ("material", "Height"): ("height", "Image"),
            ("material", "Ambient Occlusion"): ("ao", "Image"),
            ("material", "Roughness"): ("rough", "Image"),
            ("material", "Metallic"): ("metal", "Image"),
        },
    )
    unreal = ExportTarget.from_dict(
        {
            "name": "Unreal Production",
            "template_name": "Unreal ORM",
            "subfolder": "{profile}/{target}",
            "resolution": "1024 × 1024",
            "normal_convention": "DirectX (-Y)",
            "data_bit_depth": "8",
        }
    )
    source = ExportTarget.from_dict(
        {
            "name": "Source Archive",
            "template_name": "Generic PBR Separate",
            "subfolder": "{profile}/{graph}_{version}/{target}",
            "resolution": "2048 × 2048",
            "colour_bit_depth": "16",
            "data_bit_depth": "16",
        }
    )
    profile = ExportProfileSet.from_dict(
        {"name": "Studio Publish", "targets": [unreal.to_dict(), source.to_dict()]}
    )
    library = ExportProfileLibrary(profile.profile_id, (profile,))
    roundtrip = ExportProfileLibrary.from_dict(library.to_dict())
    assert roundtrip.active_profile().name == "Studio Publish"
    assert len(roundtrip.active_profile().targets) == 2

    artifacts = build_multi_target_artifacts(
        snapshot,
        ["set"],
        SimpleNamespace(width=256, height=256),
        roundtrip.active_profile(),
        graph_name="Cliff Rock",
        graph_version="2.3.0",
    )
    assert artifacts
    unreal_files = [a for a in artifacts if a.target_name == "Unreal Production"]
    source_files = [a for a in artifacts if a.target_name == "Source Archive"]
    assert unreal_files and source_files
    assert all(a.width == 1024 and a.height == 1024 for a in unreal_files)
    assert all(a.width == 2048 and a.height == 2048 for a in source_files)
    assert all(a.relative_path.startswith("Studio_Publish/Unreal_Production/") for a in unreal_files)
    assert all(a.relative_path.startswith("Studio_Publish/Cliff_Rock_2.3.0/Source_Archive/") for a in source_files)
    assert any("Cliff_Rock_Unreal_Production_ORM_1024x1024.png" in a.relative_path for a in unreal_files)
    assert any(a.normal_directx for a in unreal_files if a.filename.endswith("Normal_1024x1024.png"))
    assert any(a.options.bit_depth == 16 for a in source_files if "AO" in a.filename)

    # The current-node template remains a valid target and does not overwrite
    # the output node's authored custom/built-in selection.
    current = ExportProfileSet.from_dict(
        {"name": "Current", "targets": [{"name": "Node", "template_name": NODE_TEMPLATE, "subfolder": ""}]}
    )
    current_artifacts = build_multi_target_artifacts(
        snapshot, ["set"], SimpleNamespace(width=256, height=256), current,
        graph_name="Cliff Rock", graph_version="2.3.0",
    )
    assert len(current_artifacts) == 1
    assert current_artifacts[0].filename.endswith("Masks_512x512.png")

    # Nested target paths participate in conflict detection and retain their
    # parent directory when stable disambiguation is required.
    duplicate = [unreal_files[0], unreal_files[0]]
    assert export_filename_conflicts(duplicate)
    resolved = disambiguated_export_filenames(duplicate)
    assert all("/" in name for name in resolved)
    assert len(set(resolved)) == 2

    print(
        "Multi-target export test passed: profile persistence, target template/format/resolution overrides, "
        "expanded naming variables, target subfolders, current-node templates and nested-path collision safety."
    )


if __name__ == "__main__":
    main()
