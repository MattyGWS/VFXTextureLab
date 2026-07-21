from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from .document import DocumentSettings
    from .engine.evaluator import GraphSnapshot
from .exporting import ExportOptions, export_extension
from .export_templates import (
    CUSTOM_TEMPLATE_NAME,
    ExportChannelBinding,
    ExportTemplate,
    builtin_template,
    effective_export_template,
    referenced_sources,
    validate_export_template,
)
from .material_graph import MATERIAL_INPUTS, material_channel_present, resolve_material_producer
from .export_profiles import ExportProfileSet, ExportTarget, NODE_TEMPLATE, OUTPUT_SETTING

IMAGE_OUTPUT_PRESETS = (
    "Auto from data type",
    "Colour / sRGB",
    "Linear Data",
    "Normal Map (OpenGL +Y)",
    "Normal Map (DirectX -Y)",
    "Custom",
)

TEXTURE_SET_PRESETS = (
    "Generic PBR Separate",
    "Unreal ORM",
    "Unity HDRP Mask Map",
    "Godot ORM",
    "VFX RGBA Masks",
    CUSTOM_TEMPLATE_NAME,
)

RESOLUTION_OPTIONS = (
    "Document",
    "256 × 256",
    "512 × 512",
    "1024 × 1024",
    "2048 × 2048",
    "4096 × 4096",
    "8192 × 8192",
    "Custom",
)


@dataclass(frozen=True, slots=True)
class ExportSource:
    node_uid: str
    output_name: str = "Image"
    channel: str = "Luminance"
    invert: bool = False


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    owner_uid: str
    owner_name: str
    label: str
    filename: str
    width: int
    height: int
    options: ExportOptions
    operation: str = "image"
    sources: tuple[tuple[str, ExportSource], ...] = ()
    channel_bindings: tuple[tuple[str, ExportChannelBinding], ...] = ()
    normal_directx: bool = False
    warnings: tuple[str, ...] = ()
    target_name: str = ""
    profile_name: str = ""
    relative_directory: str = ""

    @property
    def relative_path(self) -> str:
        folder = str(self.relative_directory or "").strip("/\\")
        return f"{folder}/{self.filename}" if folder else self.filename

    @property
    def extension(self) -> str:
        return export_extension(self.options.format_name)

    def source(self, name: str) -> ExportSource | None:
        for candidate, source in self.sources:
            if candidate == name:
                return source
        return None


def safe_file_stem(value: str, fallback: str = "output") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._")
    return text or fallback



def filename_with_extension(stem: str, format_name: str) -> str:
    extension = export_extension(format_name)
    path = Path(str(stem))
    if path.suffix.lower() in {".png", ".tga", ".r16"}:
        stem = path.with_suffix("").name
    return f"{stem}{extension}"

def output_resolution(parameters: Mapping[str, Any], document: DocumentSettings) -> tuple[int, int]:
    mode = str(parameters.get("export_resolution", "Document"))
    if mode == "Document":
        return int(document.width), int(document.height)
    if mode == "Custom":
        width = max(1, min(int(parameters.get("export_width", document.width)), 16384))
        height = max(1, min(int(parameters.get("export_height", document.height)), 16384))
        return width, height
    match = re.match(r"\s*(\d+)\s*[×x]\s*(\d+)\s*", mode)
    if match:
        return max(1, int(match.group(1))), max(1, int(match.group(2)))
    return int(document.width), int(document.height)


def _render_filename(
    template: str, *, output: str, set_name: str, map_name: str, width: int, height: int,
    graph_name: str = "", graph_version: str = "", target_name: str = "", profile_name: str = "",
) -> str:
    try:
        rendered = str(template or "{output}").format(
            output=output,
            set=set_name,
            map=map_name,
            width=width,
            height=height,
            graph=graph_name or set_name,
            version=graph_version or "1.0.0",
            target=target_name or "Current",
            profile=profile_name or "Current",
        )
    except (KeyError, ValueError):
        rendered = output
    return safe_file_stem(rendered, safe_file_stem(output))


def _render_subfolder(
    template: str, *, graph_name: str, graph_version: str, target_name: str, profile_name: str,
    output_name: str,
) -> str:
    try:
        rendered = str(template or "").format(
            graph=graph_name or output_name,
            version=graph_version or "1.0.0",
            target=target_name or "Current",
            profile=profile_name or "Current",
            output=output_name,
            set=output_name,
        )
    except (KeyError, ValueError):
        rendered = target_name or ""
    parts: list[str] = []
    for raw in str(rendered).replace("\\", "/").split("/"):
        text = raw.strip()
        if not text or text in {".", ".."}:
            continue
        parts.append(safe_file_stem(text, "target"))
    return "/".join(parts)


