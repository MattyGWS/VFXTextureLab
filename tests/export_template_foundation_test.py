from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from vfx_texture_lab.export_plan import build_export_artifacts
from vfx_texture_lab.export_templates import (
    CUSTOM_TEMPLATE_NAME,
    ExportChannelBinding,
    ExportTemplate,
    builtin_template,
    builtin_template_names,
    clone_as_custom,
    effective_export_template,
    validate_export_template,
)
from vfx_texture_lab.exporting import pack_template_channels
from vfx_texture_lab.nodes.registry import build_registry


def fake_node(type_id: str, parameters: dict, kind: str = "color"):
    return SimpleNamespace(
        definition=SimpleNamespace(type_id=type_id),
        parameters=parameters,
        resolved_kind=kind,
    )


def material_snapshot(parameters: dict):
    output = fake_node("output.texture_set", parameters)
    material = fake_node("material.pbr", {})
    return SimpleNamespace(
        nodes={"set": output, "material": material},
        inputs={
            ("set", "Material"): ("material", "Material"),
            ("material", "Base Colour"): ("base", "Image"),
            ("material", "Normal"): ("normal", "Image"),
            ("material", "Ambient Occlusion"): ("ao", "Image"),
            ("material", "Roughness"): ("rough", "Image"),
            ("material", "Metallic"): ("metal", "Image"),
            ("material", "Height"): ("height", "Image"),
        },
    )


def main() -> None:
    names = builtin_template_names()
    assert names == (
        "Generic PBR Separate",
        "Unreal ORM",
        "Unity HDRP Mask Map",
        "Godot ORM",
        "VFX RGBA Masks",
    )
    for name in names:
        template = builtin_template(name)
        errors, _warnings = validate_export_template(template)
        assert not errors
        assert template.built_in
        assert template.files

    legacy = effective_export_template({"export_preset": "Separate PBR Maps"})
    assert legacy.name == "Generic PBR Separate"

    custom = clone_as_custom(builtin_template("Unity HDRP Mask Map"), name="Studio HDRP")
    custom_roundtrip = ExportTemplate.from_dict(custom.to_dict())
    assert custom_roundtrip.name == "Studio HDRP"
    assert len(custom_roundtrip.files) == len(custom.files)
    assert effective_export_template(
        {"export_preset": CUSTOM_TEMPLATE_NAME, "_custom_export_template": custom.to_dict()}
    ).name == "Studio HDRP"

    registry = build_registry()
    texture_set = registry.get("output.texture_set")
    preset = texture_set.parameter_spec("export_preset")
    assert preset is not None
    assert preset.default == "Generic PBR Separate"
    assert CUSTOM_TEMPLATE_NAME in preset.options

    parameters = {
        "name": "Stone",
        "export_filename": "{set}_{map}",
        "export_preset": "Unity HDRP Mask Map",
        "normal_convention": "DirectX (-Y)",
        "texture_format": "PNG",
        "colour_bit_depth": "8",
        "data_bit_depth": "16",
        "height_format": "Raw R16",
        "export_resolution": "1024 × 1024",
    }
    artifacts = build_export_artifacts(
        material_snapshot(parameters), ["set"], SimpleNamespace(width=512, height=512)
    )
    by_name = {artifact.filename: artifact for artifact in artifacts}
    assert "Stone_BaseColor.png" in by_name
    assert "Stone_Normal.png" in by_name
    assert "Stone_Height.r16" in by_name
    assert "Stone_MaskMap.png" in by_name
    assert by_name["Stone_MaskMap.png"].operation == "template_pack"
    assert by_name["Stone_Normal.png"].normal_directx

    scalar = lambda value: np.full((2, 2, 4), value, dtype=np.float32)
    mask = pack_template_channels(
        2,
        2,
        {
            "Metallic": scalar(0.7),
            "Ambient Occlusion": scalar(0.9),
            "Roughness": scalar(0.2),
        },
        by_name["Stone_MaskMap.png"].channel_bindings,
    )
    assert np.allclose(mask[..., 0], 0.7)
    assert np.allclose(mask[..., 1], 0.9)
    assert np.allclose(mask[..., 2], 1.0)
    assert np.allclose(mask[..., 3], 0.8)

    # A missing assigned semantic channel falls back to the material default
    # while another present channel keeps the file exportable.
    bindings = (
        ("R", ExportChannelBinding("Ambient Occlusion", "Red")),
        ("G", ExportChannelBinding("Roughness", "Red")),
        ("B", ExportChannelBinding("Metallic", "Red")),
    )
    packed = pack_template_channels(
        2, 2, {"Roughness": scalar(0.35)}, bindings
    )
    assert np.allclose(packed[..., 0], 1.0)
    assert np.allclose(packed[..., 1], 0.35)
    assert np.allclose(packed[..., 2], 0.0)

    main_window = (ROOT / "vfx_texture_lab/main_window.py").read_text()
    parameters_ui = (ROOT / "vfx_texture_lab/ui/parameters.py").read_text()
    dialog_ui = (ROOT / "vfx_texture_lab/ui/export_template_dialog.py").read_text()
    export_ui = (ROOT / "vfx_texture_lab/ui/export_dialog.py").read_text()
    assert "ExportTemplateDialog" in main_window
    assert "pack_template_channels" in main_window
    assert "Customise Template…" in parameters_ui
    assert "Channel assignments" in dialog_ui
    assert "Planned Files" in export_ui

    print(
        "Export template foundation test passed: built-in/legacy templates, graph-local custom serialization, "
        "arbitrary RGBA packing, semantic defaults, normal convention planning, R16 height handling and preflight UI hooks."
    )


if __name__ == "__main__":
    main()
