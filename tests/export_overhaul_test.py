from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import tempfile
import sys
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from vfx_texture_lab.export_plan import (
    build_export_artifacts,
    disambiguated_export_filenames,
    export_filename_conflicts,
    resolve_destination,
)
from vfx_texture_lab.exporting import ExportOptions, export_image, pack_export_channels, pack_template_channels, prepare_export_array
from vfx_texture_lab.nodes.registry import build_registry




def png_chunks(path: Path) -> dict[bytes, list[bytes]]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    chunks: dict[bytes, list[bytes]] = {}
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        chunks.setdefault(kind, []).append(payload)
        offset += 12 + length
        if kind == b"IEND":
            break
    return chunks

def fake_node(type_id: str, parameters: dict, kind: str = "grayscale"):
    return SimpleNamespace(
        definition=SimpleNamespace(type_id=type_id),
        parameters=parameters,
        resolved_kind=kind,
    )


def main() -> None:
    registry = build_registry()
    image_output = registry.get("output.image")
    texture_set = registry.get("output.texture_set")
    material_definition = registry.get("material.pbr")
    assert texture_set.terminal
    assert texture_set.inputs == ("Material",)
    assert texture_set.input_kind("Material") == "material"
    assert material_definition.output_kind("Material") == "material"
    assert material_definition.input_kind("Normal") == "vector"
    assert material_definition.input_kind("Base Colour") == "color"
    assert material_definition.input_kind("Roughness") == "grayscale"
    assert {spec.name for spec in image_output.parameters} >= {
        "export_preset", "export_filename", "export_resolution", "export_format",
    }

    document = SimpleNamespace(width=1024, height=512)
    colour = fake_node(
        "output.image",
        {"name": "Fire Colour", "export_filename": "{output}_{width}x{height}", "export_preset": "Auto from data type", "export_resolution": "Document"},
        "color",
    )
    vector = fake_node(
        "output.image",
        {"name": "Fire Normal", "export_filename": "{output}", "export_preset": "Normal Map (DirectX -Y)", "export_resolution": "512 × 512"},
        "vector",
    )
    linear_mask = fake_node(
        "output.image",
        {"name": "Grass Mask", "export_filename": "{output}", "export_preset": "Linear Data", "export_resolution": "Document"},
        "grayscale",
    )
    texture = fake_node(
        "output.texture_set",
        {
            "name": "Rock",
            "export_filename": "{set}_{map}",
            "export_preset": "Unreal ORM",
            "export_resolution": "2048 × 2048",
            "normal_convention": "DirectX (-Y)",
            "texture_format": "PNG",
            "colour_bit_depth": "8",
            "data_bit_depth": "16",
            "height_format": "PNG 16-bit",
        },
        "color",
    )
    material = fake_node("material.pbr", {"name": "Rock Material"}, "color")
    snapshot = SimpleNamespace(
        nodes={"colour": colour, "vector": vector, "linear": linear_mask, "set": texture, "material": material},
        inputs={
            ("colour", "Image"): ("colour_source", "Image"),
            ("vector", "Image"): ("vector_source", "Image"),
            ("linear", "Image"): ("linear_source", "Image"),
            ("set", "Material"): ("material", "Material"),
            ("material", "Base Colour"): ("base", "Image"),
            ("material", "Normal"): ("normal", "Image"),
            ("material", "Ambient Occlusion"): ("ao", "Image"),
            ("material", "Roughness"): ("rough", "Image"),
            ("material", "Metallic"): ("metal", "Image"),
        },
    )
    artifacts = build_export_artifacts(snapshot, ["colour", "vector", "linear", "set"], document)
    by_label = {artifact.label: artifact for artifact in artifacts}
    assert by_label["Fire Colour"].filename == "Fire_Colour_1024x512.png"
    assert by_label["Fire Colour"].options.colour_encoding == "sRGB"
    assert by_label["Fire Normal"].options.flip_green
    assert by_label["Fire Normal"].options.colour_encoding == "Linear"
    assert by_label["Fire Normal"].options.channels == "RGB"
    assert by_label["Fire Normal"].width == 512
    assert by_label["Grass Mask"].options.colour_encoding == "Linear"
    assert by_label["Grass Mask"].options.channels == "Grayscale"
    assert by_label["Grass Mask"].options.bit_depth == 16
    orm_artifact = by_label["Rock · ORM"]
    assert orm_artifact.operation == "template_pack"
    assert orm_artifact.filename == "Rock_ORM.png"
    assert by_label["Rock · Normal"].normal_directx
    assert by_label["Rock · Normal"].options.colour_encoding == "Linear"
    assert orm_artifact.options.colour_encoding == "Linear"

    source = np.zeros((2, 2, 4), dtype=np.float32)
    source[..., 0] = 0.25
    source[..., 1] = 0.2
    source[..., 2] = 1.0
    source[..., 3] = 1.0
    flipped = prepare_export_array(source, ExportOptions(channels="RGB", flip_green=True))
    assert np.allclose(flipped[..., 1], 0.8)

    ao = np.full((2, 2, 4), 0.8, dtype=np.float32)
    rough = np.full((2, 2, 4), 0.25, dtype=np.float32)
    metal = np.full((2, 2, 4), 0.6, dtype=np.float32)
    orm = pack_export_channels(2, 2, red=ao, green=rough, blue=metal, red_default=1.0)
    assert np.allclose(orm[..., 0], 0.8)
    assert np.allclose(orm[..., 1], 0.25)
    assert np.allclose(orm[..., 2], 0.6)
    assert np.allclose(orm[..., 3], 1.0)

    template_orm = pack_template_channels(
        2, 2,
        {"Ambient Occlusion": ao, "Roughness": rough, "Metallic": metal},
        orm_artifact.channel_bindings,
    )
    assert np.allclose(template_orm[..., 0], 0.8)
    assert np.allclose(template_orm[..., 1], 0.25)
    assert np.allclose(template_orm[..., 2], 0.6)

    normal_artifact = by_label["Rock · Normal"]
    template_normal = pack_template_channels(
        2, 2,
        {"Normal": source},
        normal_artifact.channel_bindings,
        normal_directx=True,
    )
    assert np.allclose(template_normal[..., 1], 0.8)

    mask = pack_export_channels(
        2, 2,
        red=metal,
        green=ao,
        blue=None,
        alpha=rough,
        blue_default=1.0,
        invert_alpha=True,
    )
    assert np.allclose(mask[..., 0], 0.6)
    assert np.allclose(mask[..., 1], 0.8)
    assert np.allclose(mask[..., 2], 1.0)
    assert np.allclose(mask[..., 3], 0.75)

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        png = root / "test.png"
        export_image(png, source, ExportOptions("PNG", 16, "RGBA", "Luminance", "Linear"))
        with Image.open(png) as opened:
            assert opened.size == (2, 2)
        linear_chunks = png_chunks(png)
        assert b"sRGB" not in linear_chunks
        assert b"gAMA" not in linear_chunks

        # Template packing returns H×W×1 for scalar files. Export preparation
        # must preserve those values rather than indexing nonexistent G/B/A.
        scalar_template = np.full((2, 2, 1), 0.375, dtype=np.float32)
        prepared_scalar = prepare_export_array(
            scalar_template, ExportOptions("PNG", 16, "Grayscale", "Luminance", "Linear")
        )
        assert prepared_scalar.shape == (2, 2, 1)
        assert np.allclose(prepared_scalar[..., 0], 0.375)
        scalar_png = root / "scalar-template.png"
        export_image(
            scalar_png, scalar_template, ExportOptions("PNG", 16, "Grayscale", "Luminance", "Linear")
        )
        with Image.open(scalar_png) as opened:
            assert opened.size == (2, 2)
        scalar_r16 = root / "scalar-template.r16"
        export_image(
            scalar_r16, scalar_template, ExportOptions("R16", 16, "Grayscale", "Luminance", "Linear")
        )
        assert scalar_r16.stat().st_size == 2 * 2 * 2
        expanded_rgb = prepare_export_array(
            scalar_template, ExportOptions("PNG", 8, "RGB", "Luminance", "Linear")
        )
        expanded_rgba = prepare_export_array(
            scalar_template, ExportOptions("PNG", 8, "RGBA", "Luminance", "Linear")
        )
        assert expanded_rgb.shape == (2, 2, 3) and np.allclose(expanded_rgb, 0.375)
        assert expanded_rgba.shape == (2, 2, 4)
        assert np.allclose(expanded_rgba[..., :3], 0.375)
        assert np.allclose(expanded_rgba[..., 3], 1.0)

        srgb_png = root / "colour.png"
        export_image(srgb_png, source, ExportOptions("PNG", 8, "RGBA", "Luminance", "sRGB"))
        srgb_chunks = png_chunks(srgb_png)
        assert b"sRGB" in srgb_chunks
        assert b"gAMA" not in srgb_chunks

        normal_png = root / "normal.png"
        export_image(normal_png, source, ExportOptions("PNG", 8, "RGB", "Luminance", "Linear"))
        normal_chunks = png_chunks(normal_png)
        assert b"sRGB" not in normal_chunks and b"gAMA" not in normal_chunks
        tga = root / "test.tga"
        export_image(tga, source, ExportOptions("TGA", 8, "RGB", "Luminance", "Linear"))
        with Image.open(tga) as opened:
            assert opened.size == (2, 2)
        r16 = root / "height.r16"
        export_image(r16, source, ExportOptions("R16", 16, "Grayscale", "Red", "Linear"))
        assert r16.stat().st_size == 2 * 2 * 2
        reserved: set[str] = set()
        first = resolve_destination(root, "test.png", "Add numeric suffix", reserved)
        second = resolve_destination(root, "test.png", "Add numeric suffix", reserved)
        assert first is not None and first.name == "test_2.png"
        assert second is not None and second.name == "test_3.png"
        assert resolve_destination(root, "test.png", "Skip existing", set()) is None
        replaced = resolve_destination(root, "test.png", "Replace existing", set())
        assert replaced is not None and replaced.name == "test.png"
        replaced_again = resolve_destination(root, "test.png", "Replace existing", set())
        assert replaced_again is not None and replaced_again.name == "test.png"

        conflict_a = replace(by_label["Fire Colour"], owner_uid="node-a1234567", owner_name="First Output", filename="shared.png")
        conflict_b = replace(by_label["Grass Mask"], owner_uid="node-b7654321", owner_name="Second Output", filename="shared.png")
        conflicts = export_filename_conflicts([conflict_a, conflict_b])
        assert set(conflicts) == {"shared.png"}
        safe_names = disambiguated_export_filenames([conflict_a, conflict_b])
        assert safe_names == ["shared__First_Output.png", "shared__Second_Output.png"]
        assert disambiguated_export_filenames([conflict_a, conflict_b]) == safe_names

    print("Export overhaul test passed: typed output defaults, reusable template planning, arbitrary channel packing, normal Y conversion, PNG writing, overwrite defaults and stable conflict disambiguation.")


if __name__ == "__main__":
    main()
