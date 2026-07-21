from __future__ import annotations

import base64
import binascii
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .graph_assets import GRAPH_ASSET_FORMAT, GRAPH_INSTANCE_TYPE, source_revision


class SelfContainedGraphError(ValueError):
    """Raised when a graph cannot be converted into one portable file."""

    def __init__(self, message: str, *, chain: list[str] | None = None) -> None:
        self.chain = [str(value) for value in (chain or []) if str(value)]
        prefix = "\n→ ".join(self.chain)
        super().__init__(f"{prefix}\n{message}" if prefix else str(message))


@dataclass(slots=True)
class SelfContainedExportReport:
    graph_instances: int = 0
    images: int = 0
    recovered_graphs: int = 0
    recovered_images: int = 0
    already_embedded_graphs: int = 0
    already_embedded_images: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            f"Nested graph instances embedded: {self.graph_instances}",
            f"Images embedded: {self.images}",
        ]
        if self.recovered_graphs:
            lines.append(f"Graph sources recovered from cached revisions: {self.recovered_graphs}")
        if self.recovered_images:
            lines.append(f"Images recovered from embedded bytes: {self.recovered_images}")
        return lines


def resolve_authored_path(path_value: str | Path, owner_graph_path: str | Path | None) -> Path:
    """Resolve a stored resource path relative to the graph that owns it."""

    text = str(path_value or "").strip()
    if not text:
        raise ValueError("The resource has no source path.")
    path = Path(text).expanduser()
    if path.is_absolute():
        return path.resolve()
    if owner_graph_path is None:
        raise ValueError(
            f"Relative resource path '{text}' cannot be resolved because its owning graph has not been saved."
        )
    owner = Path(owner_graph_path).expanduser()
    return (owner.parent / path).resolve()


def _graph_label(data: Mapping[str, Any], fallback: str = "Graph") -> str:
    metadata = data.get("graph_asset")
    if isinstance(metadata, Mapping):
        name = str(metadata.get("name", "")).strip()
        if name:
            return name
    return str(fallback or "Graph")


def _decode_embedded_image(parameters: Mapping[str, Any], *, chain: list[str]) -> bytes | None:
    encoded = str(parameters.get("_embedded_data", "") or "").strip()
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SelfContainedGraphError(
            "The stored embedded image data is damaged and cannot be decoded.", chain=chain
        ) from exc