def _image_options(parameters: Mapping[str, Any], data_kind: str) -> ExportOptions:
    preset = str(parameters.get("export_preset", "Auto from data type"))
    kind = str(data_kind or "grayscale")
    if preset == "Colour / sRGB":
        return ExportOptions("PNG", 8, "RGBA", "Luminance", "sRGB")
    if preset == "Linear Data":
        return ExportOptions("PNG", 16, "Grayscale" if kind == "grayscale" else "RGBA", "Luminance", "Linear")
    if preset == "Normal Map (OpenGL +Y)":
        return ExportOptions("PNG", 8, "RGB", "Luminance", "Linear", flip_green=False)
    if preset == "Normal Map (DirectX -Y)":
        return ExportOptions("PNG", 8, "RGB", "Luminance", "Linear", flip_green=True)
    if preset == "Custom":
        channels = str(parameters.get("export_channels", "Auto"))
        if channels == "Auto":
            channels = "Grayscale" if kind == "grayscale" else ("RGB" if kind == "vector" else "RGBA")
        encoding = str(parameters.get("export_encoding", "Auto"))
        if encoding == "Auto":
            encoding = "sRGB" if kind == "color" else "Linear"
        format_name = str(parameters.get("export_format", "PNG"))
        bit_depth = int(str(parameters.get("export_bit_depth", "8")).split()[0])
        source_channel = str(parameters.get("export_source_channel", "Luminance"))
        if format_name == "TGA":
            bit_depth = 8
        elif format_name == "R16":
            bit_depth = 16
            channels = "Grayscale"
            encoding = "Linear"
        return ExportOptions(
            format_name=format_name,
            bit_depth=bit_depth,
            channels=channels,
            source_channel=source_channel,
            colour_encoding=encoding,
            invert=bool(parameters.get("export_invert", False)),
            flip_green=bool(parameters.get("export_flip_green", False)),
        )
    # Auto follows semantic graph data rather than channel count.
    if kind == "color":
        return ExportOptions("PNG", 8, "RGBA", "Luminance", "sRGB")
    if kind == "vector":
        return ExportOptions("PNG", 8, "RGB", "Luminance", "Linear")
    return ExportOptions("PNG", 16, "Grayscale", "Luminance", "Linear")


def _connected_source(snapshot: GraphSnapshot, owner_uid: str, input_name: str) -> ExportSource | None:
    source = snapshot.inputs.get((owner_uid, input_name))
    if source is None:
        return None
    return ExportSource(str(source[0]), str(source[1] or "Image"))


def _connected_material(snapshot: GraphSnapshot, owner_uid: str) -> tuple[str, Any] | None:
    source = snapshot.inputs.get((owner_uid, "Material"))
    if source is None:
        return None
    material_uid = resolve_material_producer(snapshot, str(source[0]))
    if material_uid is None:
        return None
    material_node = snapshot.nodes.get(material_uid)
    return (material_uid, material_node) if material_node is not None else None


def image_output_artifacts(
    snapshot: GraphSnapshot, uid: str, document: DocumentSettings, *,
    graph_name: str = "", graph_version: str = "", profile_name: str = "",
) -> list[ExportArtifact]:
    node = snapshot.nodes[uid]
    parameters = node.parameters
    name = str(parameters.get("name", "Output")).strip() or "Output"
    if (uid, "Image") not in snapshot.inputs:
        return []
    width, height = output_resolution(parameters, document)
    options = _image_options(parameters, node.resolved_kind)
    stem = _render_filename(
        str(parameters.get("export_filename", "{output}")),
        output=name,
        set_name=name,
        map_name=name,
        width=width,
        height=height,
        graph_name=graph_name,
        graph_version=graph_version,
        profile_name=profile_name,
    )
    return [
        ExportArtifact(
            owner_uid=uid,
            owner_name=name,
            label=name,
            filename=filename_with_extension(stem, options.format_name),
            width=width,
            height=height,
            options=options,
            sources=(("Image", ExportSource(uid, "Image")),),
        )
    ]


def _target_parameters(parameters: Mapping[str, Any], target: ExportTarget | None) -> dict[str, Any]:
    result = dict(parameters)
    if target is None:
        return result
    overrides = {
        "export_resolution": target.resolution,
        "normal_convention": target.normal_convention,
        "texture_format": target.texture_format,
        "colour_bit_depth": target.colour_bit_depth,
        "data_bit_depth": target.data_bit_depth,
        "height_format": target.height_format,
    }
    for name, value in overrides.items():
        if value != OUTPUT_SETTING:
            result[name] = value
    return result


def _target_template(parameters: Mapping[str, Any], target: ExportTarget | None) -> ExportTemplate:
    if target is None or target.template_name == NODE_TEMPLATE:
        return effective_export_template(parameters)
    if target.custom_template:
        template = ExportTemplate.from_dict(target.custom_template)
        if template.files:
            return template
    return builtin_template(target.template_name)


