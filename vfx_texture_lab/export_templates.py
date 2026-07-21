from __future__ import annotations

"""Reusable export-template definitions for Texture Set Output.

Templates deliberately describe files and channel assignments independently
from graph evaluation.  A Texture Set Output supplies semantic material
channels; a template decides how those channels become production files.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Iterable, Mapping
from string import Formatter

from .material import MATERIAL_INPUTS

EXPORT_TEMPLATE_FORMAT_VERSION = 1
CUSTOM_TEMPLATE_NAME = "Custom Template"

FORMAT_OPTIONS = ("Texture-set setting", "Height setting", "PNG", "TGA", "R16")
BIT_DEPTH_OPTIONS = ("Colour setting", "Scalar setting", "8", "16")
COLOUR_ENCODING_OPTIONS = ("sRGB", "Linear")
CHANNEL_LAYOUT_OPTIONS = ("Grayscale", "RGB", "RGBA")
COMPONENT_OPTIONS = ("Red", "Green", "Blue", "Alpha", "Luminance")


@dataclass(frozen=True, slots=True)
class ExportChannelBinding:
    source: str = "Constant"
    component: str = "Red"
    invert: bool = False
    constant: float = 0.0
    normal_y: bool = False

    @property
    def is_constant(self) -> bool:
        return self.source == "Constant"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "component": self.component,
            "invert": bool(self.invert),
            "constant": float(self.constant),
            "normal_y": bool(self.normal_y),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ExportChannelBinding":
        raw = dict(data or {})
        source = str(raw.get("source", "Constant"))
        if source != "Constant" and source not in MATERIAL_INPUTS:
            source = "Constant"
        component = str(raw.get("component", "Red"))
        if component not in COMPONENT_OPTIONS:
            component = "Red"
        return cls(
            source=source,
            component=component,
            invert=bool(raw.get("invert", False)),
            constant=max(0.0, min(float(raw.get("constant", 0.0)), 1.0)),
            normal_y=bool(raw.get("normal_y", False)),
        )


@dataclass(frozen=True, slots=True)
class ExportFileTemplate:
    name: str
    map_name: str
    filename: str = ""
    format_name: str = "Texture-set setting"
    bit_depth: str = "Scalar setting"
    channels: str = "RGBA"
    colour_encoding: str = "Linear"
    bindings: tuple[tuple[str, ExportChannelBinding], ...] = ()
    always_export: bool = False
    description: str = ""

    def binding(self, channel: str) -> ExportChannelBinding:
        for candidate, binding in self.bindings:
            if candidate == channel:
                return binding
        default = 1.0 if channel == "A" else 0.0
        return ExportChannelBinding(constant=default)

    def active_channels(self) -> tuple[str, ...]:
        if self.channels == "Grayscale":
            return ("R",)
        if self.channels == "RGB":
            return ("R", "G", "B")
        return ("R", "G", "B", "A")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "map_name": self.map_name,
            "filename": self.filename,
            "format": self.format_name,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "colour_encoding": self.colour_encoding,
            "bindings": {channel: binding.to_dict() for channel, binding in self.bindings},
            "always_export": bool(self.always_export),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, ordinal: int = 1) -> "ExportFileTemplate":
        raw = dict(data or {})
        channels = str(raw.get("channels", "RGBA"))
        if channels not in CHANNEL_LAYOUT_OPTIONS:
            channels = "RGBA"
        format_name = str(raw.get("format", "Texture-set setting"))
        if format_name not in FORMAT_OPTIONS:
            format_name = "Texture-set setting"
        bit_depth = str(raw.get("bit_depth", "Scalar setting"))
        if bit_depth not in BIT_DEPTH_OPTIONS:
            bit_depth = "Scalar setting"
        encoding = str(raw.get("colour_encoding", "Linear"))
        if encoding not in COLOUR_ENCODING_OPTIONS:
            encoding = "Linear"
        bindings_raw = raw.get("bindings", {})
        if not isinstance(bindings_raw, Mapping):
            bindings_raw = {}
        bindings = tuple(
            (channel, ExportChannelBinding.from_dict(bindings_raw.get(channel)))
            for channel in ("R", "G", "B", "A")
        )
        return cls(
            name=str(raw.get("name", f"Output {ordinal}")).strip() or f"Output {ordinal}",
            map_name=str(raw.get("map_name", f"Map{ordinal}")).strip() or f"Map{ordinal}",
            filename=str(raw.get("filename", "")),
            format_name=format_name,
            bit_depth=bit_depth,
            channels=channels,
            colour_encoding=encoding,
            bindings=bindings,
            always_export=bool(raw.get("always_export", False)),
            description=str(raw.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class ExportTemplate:
    name: str
    files: tuple[ExportFileTemplate, ...]
    description: str = ""
    template_id: str = ""
    author: str = ""
    asset_version: str = "1.0.0"
    target: str = "Generic"
    built_in: bool = False
    version: int = EXPORT_TEMPLATE_FORMAT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "vfx-texture-lab-export-template",
            "version": int(self.version),
            "name": self.name,
            "description": self.description,
            "template_id": self.template_id,
            "author": self.author,
            "asset_version": self.asset_version,
            "target": self.target,
            "files": [file.to_dict() for file in self.files],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ExportTemplate":
        raw = dict(data or {})
        files_raw = raw.get("files", [])
        if not isinstance(files_raw, list):
            files_raw = []
        return cls(
            name=str(raw.get("name", CUSTOM_TEMPLATE_NAME)).strip() or CUSTOM_TEMPLATE_NAME,
            description=str(raw.get("description", "")),
            template_id=str(raw.get("template_id", "custom")),
            author=str(raw.get("author", "")),
            asset_version=str(raw.get("asset_version", raw.get("template_version", "1.0.0"))) or "1.0.0",
            target=str(raw.get("target", "Generic")) or "Generic",
            version=max(1, int(raw.get("version", EXPORT_TEMPLATE_FORMAT_VERSION))),
            files=tuple(
                ExportFileTemplate.from_dict(item, ordinal=index)
                for index, item in enumerate(files_raw, start=1)
                if isinstance(item, Mapping)
            ),
        )


def _binding(
    source: str,
    component: str = "Red",
    *,
    invert: bool = False,
    constant: float = 0.0,
    normal_y: bool = False,
) -> ExportChannelBinding:
    return ExportChannelBinding(source, component, invert, constant, normal_y)


def _file(
    name: str,
    map_name: str,
    channels: str,
    encoding: str,
    bindings: Mapping[str, ExportChannelBinding],
    *,
    bit_depth: str,
    format_name: str = "Texture-set setting",
    description: str = "",
) -> ExportFileTemplate:
    merged = {
        "R": _binding("Constant", constant=0.0),
        "G": _binding("Constant", constant=0.0),
        "B": _binding("Constant", constant=0.0),
        "A": _binding("Constant", constant=1.0),
    }
    merged.update(bindings)
    return ExportFileTemplate(
        name=name,
        map_name=map_name,
        channels=channels,
        colour_encoding=encoding,
        bit_depth=bit_depth,
        format_name=format_name,
        bindings=tuple(merged.items()),
        description=description,
    )


def _common_files() -> tuple[ExportFileTemplate, ...]:
    return (
        _file(
            "Base Colour",
            "BaseColor",
            "RGBA",
            "sRGB",
            {
                "R": _binding("Base Colour", "Red"),
                "G": _binding("Base Colour", "Green"),
                "B": _binding("Base Colour", "Blue"),
                "A": _binding("Opacity", "Red"),
            },
            bit_depth="Colour setting",
            description="Base colour with semantic material opacity in alpha.",
        ),
        _file(
            "Normal",
            "Normal",
            "RGB",
            "Linear",
            {
                "R": _binding("Normal", "Red"),
                "G": _binding("Normal", "Green", normal_y=True),
                "B": _binding("Normal", "Blue"),
            },
            bit_depth="8",
            description="Tangent-space normal using the output node's OpenGL/DirectX convention.",
        ),
        _file(
            "Emissive",
            "Emissive",
            "RGB",
            "sRGB",
            {
                "R": _binding("Emissive", "Red"),
                "G": _binding("Emissive", "Green"),
                "B": _binding("Emissive", "Blue"),
            },
            bit_depth="Colour setting",
        ),
        _file(
            "Opacity",
            "Opacity",
            "Grayscale",
            "Linear",
            {"R": _binding("Opacity", "Red")},
            bit_depth="8",
        ),
        _file(
            "Height",
            "Height",
            "Grayscale",
            "Linear",
            {"R": _binding("Height", "Red")},
            bit_depth="16",
            format_name="Height setting",
        ),
    )


def _scalar_file(name: str, map_name: str, source: str) -> ExportFileTemplate:
    return _file(
        name,
        map_name,
        "Grayscale",
        "Linear",
        {"R": _binding(source, "Red")},
        bit_depth="Scalar setting",
    )


_GENERIC = ExportTemplate(
    name="Generic PBR Separate",
    template_id="builtin.generic_pbr_separate",
    built_in=True,
    description="Separate colour, normal, height and scalar PBR maps.",
    author="VFX Texture Lab", asset_version="1.0.0", target="Generic PBR",
    files=_common_files()
    + (
        _scalar_file("Ambient Occlusion", "AO", "Ambient Occlusion"),
        _scalar_file("Roughness", "Roughness", "Roughness"),
        _scalar_file("Metallic", "Metallic", "Metallic"),
        _scalar_file("Specular Level", "Specular", "Specular Level"),
    ),
)

_UNREAL = ExportTemplate(
    name="Unreal ORM",
    template_id="builtin.unreal_orm",
    built_in=True,
    description="Unreal-friendly separate colour/normal maps with AO, Roughness and Metallic packed into RGB.",
    author="VFX Texture Lab", asset_version="1.0.0", target="Unreal Engine",
    files=_common_files()
    + (
        _file(
            "Occlusion Roughness Metallic",
            "ORM",
            "RGB",
            "Linear",
            {
                "R": _binding("Ambient Occlusion", "Red"),
                "G": _binding("Roughness", "Red"),
                "B": _binding("Metallic", "Red"),
            },
            bit_depth="8",
        ),
    ),
)

_UNITY = ExportTemplate(
    name="Unity HDRP Mask Map",
    template_id="builtin.unity_hdrp_mask",
    built_in=True,
    description="Unity HDRP Mask Map: Metallic R, AO G, Detail Mask B, Smoothness A.",
    author="VFX Texture Lab", asset_version="1.0.0", target="Unity HDRP",
    files=_common_files()
    + (
        _file(
            "HDRP Mask Map",
            "MaskMap",
            "RGBA",
            "Linear",
            {
                "R": _binding("Metallic", "Red"),
                "G": _binding("Ambient Occlusion", "Red"),
                "B": _binding("Constant", constant=1.0),
                "A": _binding("Roughness", "Red", invert=True),
            },
            bit_depth="8",
        ),
    ),
)

_GODOT = ExportTemplate(
    name="Godot ORM",
    template_id="builtin.godot_orm",
    built_in=True,
    description="Godot ORM texture: AO R, Roughness G and Metallic B.",
    author="VFX Texture Lab", asset_version="1.0.0", target="Godot",
    files=_common_files()
    + (
        _file(
            "Occlusion Roughness Metallic",
            "ORM",
            "RGB",
            "Linear",
            {
                "R": _binding("Ambient Occlusion", "Red"),
                "G": _binding("Roughness", "Red"),
                "B": _binding("Metallic", "Red"),
            },
            bit_depth="8",
        ),
    ),
)

_VFX_MASKS = ExportTemplate(
    name="VFX RGBA Masks",
    template_id="builtin.vfx_rgba_masks",
    built_in=True,
    description="Artist-friendly starter pack for real-time VFX: Opacity, Emissive luminance, Height and AO.",
    author="VFX Texture Lab", asset_version="1.0.0", target="Real-time VFX",
    files=(
        _file(
            "VFX Packed Masks",
            "Masks",
            "RGBA",
            "Linear",
            {
                "R": _binding("Opacity", "Red"),
                "G": _binding("Emissive", "Luminance"),
                "B": _binding("Height", "Red"),
                "A": _binding("Ambient Occlusion", "Red"),
            },
            bit_depth="8",
        ),
    ),
)

BUILTIN_EXPORT_TEMPLATES: dict[str, ExportTemplate] = {
    template.name: template
    for template in (_GENERIC, _UNREAL, _UNITY, _GODOT, _VFX_MASKS)
}

LEGACY_TEMPLATE_ALIASES = {
    "Separate PBR Maps": "Generic PBR Separate",
}


def builtin_template_names() -> tuple[str, ...]:
    return tuple(BUILTIN_EXPORT_TEMPLATES)


def builtin_template(name: str) -> ExportTemplate:
    resolved = LEGACY_TEMPLATE_ALIASES.get(str(name), str(name))
    return BUILTIN_EXPORT_TEMPLATES.get(resolved, _GENERIC)


def effective_export_template(parameters: Mapping[str, Any]) -> ExportTemplate:
    selected = LEGACY_TEMPLATE_ALIASES.get(
        str(parameters.get("export_preset", "Generic PBR Separate")),
        str(parameters.get("export_preset", "Generic PBR Separate")),
    )
    if selected == CUSTOM_TEMPLATE_NAME:
        raw = parameters.get("_custom_export_template")
        if isinstance(raw, Mapping):
            template = ExportTemplate.from_dict(raw)
            if template.files:
                return template
    return builtin_template(selected)


def template_summary(template: ExportTemplate) -> str:
    count = len(template.files)
    return f"{count} file{'s' if count != 1 else ''} · {template.description}".strip(" ·")


def clone_as_custom(template: ExportTemplate, *, name: str | None = None) -> ExportTemplate:
    data = deepcopy(template.to_dict())
    data["name"] = str(name or f"Custom {template.name}")
    data["template_id"] = "custom"
    return ExportTemplate.from_dict(data)


def referenced_sources(file: ExportFileTemplate) -> tuple[str, ...]:
    seen: list[str] = []
    for channel in file.active_channels():
        source = file.binding(channel).source
        if source != "Constant" and source not in seen:
            seen.append(source)
    return tuple(seen)


def validate_export_template(template: ExportTemplate) -> tuple[tuple[str, ...], tuple[str, ...]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not template.files:
        errors.append("The template has no output files.")
        return tuple(errors), tuple(warnings)

    names: set[str] = set()
    map_names: set[str] = set()
    for index, file in enumerate(template.files, start=1):
        prefix = file.name or f"Output {index}"
        if not file.name.strip():
            errors.append(f"Output {index} has no display name.")
        if not file.map_name.strip():
            errors.append(f"{prefix} has no map token.")
        folded = file.name.casefold()
        if folded in names:
            warnings.append(f"Two template files are both named ‘{file.name}’.")
        names.add(folded)
        map_folded = file.map_name.casefold()
        if map_folded in map_names:
            warnings.append(f"Two template files use the same {{map}} value ‘{file.map_name}’.")
        map_names.add(map_folded)
        if file.filename.strip():
            try:
                fields = {field for _literal, field, _format, _conversion in Formatter().parse(file.filename) if field}
            except ValueError as exc:
                errors.append(f"{prefix}: invalid file-name template ({exc}).")
                fields = set()
            unsupported = sorted(fields - {"set", "map", "output", "width", "height", "graph", "version", "target", "profile"})
            if unsupported:
                errors.append(f"{prefix}: unsupported file-name token(s): {', '.join(unsupported)}.")
        if file.format_name == "R16" and file.channels != "Grayscale":
            errors.append(f"{prefix}: Raw R16 requires Grayscale output.")
        if file.format_name == "TGA" and file.bit_depth == "16":
            warnings.append(f"{prefix}: TGA is written as 8-bit.")
        if file.colour_encoding == "sRGB" and all(
            file.binding(channel).source in {
                "Height", "Ambient Occlusion", "Metallic", "Roughness", "Specular Level", "Opacity", "Constant"
            }
            for channel in file.active_channels()
        ):
            warnings.append(f"{prefix}: scalar/data channels are being encoded as sRGB.")
        if not referenced_sources(file) and not file.always_export:
            warnings.append(f"{prefix}: contains only constants and will normally be skipped.")
    return tuple(errors), tuple(dict.fromkeys(warnings))


def source_labels() -> tuple[tuple[str, ExportChannelBinding], ...]:
    """Choices used by the editor, ordered for artists rather than internals."""
    choices: list[tuple[str, ExportChannelBinding]] = [
        ("Constant 0", _binding("Constant", constant=0.0)),
        ("Constant 1", _binding("Constant", constant=1.0)),
    ]
    colour_sources = {"Base Colour", "Emissive", "Normal"}
    for source in MATERIAL_INPUTS:
        if source in colour_sources:
            for component in ("Red", "Green", "Blue", "Alpha", "Luminance"):
                label = f"{source} · {component}"
                normal_y = source == "Normal" and component == "Green"
                if normal_y:
                    label += " / Y convention"
                choices.append((label, _binding(source, component, normal_y=normal_y)))
        else:
            choices.append((source, _binding(source, "Red")))
    return tuple(choices)