def _read_graph(path: Path, *, chain: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SelfContainedGraphError(
            f"Could not read linked graph source:\n{path}\n{exc}", chain=chain
        ) from exc
    if not isinstance(payload, dict) or str(payload.get("format", "")) != GRAPH_ASSET_FORMAT:
        raise SelfContainedGraphError(
            f"The linked source is not a valid VFX Texture Lab graph:\n{path}", chain=chain
        )
    return payload


def _source_key(data: Mapping[str, Any], source_path: Path | None) -> str:
    if source_path is not None:
        return f"path:{source_path}"
    return f"embedded:{source_revision(data)}"


def _child_graph_source(
    parameters: Mapping[str, Any],
    *,
    owner_path: Path | None,
    chain: list[str],
    report: SelfContainedExportReport,
) -> tuple[dict[str, Any], Path | None, bool]:
    mode = str(parameters.get("_asset_mode", "Linked") or "Linked")
    source_text = str(parameters.get("_asset_path", "") or "").strip()
    embedded = parameters.get("_asset_embedded_graph")
    cached = parameters.get("_asset_cached_graph")
    source_path: Path | None = None
    if source_text:
        try:
            source_path = resolve_authored_path(source_text, owner_path)
        except ValueError as exc:
            if not isinstance(cached, Mapping) and not isinstance(embedded, Mapping):
                raise SelfContainedGraphError(str(exc), chain=chain) from exc

    if mode == "Session":
        if isinstance(cached, Mapping):
            return deepcopy(dict(cached)), source_path, False
        if isinstance(embedded, Mapping):
            return deepcopy(dict(embedded)), source_path, False
        raise SelfContainedGraphError(
            "The open Graph Instance has no serialised live revision.", chain=chain
        )

    if mode == "Embedded":
        if isinstance(embedded, Mapping):
            report.already_embedded_graphs += 1
            return deepcopy(dict(embedded)), source_path, False
        if isinstance(cached, Mapping):
            report.recovered_graphs += 1
            report.warnings.append(f"{' → '.join(chain)} used its cached graph revision.")
            return deepcopy(dict(cached)), source_path, True
        raise SelfContainedGraphError(
            "The embedded Graph Instance contains no graph data.", chain=chain
        )

    if source_path is not None and source_path.is_file():
        try:
            return _read_graph(source_path, chain=chain), source_path, False
        except SelfContainedGraphError:
            if not isinstance(cached, Mapping):
                raise
            report.recovered_graphs += 1
            report.warnings.append(
                f"{' → '.join(chain)} could not read its linked source and used the last-known-good cache."
            )
            return deepcopy(dict(cached)), source_path, True

    if isinstance(cached, Mapping):
        report.recovered_graphs += 1
        source_description = str(source_path or source_text or "missing source")
        report.warnings.append(
            f"{' → '.join(chain)} recovered a missing linked source from cache: {source_description}"
        )
        return deepcopy(dict(cached)), source_path, True
    if isinstance(embedded, Mapping):
        report.recovered_graphs += 1
        return deepcopy(dict(embedded)), source_path, True
    raise SelfContainedGraphError(
        f"The linked graph source is missing and no cached revision is available:\n{source_path or source_text or 'No path'}",
        chain=chain,
    )


def _embed_graph(
    data: dict[str, Any],
    *,
    owner_path: Path | None,
    report: SelfContainedExportReport,
    chain: list[str],
    ancestry: set[str],
    depth: int,
) -> dict[str, Any]:
    if depth > 64:
        raise SelfContainedGraphError(
            "Graph nesting exceeded the safety limit of 64 levels.", chain=chain
        )
    result = deepcopy(data)
    if str(result.get("format", "")) != GRAPH_ASSET_FORMAT:
        raise SelfContainedGraphError(
            "This data is not a VFX Texture Lab graph.", chain=chain
        )
    key = _source_key(result, owner_path)
    if key in ancestry:
        raise SelfContainedGraphError(
            "A recursive graph dependency was detected.", chain=chain
        )
    ancestry = set(ancestry)
    ancestry.add(key)

    for node_data in result.get("nodes", ()): 
        if not isinstance(node_data, dict):
            continue
        parameters = node_data.setdefault("parameters", {})
        type_id = str(node_data.get("type", ""))
        definition = node_data.get("definition")
        definition_name = str(definition.get("name", "")) if isinstance(definition, Mapping) else ""
        node_name = str(
            parameters.get("name")
            or definition_name
            or type_id
            or "Node"
        )
        node_chain = [*chain, node_name]

        if type_id == GRAPH_INSTANCE_TYPE:
            interface = parameters.get("_asset_interface")
            if isinstance(interface, Mapping):
                node_name = str(interface.get("name") or node_name)
                node_chain = [*chain, node_name]
            child, child_owner_path, recovered = _child_graph_source(
                parameters,
                owner_path=owner_path,
                chain=node_chain,
                report=report,
            )
            child_label = _graph_label(child, node_name)
            child_chain = [*chain, child_label]
            embedded_child = _embed_graph(
                child,
                owner_path=child_owner_path,
                report=report,
                chain=child_chain,
                ancestry=ancestry,
                depth=depth + 1,
            )
            report.graph_instances += 1
            original_name = ""
            source_text = str(parameters.get("_asset_path", "") or "").strip()
            if source_text:
                original_name = Path(source_text).name
            parameters["_asset_mode"] = "Embedded"
            parameters["_asset_path"] = ""
            parameters["_asset_embedded_graph"] = deepcopy(embedded_child)
            parameters["_asset_cached_graph"] = deepcopy(embedded_child)
            parameters["_asset_revision"] = source_revision(embedded_child)
            parameters["_asset_status"] = (
                "Embedded · recovered cached revision" if recovered else "Embedded · self-contained"
            )
            parameters["_asset_mtime_ns"] = 0
            parameters.pop("_asset_session_uid", None)
            if original_name:
                parameters["_asset_original_name"] = original_name
            if recovered:
                parameters["_asset_recovered_from_cache"] = True
            else:
                parameters.pop("_asset_recovered_from_cache", None)
            continue

        if type_id != "input.image":
            continue

        report.images += 1
        path_text = str(parameters.get("path", "") or "").strip()
        embedded_bytes = _decode_embedded_image(parameters, chain=node_chain)
        image_bytes: bytes | None = None
        image_name = str(parameters.get("_embedded_name", "") or "").strip()
        recovered = False

        if bool(parameters.get("embedded")) and embedded_bytes is not None:
            image_bytes = embedded_bytes
            report.already_embedded_images += 1
        elif path_text:
            try:
                image_path = resolve_authored_path(path_text, owner_path)
            except ValueError as exc:
                if embedded_bytes is None:
                    raise SelfContainedGraphError(str(exc), chain=node_chain) from exc
                image_path = None
            if image_path is not None and image_path.is_file():
                try:
                    image_bytes = image_path.read_bytes()
                    image_name = image_path.name
                except OSError as exc:
                    if embedded_bytes is None:
                        raise SelfContainedGraphError(
                            f"Could not read image source:\n{image_path}\n{exc}", chain=node_chain
                        ) from exc
            if image_bytes is None and embedded_bytes is not None:
                image_bytes = embedded_bytes
                recovered = True
        elif embedded_bytes is not None:
            image_bytes = embedded_bytes
            report.already_embedded_images += 1

        if image_bytes is None:
            raise SelfContainedGraphError(
                f"Image source is missing and no embedded copy is available:\n{path_text or 'No path'}",
                chain=node_chain,
            )
        if recovered:
            report.recovered_images += 1
            report.warnings.append(
                f"{' → '.join(node_chain)} recovered its image from stored embedded bytes."
            )
        parameters["embedded"] = True
        parameters["path"] = ""
        parameters["_embedded_data"] = base64.b64encode(image_bytes).decode("ascii")
        parameters["_embedded_name"] = image_name or "embedded-image"
        if path_text:
            parameters["_embedded_original_name"] = Path(path_text).name

    return result


def build_self_contained_graph(
    data: Mapping[str, Any],
    *,
    owner_path: str | Path | None = None,
    app_version: str = "",
) -> tuple[dict[str, Any], SelfContainedExportReport]:
    """Return a deep-copied graph whose nested graphs and images are embedded."""

    if not isinstance(data, Mapping):
        raise SelfContainedGraphError("The graph data is invalid.")
    root = deepcopy(dict(data))
    owner = Path(owner_path).expanduser().resolve() if owner_path else None
    report = SelfContainedExportReport()
    label = _graph_label(root, owner.stem if owner is not None else "Current Graph")
    result = _embed_graph(
        root,
        owner_path=owner,
        report=report,
        chain=[label],
        ancestry=set(),
        depth=0,
    )
    result["portable_export"] = {
        "mode": "single-file",
        "version": 1,
        "created_with": str(app_version or ""),
    }
    validate_self_contained_graph(result)
    return result, report


def validate_self_contained_graph(data: Mapping[str, Any]) -> None:
    """Verify that a graph requires no external graph or image resources."""

    def walk(graph: Mapping[str, Any], chain: list[str], ancestry: set[str], depth: int) -> None:
        if depth > 64:
            raise SelfContainedGraphError("Graph nesting exceeded 64 levels.", chain=chain)
        if str(graph.get("format", "")) != GRAPH_ASSET_FORMAT:
            raise SelfContainedGraphError("Embedded graph data is invalid.", chain=chain)
        key = f"embedded:{source_revision(graph)}"
        if key in ancestry:
            raise SelfContainedGraphError("A recursive embedded dependency was detected.", chain=chain)
        ancestry = set(ancestry)
        ancestry.add(key)
        for node_data in graph.get("nodes", ()):
            if not isinstance(node_data, Mapping):
                continue
            parameters = node_data.get("parameters", {})
            if not isinstance(parameters, Mapping):
                parameters = {}
            type_id = str(node_data.get("type", ""))
            node_name = str(parameters.get("name") or type_id or "Node")
            node_chain = [*chain, node_name]
            if type_id == GRAPH_INSTANCE_TYPE:
                if str(parameters.get("_asset_mode", "")) != "Embedded":
                    raise SelfContainedGraphError(
                        "A Graph Instance is still externally linked.", chain=node_chain
                    )
                if str(parameters.get("_asset_path", "") or "").strip():
                    raise SelfContainedGraphError(
                        "An embedded Graph Instance still contains an external path.", chain=node_chain
                    )
                child = parameters.get("_asset_embedded_graph")
                if not isinstance(child, Mapping):
                    raise SelfContainedGraphError(
                        "An embedded Graph Instance has no graph data.", chain=node_chain
                    )
                walk(child, [*chain, _graph_label(child, node_name)], ancestry, depth + 1)
            elif type_id == "input.image":
                if not bool(parameters.get("embedded")):
                    raise SelfContainedGraphError("An Image Input is not embedded.", chain=node_chain)
                if str(parameters.get("path", "") or "").strip():
                    raise SelfContainedGraphError(
                        "An embedded Image Input still contains an external path.", chain=node_chain
                    )
                _decode_embedded_image(parameters, chain=node_chain)
                if not str(parameters.get("_embedded_data", "") or "").strip():
                    raise SelfContainedGraphError(
                        "An Image Input contains no embedded bytes.", chain=node_chain
                    )

    label = _graph_label(data, "Graph")
    walk(data, [label], set(), 0)


def recovery_summary(data: Mapping[str, Any]) -> dict[str, int]:
    """Return a lightweight Inspector summary without touching the file system."""

    counts = {
        "linked_graphs": 0,
        "embedded_graphs": 0,
        "cached_graphs": 0,
        "external_images": 0,
        "embedded_images": 0,
    }
    def walk(graph: Mapping[str, Any], depth: int) -> None:
        # Serialized graph dictionaries cannot contain Python reference cycles.
        # Avoid hashing the whole payload here because this summary is rebuilt
        # live in the Inspector and graphs may contain large embedded images.
        if depth > 64:
            return
        for node_data in graph.get("nodes", ()):
            if not isinstance(node_data, Mapping):
                continue
            params = node_data.get("parameters", {})
            if not isinstance(params, Mapping):
                params = {}
            type_id = str(node_data.get("type", ""))
            if type_id == GRAPH_INSTANCE_TYPE:
                mode = str(params.get("_asset_mode", "Linked"))
                if mode == "Embedded":
                    counts["embedded_graphs"] += 1
                else:
                    counts["linked_graphs"] += 1
                cached = params.get("_asset_cached_graph")
                embedded = params.get("_asset_embedded_graph")
                if isinstance(cached, Mapping):
                    counts["cached_graphs"] += 1
                child = embedded if isinstance(embedded, Mapping) else cached
                if isinstance(child, Mapping):
                    walk(child, depth + 1)
            elif type_id == "input.image":
                if bool(params.get("embedded")) or str(params.get("_embedded_data", "") or ""):
                    counts["embedded_images"] += 1
                else:
                    counts["external_images"] += 1

    walk(data, 0)
    return counts