def texture_set_artifacts(
    snapshot: GraphSnapshot, uid: str, document: DocumentSettings, *,
    target: ExportTarget | None = None, graph_name: str = "", graph_version: str = "",
    profile_name: str = "",
) -> list[ExportArtifact]:
    node = snapshot.nodes[uid]
    p = _target_parameters(node.parameters, target)
    set_name = str(p.get("name", "Material")).strip() or "Material"
    width, height = output_resolution(p, document)
    fallback_filename = str(p.get("export_filename", "{set}_{map}"))
    colour_depth = int(str(p.get("colour_bit_depth", "8")).split()[0])
    data_depth = int(str(p.get("data_bit_depth", "16")).split()[0])
    normal_directx = str(p.get("normal_convention", "OpenGL (+Y)")) == "DirectX (-Y)"
    texture_format = str(p.get("texture_format", "PNG"))
    material_ref = _connected_material(snapshot, uid)
    if material_ref is None:
        return []
    material_uid, _material_node = material_ref

    sources = {
        name: (
            ExportSource(material_uid, name)
            if material_channel_present(snapshot, material_uid, name)
            else None
        )
        for name in MATERIAL_INPUTS
    }

    export_template = _target_template(p, target)
    template_errors, template_warnings = validate_export_template(export_template)
    if template_errors:
        return []
    target_name = target.name if target is not None else ""
    relative_directory = _render_subfolder(
        target.subfolder if target is not None else "",
        graph_name=graph_name, graph_version=graph_version, target_name=target_name,
        profile_name=profile_name, output_name=set_name,
    )

    artifacts: list[ExportArtifact] = []
    for file in export_template.files:
        requested = referenced_sources(file)
        present = tuple(name for name in requested if sources.get(name) is not None)
        if not present and not file.always_export:
            continue

        format_name = file.format_name
        if format_name == "Texture-set setting":
            format_name = texture_format
        elif format_name == "Height setting":
            format_name = "R16" if str(p.get("height_format", "PNG 16-bit")) == "Raw R16" else "PNG"
        if format_name == "R16":
            channels = "Grayscale"
            bit_depth = 16
            colour_encoding = "Linear"
        else:
            channels = file.channels
            if file.bit_depth == "Colour setting":
                bit_depth = colour_depth
            elif file.bit_depth == "Scalar setting":
                bit_depth = data_depth
            else:
                bit_depth = int(file.bit_depth)
            if format_name == "TGA":
                bit_depth = 8
            colour_encoding = file.colour_encoding

        authored_filename = file.filename.strip() or fallback_filename
        stem = _render_filename(
            authored_filename, output=set_name, set_name=set_name, map_name=file.map_name,
            width=width, height=height, graph_name=graph_name, graph_version=graph_version,
            target_name=target_name, profile_name=profile_name,
        )
        artifact_sources = tuple((name, sources[name]) for name in present if sources[name] is not None)
        local_warnings = list(template_warnings)
        if "Height" in requested and bit_depth == 8:
            local_warnings.append(f"{file.name}: Height is being exported at 8-bit precision.")
        if file.colour_encoding == "sRGB" and channels == "Grayscale":
            local_warnings.append(f"{file.name}: grayscale output is encoded as sRGB.")
        artifacts.append(
            ExportArtifact(
                owner_uid=uid, owner_name=set_name,
                label=f"{target_name + ' · ' if target_name else ''}{set_name} · {file.map_name}",
                filename=filename_with_extension(stem, format_name), width=width, height=height,
                options=ExportOptions(format_name, bit_depth, channels, "Red", colour_encoding),
                operation="template_pack", sources=artifact_sources,
                channel_bindings=tuple((channel, file.binding(channel)) for channel in file.active_channels()),
                normal_directx=normal_directx, warnings=tuple(dict.fromkeys(local_warnings)),
                target_name=target_name, profile_name=profile_name, relative_directory=relative_directory,
            )
        )
    return artifacts


def build_export_artifacts(
    snapshot: GraphSnapshot, node_uids: list[str], document: DocumentSettings, *,
    graph_name: str = "", graph_version: str = "", profile_name: str = "",
) -> list[ExportArtifact]:
    artifacts: list[ExportArtifact] = []
    for uid in node_uids:
        node = snapshot.nodes.get(uid)
        if node is None:
            continue
        if node.definition.type_id == "output.image":
            artifacts.extend(image_output_artifacts(
                snapshot, uid, document, graph_name=graph_name, graph_version=graph_version,
                profile_name=profile_name,
            ))
        elif node.definition.type_id == "output.texture_set":
            artifacts.extend(texture_set_artifacts(
                snapshot, uid, document, graph_name=graph_name, graph_version=graph_version,
                profile_name=profile_name,
            ))
    return artifacts


def build_multi_target_artifacts(
    snapshot: GraphSnapshot, node_uids: list[str], document: DocumentSettings,
    profile: ExportProfileSet, *, graph_name: str = "", graph_version: str = "",
) -> list[ExportArtifact]:
    artifacts: list[ExportArtifact] = []
    enabled_targets = tuple(target for target in profile.targets if target.enabled)
    for uid in node_uids:
        node = snapshot.nodes.get(uid)
        if node is None:
            continue
        if node.definition.type_id == "output.image":
            # Single Image Output already fully describes its one file. It is
            # emitted once alongside all selected texture-set production targets.
            artifacts.extend(image_output_artifacts(
                snapshot, uid, document, graph_name=graph_name, graph_version=graph_version,
                profile_name=profile.name,
            ))
        elif node.definition.type_id == "output.texture_set":
            for target in enabled_targets:
                artifacts.extend(texture_set_artifacts(
                    snapshot, uid, document, target=target, graph_name=graph_name,
                    graph_version=graph_version, profile_name=profile.name,
                ))
    return artifacts


def resolve_destination(directory: Path, filename: str, collision: str, reserved: set[str]) -> Path | None:
    path = directory / Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path).casefold()
    if collision == "Replace existing" and key not in reserved:
        reserved.add(key)
        return path
    if collision == "Skip existing" and (path.exists() or key in reserved):
        return None
    if not path.exists() and key not in reserved:
        reserved.add(key)
        return path
    stem, suffix = path.stem, path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        candidate_key = str(candidate).casefold()
        if not candidate.exists() and candidate_key not in reserved:
            reserved.add(candidate_key)
            return candidate
        counter += 1


def export_filename_conflicts(artifacts: list[ExportArtifact]) -> dict[str, tuple[ExportArtifact, ...]]:
    """Return case-insensitive filename collisions inside one export request.

    Existing files on disk are deliberately not included here. This only
    identifies two graph output endpoints that would target the same path in
    the same batch, which is the situation where blindly replacing would let
    one output overwrite another.
    """
    groups: dict[str, list[ExportArtifact]] = {}
    display_names: dict[str, str] = {}
    for artifact in artifacts:
        key = str(artifact.relative_path).casefold()
        groups.setdefault(key, []).append(artifact)
        display_names.setdefault(key, artifact.relative_path)
    return {
        display_names[key]: tuple(group)
        for key, group in groups.items()
        if len(group) > 1
    }


def disambiguated_export_filenames(artifacts: list[ExportArtifact]) -> list[str]:
    """Return stable filenames for a batch without inter-node overwrites.

    Normal, non-conflicting exports keep their authored filename exactly. When
    two selected output nodes request the same filename, each conflicting file
    receives a deterministic suffix derived from the output node's public name
    and stable UID. Repeating the same export therefore overwrites the same
    files instead of creating an ever-growing _2, _3, ... sequence.
    """
    resolved = [artifact.relative_path for artifact in artifacts]
    by_key: dict[str, list[int]] = {}
    for index, artifact in enumerate(artifacts):
        by_key.setdefault(str(artifact.relative_path).casefold(), []).append(index)

    for indices in by_key.values():
        if len(indices) <= 1:
            continue
        owner_name_counts: dict[str, int] = {}
        owner_uid_counts: dict[str, int] = {}
        for index in indices:
            artifact = artifacts[index]
            owner_name_counts[artifact.owner_name.casefold()] = owner_name_counts.get(artifact.owner_name.casefold(), 0) + 1
            owner_uid_counts[artifact.owner_uid] = owner_uid_counts.get(artifact.owner_uid, 0) + 1

        used: set[str] = set()
        for ordinal, index in enumerate(indices, start=1):
            artifact = artifacts[index]
            path = Path(artifact.relative_path)
            owner_tag = safe_file_stem(artifact.owner_name, "output")
            if owner_name_counts.get(artifact.owner_name.casefold(), 0) > 1:
                uid_tag = re.sub(r"[^A-Za-z0-9]+", "", artifact.owner_uid)[:8] or f"node{ordinal}"
                owner_tag = f"{owner_tag}_{uid_tag}"
            if owner_uid_counts.get(artifact.owner_uid, 0) > 1:
                detail = artifact.label.rsplit("·", 1)[-1].strip()
                owner_tag = f"{owner_tag}_{safe_file_stem(detail, f'map{ordinal}')}"

            candidate = str(path.with_name(f"{path.stem}__{owner_tag}{path.suffix}"))
            candidate_key = candidate.casefold()
            counter = 2
            while candidate_key in used:
                candidate = str(path.with_name(f"{path.stem}__{owner_tag}_{counter}{path.suffix}"))
                candidate_key = candidate.casefold()
                counter += 1
            used.add(candidate_key)
            resolved[index] = candidate
    return resolved
