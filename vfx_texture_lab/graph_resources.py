"""Graph-level imported image and mesh resources.

The graph resource library gives imported files stable identities independent of
individual nodes.  Image Input and Mesh Input nodes keep their familiar runtime
parameters for backwards compatibility and evaluation, while ``_resource_id``
links them to one graph-owned record used by Graph Explorer, relinking,
embedding and future package/bake workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import binascii
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping
import uuid


RESOURCE_LIBRARY_VERSION = 1
RESOURCE_NODE_TYPES = {"input.image": "image", "input.mesh": "mesh"}


def _new_id() -> str:
    return uuid.uuid4().hex


def _normalised_kind(value: object) -> str:
    return "mesh" if str(value or "").strip().casefold() == "mesh" else "image"


def _canonical_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return text


def _safe_embedded_hash(encoded: str) -> str:
    text = str(encoded or "").strip()
    if not text:
        return ""
    try:
        payload = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        return ""
    return hashlib.sha256(payload).hexdigest()


def _parameter_embedded_hash(parameters: Mapping[str, Any], encoded: str) -> str:
    cached = str(parameters.get("_resource_sha256", "") or "").strip().lower()
    if len(cached) == 64 and all(character in "0123456789abcdef" for character in cached):
        return cached
    return _safe_embedded_hash(encoded)


def _source_name(kind: str, source_path: str, embedded_name: str, fallback: str = "") -> str:
    if source_path:
        return Path(source_path).name
    if embedded_name:
        return Path(embedded_name).name
    if fallback:
        return str(fallback)
    return "Untitled Mesh" if kind == "mesh" else "Untitled Image"


@dataclass(slots=True)
class GraphResourceFolder:
    uid: str = field(default_factory=_new_id)
    name: str = "Folder"
    parent_uid: str = ""

    def normalise(self) -> None:
        self.uid = str(self.uid or _new_id()).strip() or _new_id()
        self.name = str(self.name or "Folder").strip() or "Folder"
        self.parent_uid = str(self.parent_uid or "").strip()
        if self.parent_uid == self.uid:
            self.parent_uid = ""

    def to_dict(self) -> dict[str, str]:
        self.normalise()
        return {"uid": self.uid, "name": self.name, "parent_uid": self.parent_uid}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "GraphResourceFolder":
        raw = dict(data or {})
        value = cls(
            uid=str(raw.get("uid") or raw.get("id") or _new_id()),
            name=str(raw.get("name") or "Folder"),
            parent_uid=str(raw.get("parent_uid") or raw.get("parent") or ""),
        )
        value.normalise()
        return value


@dataclass(slots=True)
class GraphResource:
    uid: str = field(default_factory=_new_id)
    kind: str = "image"
    name: str = "Untitled Image"
    folder_uid: str = ""
    source_path: str = ""
    embedded: bool = False
    embedded_data: str = ""
    embedded_name: str = ""
    original_name: str = ""
    sha256: str = ""
    size_bytes: int = 0
    mtime_ns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalise(self) -> None:
        self.uid = str(self.uid or _new_id()).strip() or _new_id()
        self.kind = _normalised_kind(self.kind)
        self.source_path = str(self.source_path or "").strip()
        self.embedded = bool(self.embedded or self.embedded_data)
        self.embedded_data = str(self.embedded_data or "").strip()
        self.embedded_name = str(self.embedded_name or "").strip()
        self.original_name = str(self.original_name or "").strip()
        self.folder_uid = str(self.folder_uid or "").strip()
        self.sha256 = str(self.sha256 or "").strip().lower()
        self.size_bytes = max(int(self.size_bytes or 0), 0)
        self.mtime_ns = max(int(self.mtime_ns or 0), 0)
        self.metadata = dict(self.metadata or {})
        self.name = str(self.name or "").strip() or _source_name(
            self.kind, self.source_path, self.embedded_name, self.original_name
        )
        if self.embedded_data and not self.sha256:
            self.sha256 = _safe_embedded_hash(self.embedded_data)

    @property
    def linked(self) -> bool:
        return bool(str(self.source_path or "").strip())

    def to_dict(self) -> dict[str, Any]:
        self.normalise()
        return {
            "uid": self.uid,
            "kind": self.kind,
            "name": self.name,
            "folder_uid": self.folder_uid,
            "source_path": self.source_path,
            "embedded": bool(self.embedded),
            "embedded_data": self.embedded_data,
            "embedded_name": self.embedded_name,
            "original_name": self.original_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "GraphResource":
        raw = dict(data or {})
        value = cls(
            uid=str(raw.get("uid") or raw.get("id") or _new_id()),
            kind=str(raw.get("kind") or raw.get("type") or "image"),
            name=str(raw.get("name") or ""),
            folder_uid=str(raw.get("folder_uid") or raw.get("folder") or ""),
            source_path=str(raw.get("source_path") or raw.get("path") or ""),
            embedded=bool(raw.get("embedded", False)),
            embedded_data=str(raw.get("embedded_data") or raw.get("data") or ""),
            embedded_name=str(raw.get("embedded_name") or ""),
            original_name=str(raw.get("original_name") or ""),
            sha256=str(raw.get("sha256") or ""),
            size_bytes=int(raw.get("size_bytes", 0) or 0),
            mtime_ns=int(raw.get("mtime_ns", 0) or 0),
            metadata=dict(raw.get("metadata") or {}),
        )
        value.normalise()
        return value

    def resolved_path(self, owner_path: str | Path | None = None) -> Path | None:
        text = str(self.source_path or "").strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if not path.is_absolute() and owner_path:
            owner = Path(owner_path).expanduser()
            base = owner.parent if owner.suffix else owner
            path = base / path
        try:
            return path.resolve()
        except Exception:
            return path

    def status(self, owner_path: str | Path | None = None) -> tuple[str, str]:
        path = self.resolved_path(owner_path)
        if path is not None and path.is_file():
            if self.embedded_data:
                return "linked+embedded", "Linked source with embedded recovery copy"
            return "linked", "Linked source"
        if self.embedded_data:
            return "embedded", "Embedded in graph" if not self.source_path else "Linked source missing; embedded copy available"
        return "missing", "Missing source"


@dataclass(slots=True)
class GraphResourceLibrary:
    folders: list[GraphResourceFolder] = field(default_factory=list)
    resources: list[GraphResource] = field(default_factory=list)
    version: int = RESOURCE_LIBRARY_VERSION

    def normalise(self) -> None:
        self.version = max(int(self.version or RESOURCE_LIBRARY_VERSION), 1)
        folder_ids: set[str] = set()
        clean_folders: list[GraphResourceFolder] = []
        for folder in list(self.folders or []):
            if not isinstance(folder, GraphResourceFolder):
                folder = GraphResourceFolder.from_dict(folder)  # type: ignore[arg-type]
            folder.normalise()
            if folder.uid in folder_ids:
                folder.uid = _new_id()
            folder_ids.add(folder.uid)
            clean_folders.append(folder)
        for folder in clean_folders:
            if folder.parent_uid not in folder_ids:
                folder.parent_uid = ""
        self.folders = clean_folders

        resource_ids: set[str] = set()
        clean_resources: list[GraphResource] = []
        for resource in list(self.resources or []):
            if not isinstance(resource, GraphResource):
                resource = GraphResource.from_dict(resource)  # type: ignore[arg-type]
            resource.normalise()
            if resource.uid in resource_ids:
                resource.uid = _new_id()
            resource_ids.add(resource.uid)
            if resource.folder_uid not in folder_ids:
                resource.folder_uid = ""
            clean_resources.append(resource)
        self.resources = clean_resources

    def to_dict(self) -> dict[str, Any]:
        self.normalise()
        return {
            "version": self.version,
            "folders": [folder.to_dict() for folder in self.folders],
            "items": [resource.to_dict() for resource in self.resources],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "GraphResourceLibrary":
        raw = dict(data or {})
        folders_raw = raw.get("folders", [])
        resources_raw = raw.get("items", raw.get("resources", []))
        library = cls(
            folders=[GraphResourceFolder.from_dict(item) for item in folders_raw if isinstance(item, Mapping)],
            resources=[GraphResource.from_dict(item) for item in resources_raw if isinstance(item, Mapping)],
            version=int(raw.get("version", RESOURCE_LIBRARY_VERSION) or RESOURCE_LIBRARY_VERSION),
        )
        library.normalise()
        return library

    @classmethod
    def from_project_data(cls, data: MutableMapping[str, Any]) -> "GraphResourceLibrary":
        library = cls.from_dict(data.get("resources") if isinstance(data.get("resources"), Mapping) else None)
        # Format 19 stores embedded payloads once in the graph resource record.
        # Hydrate the familiar node parameters before migration/capture so all
        # existing evaluators and older graph-manipulation code continue to work.
        library.hydrate_serialized_nodes(data.get("nodes", []))
        library.capture_serialized_nodes(data.get("nodes", []))
        data["resources"] = library.to_dict()
        return library

    def by_id(self, uid: object) -> GraphResource | None:
        wanted = str(uid or "").strip()
        return next((item for item in self.resources if item.uid == wanted), None)

    def folder_by_id(self, uid: object) -> GraphResourceFolder | None:
        wanted = str(uid or "").strip()
        return next((item for item in self.folders if item.uid == wanted), None)

    def _default_folder(self, kind: str) -> str:
        wanted = "Meshes" if _normalised_kind(kind) == "mesh" else "Images"
        existing = next((folder for folder in self.folders if not folder.parent_uid and folder.name.casefold() == wanted.casefold()), None)
        if existing is not None:
            return existing.uid
        folder = GraphResourceFolder(name=wanted)
        self.folders.append(folder)
        return folder.uid

    def add_folder(self, name: str, parent_uid: str = "") -> GraphResourceFolder:
        parent = str(parent_uid or "").strip()
        if parent and self.folder_by_id(parent) is None:
            parent = ""
        base = str(name or "New Folder").strip() or "New Folder"
        siblings = {
            folder.name.casefold()
            for folder in self.folders
            if folder.parent_uid == parent
        }
        final = base
        ordinal = 2
        while final.casefold() in siblings:
            final = f"{base} {ordinal}"
            ordinal += 1
        folder = GraphResourceFolder(name=final, parent_uid=parent)
        self.folders.append(folder)
        return folder

    def rename_folder(self, uid: str, name: str) -> bool:
        folder = self.folder_by_id(uid)
        text = str(name or "").strip()
        if folder is None or not text or text == folder.name:
            return False
        folder.name = text
        return True

    def remove_folder(self, uid: str) -> bool:
        folder = self.folder_by_id(uid)
        if folder is None:
            return False
        parent = folder.parent_uid
        for child in self.folders:
            if child.parent_uid == folder.uid:
                child.parent_uid = parent
        for resource in self.resources:
            if resource.folder_uid == folder.uid:
                resource.folder_uid = parent
        self.folders = [candidate for candidate in self.folders if candidate.uid != folder.uid]
        return True

    def move_resource(self, resource_uid: str, folder_uid: str = "") -> bool:
        resource = self.by_id(resource_uid)
        target = str(folder_uid or "").strip()
        if target and self.folder_by_id(target) is None:
            return False
        if resource is None or resource.folder_uid == target:
            return False
        resource.folder_uid = target
        return True

    def rename_resource(self, resource_uid: str, name: str) -> bool:
        resource = self.by_id(resource_uid)
        text = str(name or "").strip()
        if resource is None or not text or resource.name == text:
            return False
        resource.name = text
        resource.metadata["_display_name_custom"] = True
        return True

    def remove_resource(self, resource_uid: str, *, referenced: int = 0) -> bool:
        if int(referenced) > 0 or self.by_id(resource_uid) is None:
            return False
        self.resources = [item for item in self.resources if item.uid != str(resource_uid)]
        return True

    def _folder_path(self, folder_uid: str) -> list[str]:
        """Return a virtual folder path from graph root to ``folder_uid``."""

        folder = self.folder_by_id(folder_uid)
        if folder is None:
            return []
        result: list[str] = []
        seen: set[str] = set()
        while folder is not None and folder.uid not in seen:
            seen.add(folder.uid)
            result.append(folder.name)
            folder = self.folder_by_id(folder.parent_uid)
        result.reverse()
        return result

    def _ensure_folder_path(self, names: Iterable[str]) -> str:
        parent_uid = ""
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            existing = next(
                (
                    folder
                    for folder in self.folders
                    if folder.parent_uid == parent_uid and folder.name.casefold() == name.casefold()
                ),
                None,
            )
            if existing is None:
                existing = self.add_folder(name, parent_uid)
            parent_uid = existing.uid
        return parent_uid

    def parameters_for_resource(self, resource_uid: str) -> dict[str, Any]:
        """Build runtime parameters for a new Image Input or Mesh Input node."""

        resource = self.by_id(resource_uid)
        if resource is None:
            raise KeyError("Graph resource no longer exists")
        parameters: dict[str, Any] = {}
        self._apply_record_parameters(resource, parameters)
        return parameters

    def copy_resource_from(
        self,
        source_library: "GraphResourceLibrary",
        resource_uid: str,
        *,
        source_owner_path: str | Path | None = None,
    ) -> GraphResource:
        """Copy one resource and its virtual folder hierarchy into this graph.

        Linked paths are resolved against the source graph before crossing the
        document boundary so a relative path cannot accidentally point at a
        different file in the destination graph. Repeated drops reuse an
        equivalent destination resource rather than multiplying records.
        """

        source = source_library.by_id(resource_uid)
        if source is None:
            raise KeyError("Source graph resource no longer exists")

        source_path = str(source.source_path or "").strip()
        if source_path:
            resolved = source.resolved_path(source_owner_path)
            if resolved is not None:
                source_path = str(resolved)

        probe = {
            "path": source_path,
            "embedded": bool(source.embedded),
            "_embedded_data": source.embedded_data,
            "_resource_sha256": source.sha256,
        }
        reusable = self._find_reusable(source.kind, probe)
        if reusable is not None:
            return reusable

        folder_uid = self._ensure_folder_path(source_library._folder_path(source.folder_uid))
        copied = GraphResource(
            kind=source.kind,
            name=source.name,
            folder_uid=folder_uid,
            source_path=source_path,
            embedded=bool(source.embedded),
            embedded_data=source.embedded_data,
            embedded_name=source.embedded_name,
            original_name=source.original_name,
            sha256=source.sha256,
            size_bytes=source.size_bytes,
            mtime_ns=source.mtime_ns,
            metadata=deepcopy(source.metadata),
        )
        copied.normalise()
        self.resources.append(copied)
        return copied

    def _resource_identity(self, kind: str, parameters: Mapping[str, Any]) -> tuple[str, str]:
        path = _canonical_path(parameters.get("path"))
        if path:
            return _normalised_kind(kind), f"path:{path.casefold()}"
        embedded = str(parameters.get("_embedded_data", "") or "").strip()
        digest = _parameter_embedded_hash(parameters, embedded)
        if digest:
            return _normalised_kind(kind), f"sha256:{digest}"
        return _normalised_kind(kind), ""

    def _resource_state_identity(self, kind: str, parameters: Mapping[str, Any]) -> str:
        """Return the source identity plus its linked/embedded storage state.

        Two nodes may point at the same file while intentionally using different
        portability modes.  Keeping that state in the sharing identity prevents
        a per-node Embed toggle from silently changing every other use.
        """

        normalised_kind, source_identity = self._resource_identity(kind, parameters)
        if not source_identity:
            return ""
        encoded = str(parameters.get("_embedded_data", "") or "").strip()
        payload_hash = _parameter_embedded_hash(parameters, encoded)
        embedded = bool(parameters.get("embedded", False) or encoded)
        return (
            f"{normalised_kind}|{source_identity}|embedded:{int(embedded)}"
            f"|payload:{payload_hash}"
        )

    def _find_reusable(self, kind: str, parameters: Mapping[str, Any]) -> GraphResource | None:
        wanted_state = self._resource_state_identity(kind, parameters)
        if not wanted_state:
            return None
        for resource in self.resources:
            probe = {
                "path": resource.source_path,
                "embedded": resource.embedded,
                "_embedded_data": resource.embedded_data,
                "_resource_sha256": resource.sha256,
            }
            if self._resource_state_identity(resource.kind, probe) == wanted_state:
                return resource
        return None

    @staticmethod
    def _metadata_parameter_keys(kind: str) -> tuple[str, ...]:
        if kind == "mesh":
            return (
                "_source_vertex_count", "_source_triangle_count", "_source_has_uvs",
                "_source_has_normals", "_source_object_count", "_source_mesh_name", "_source_error",
            )
        return (
            "_source_precision", "_source_channels", "_source_mode", "_source_size",
            "_native_kind", "_detected_kind", "_normal_detection", "_source_error",
        )

    @classmethod
    def _metadata_from_parameters(cls, kind: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: parameters[key]
            for key in cls._metadata_parameter_keys(kind)
            if key in parameters
        }

    def _update_from_parameters(self, resource: GraphResource, parameters: Mapping[str, Any]) -> None:
        previous_embedded_data = resource.embedded_data
        resource.source_path = str(parameters.get("path", "") or "").strip()
        resource.embedded = bool(parameters.get("embedded", False) or parameters.get("_embedded_data"))
        resource.embedded_data = str(parameters.get("_embedded_data", "") or "").strip()
        resource.embedded_name = str(parameters.get("_embedded_name", "") or "").strip()
        resource.original_name = str(parameters.get("_embedded_original_name", "") or "").strip()
        if resource.embedded_data:
            # Reuse the digest while the payload is unchanged; recalculate it
            # exactly once when linked recovery bytes are refreshed.
            if resource.embedded_data != previous_embedded_data or not resource.sha256:
                resource.sha256 = _safe_embedded_hash(resource.embedded_data)
        else:
            resource.sha256 = ""
        for key in self._metadata_parameter_keys(resource.kind):
            resource.metadata.pop(key, None)
        resource.metadata.update(self._metadata_from_parameters(resource.kind, parameters))
        if not bool(resource.metadata.get("_display_name_custom", False)):
            resource.name = _source_name(
                resource.kind,
                resource.source_path,
                resource.embedded_name,
                str(parameters.get("name", "") or "").strip(),
            )
        path = Path(resource.source_path).expanduser() if resource.source_path else None
        if path is not None and path.is_file():
            try:
                stat = path.stat()
                resource.size_bytes = int(stat.st_size)
                resource.mtime_ns = int(stat.st_mtime_ns)
                resource.sha256 = resource.sha256 or ""
            except OSError:
                pass
        resource.normalise()

    def _create_from_parameters(self, kind: str, parameters: Mapping[str, Any]) -> GraphResource:
        kind = _normalised_kind(kind)
        source_path = str(parameters.get("path", "") or "").strip()
        embedded_name = str(parameters.get("_embedded_name", "") or "").strip()
        fallback = str(parameters.get("name", "") or "").strip()
        resource = GraphResource(
            kind=kind,
            name=_source_name(kind, source_path, embedded_name, fallback),
            folder_uid=self._default_folder(kind),
        )
        self._update_from_parameters(resource, parameters)
        self.resources.append(resource)
        return resource

    def ensure_parameter_resource(
        self,
        node_type: str,
        parameters: MutableMapping[str, Any],
        *,
        reference_counts: Mapping[str, int] | None = None,
        target_identities: Mapping[str, set[str]] | None = None,
    ) -> GraphResource | None:
        kind = RESOURCE_NODE_TYPES.get(str(node_type or ""))
        if kind is None:
            return None
        resource_uid = str(parameters.get("_resource_id", "") or "").strip()
        resource = self.by_id(resource_uid)
        reusable = self._find_reusable(kind, parameters)
        has_source = bool(
            str(parameters.get("path", "") or "").strip()
            or str(parameters.get("_embedded_data", "") or "").strip()
        )
        if not has_source:
            # An empty Image/Mesh Input is a node waiting for a source, not an
            # imported graph resource. Detaching leaves a previously used record
            # available as an explicit unused resource until the artist removes it.
            parameters.pop("_resource_id", None)
            return None
        if resource is None:
            resource = reusable or self._create_from_parameters(kind, parameters)
            parameters["_resource_id"] = resource.uid
            if resource.sha256:
                parameters["_resource_sha256"] = resource.sha256
            else:
                parameters.pop("_resource_sha256", None)
            return resource

        # Editing the source path on one of several shared nodes creates a new
        # resource rather than unexpectedly replacing every use. Explicit
        # Explorer Replace/Relink actions still update all linked nodes.
        current_state = self._resource_state_identity(resource.kind, {
            "path": resource.source_path,
            "embedded": resource.embedded,
            "_embedded_data": resource.embedded_data,
            "_resource_sha256": resource.sha256,
        })
        node_state = self._resource_state_identity(kind, parameters)
        shared = int((reference_counts or {}).get(resource.uid, 0)) > 1
        group_targets = set((target_identities or {}).get(resource.uid, set()))
        whole_group_changed_together = (
            shared and len(group_targets) == 1 and node_state in group_targets
        )
        if (
            shared
            and not whole_group_changed_together
            and node_state
            and current_state
            and node_state != current_state
        ):
            previous_folder_uid = resource.folder_uid
            if reusable is not None and reusable.uid != resource.uid:
                resource = reusable
            else:
                resource = self._create_from_parameters(kind, parameters)
                resource.folder_uid = previous_folder_uid
            parameters["_resource_id"] = resource.uid
            if resource.sha256:
                parameters["_resource_sha256"] = resource.sha256
            else:
                parameters.pop("_resource_sha256", None)
            return resource

        self._update_from_parameters(resource, parameters)
        parameters["_resource_id"] = resource.uid
        if resource.sha256:
            parameters["_resource_sha256"] = resource.sha256
        else:
            parameters.pop("_resource_sha256", None)
        return resource

    def capture_serialized_nodes(self, nodes: Iterable[Any]) -> bool:
        entries = [item for item in nodes if isinstance(item, Mapping)]
        counts: dict[str, int] = {}
        targets: dict[str, set[str]] = {}
        for entry in entries:
            parameters = entry.get("parameters")
            node_type = str(entry.get("type", "") or "")
            kind = RESOURCE_NODE_TYPES.get(node_type)
            if isinstance(parameters, Mapping):
                uid = str(parameters.get("_resource_id", "") or "").strip()
                if uid:
                    counts[uid] = counts.get(uid, 0) + 1
                    if kind is not None:
                        state = self._resource_state_identity(kind, parameters)
                        if state:
                            targets.setdefault(uid, set()).add(state)
        before = self.to_dict()
        for entry in entries:
            node_type = str(entry.get("type", "") or "")
            parameters = entry.get("parameters")
            if isinstance(parameters, MutableMapping):
                self.ensure_parameter_resource(
                    node_type,
                    parameters,
                    reference_counts=counts,
                    target_identities=targets,
                )
        return before != self.to_dict()

    def capture_scene(self, scene: Any) -> bool:
        nodes = list(getattr(scene, "nodes", {}).values())
        counts: dict[str, int] = {}
        targets: dict[str, set[str]] = {}
        for node in nodes:
            parameters = getattr(node, "parameters", {})
            uid = str(parameters.get("_resource_id", "") or "").strip()
            node_type = str(getattr(getattr(node, "definition", None), "type_id", "") or "")
            kind = RESOURCE_NODE_TYPES.get(node_type)
            if uid:
                counts[uid] = counts.get(uid, 0) + 1
                if kind is not None:
                    state = self._resource_state_identity(kind, parameters)
                    if state:
                        targets.setdefault(uid, set()).add(state)
        before = self.to_dict()
        for node in nodes:
            node_type = str(getattr(getattr(node, "definition", None), "type_id", "") or "")
            parameters = getattr(node, "parameters", None)
            if isinstance(parameters, MutableMapping):
                self.ensure_parameter_resource(
                    node_type,
                    parameters,
                    reference_counts=counts,
                    target_identities=targets,
                )
        return before != self.to_dict()

    def hydrate_serialized_nodes(self, nodes: Iterable[Any]) -> int:
        """Restore runtime node parameters from graph-owned resource records."""

        count = 0
        for entry in nodes:
            if not isinstance(entry, Mapping):
                continue
            node_type = str(entry.get("type", "") or "")
            if node_type not in RESOURCE_NODE_TYPES:
                continue
            parameters = entry.get("parameters")
            if not isinstance(parameters, MutableMapping):
                continue
            resource = self.by_id(parameters.get("_resource_id"))
            if resource is None:
                continue
            self._apply_record_parameters(resource, parameters)
            count += 1
        return count

    def compact_serialized_nodes(self, nodes: Iterable[Any]) -> int:
        """Store embedded payloads once in resources instead of once per using node."""

        count = 0
        for entry in nodes:
            if not isinstance(entry, Mapping):
                continue
            parameters = entry.get("parameters")
            if not isinstance(parameters, MutableMapping):
                continue
            resource = self.by_id(parameters.get("_resource_id"))
            if resource is None or not resource.embedded_data:
                continue
            parameters.pop("_embedded_data", None)
            parameters.pop("_embedded_name", None)
            parameters.pop("_embedded_original_name", None)
            count += 1
        return count

    def prune_unreferenced_serialized(self, nodes: Iterable[Any]) -> int:
        """Remove resource records not referenced by the supplied serialized graph."""

        referenced: set[str] = set()
        for entry in nodes:
            if not isinstance(entry, Mapping):
                continue
            parameters = entry.get("parameters")
            if isinstance(parameters, Mapping):
                uid = str(parameters.get("_resource_id", "") or "").strip()
                if uid:
                    referenced.add(uid)
        before = len(self.resources)
        self.resources = [resource for resource in self.resources if resource.uid in referenced]
        return before - len(self.resources)

    def reference_counts(self, scene: Any) -> dict[str, int]:
        result: dict[str, int] = {}
        for node in getattr(scene, "nodes", {}).values():
            uid = str(getattr(node, "parameters", {}).get("_resource_id", "") or "").strip()
            if uid:
                result[uid] = result.get(uid, 0) + 1
        return result

    def node_uids_for_resource(self, scene: Any, resource_uid: str) -> list[str]:
        wanted = str(resource_uid or "")
        return [
            str(node.uid)
            for node in getattr(scene, "nodes", {}).values()
            if str(getattr(node, "parameters", {}).get("_resource_id", "") or "") == wanted
        ]

    @staticmethod
    def _apply_record_parameters(resource: GraphResource, parameters: MutableMapping[str, Any]) -> None:
        parameters["_resource_id"] = resource.uid
        parameters["path"] = resource.source_path
        parameters["embedded"] = bool(resource.embedded)
        if resource.embedded_data:
            parameters["_embedded_data"] = resource.embedded_data
            parameters["_embedded_name"] = resource.embedded_name or resource.name
            if resource.original_name:
                parameters["_embedded_original_name"] = resource.original_name
            if resource.sha256:
                parameters["_resource_sha256"] = resource.sha256
        else:
            parameters.pop("_embedded_data", None)
            parameters.pop("_embedded_name", None)
            parameters.pop("_embedded_original_name", None)
            parameters.pop("_resource_sha256", None)
        for key, value in resource.metadata.items():
            if str(key).startswith("_source_") or key in {"_native_kind", "_detected_kind", "_normal_detection"}:
                parameters[key] = value

    def apply_resource_to_scene(self, scene: Any, resource_uid: str, *, touch: bool = True) -> int:
        resource = self.by_id(resource_uid)
        if resource is None:
            return 0
        count = 0
        for node in getattr(scene, "nodes", {}).values():
            parameters = getattr(node, "parameters", None)
            if not isinstance(parameters, MutableMapping):
                continue
            if str(parameters.get("_resource_id", "") or "") != resource.uid:
                continue
            self._apply_record_parameters(resource, parameters)
            parameters["_reload_token"] = int(resource.mtime_ns or resource.size_bytes or 1)
            node_type = str(getattr(getattr(node, "definition", None), "type_id", "") or "")
            try:
                if node_type == "input.image":
                    from .nodes.input_nodes import refresh_image_metadata
                    refresh_image_metadata(parameters)
                elif node_type == "input.mesh":
                    from .geometry import refresh_mesh_metadata
                    refresh_mesh_metadata(parameters)
            except Exception:
                pass
            count += 1
        if count and touch and hasattr(scene, "_resolve_dynamic_types"):
            try:
                scene._resolve_dynamic_types()
                scene._remove_incompatible_connections()
                scene._refresh_all_groups()
                scene._touch()
            except Exception:
                pass
        return count

    def relink(self, resource_uid: str, path: str | Path) -> GraphResource:
        resource = self.by_id(resource_uid)
        if resource is None:
            raise KeyError("Graph resource no longer exists")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        stat = source.stat()
        resource.source_path = str(source)
        if not bool(resource.metadata.get("_display_name_custom", False)):
            resource.name = source.name
        resource.embedded = False
        resource.embedded_data = ""
        resource.embedded_name = ""
        resource.original_name = ""
        resource.sha256 = ""
        resource.size_bytes = int(stat.st_size)
        resource.mtime_ns = int(stat.st_mtime_ns)
        resource.metadata.pop("_source_error", None)
        return resource

    def embed(self, resource_uid: str, *, source_path: str | Path | None = None) -> GraphResource:
        resource = self.by_id(resource_uid)
        if resource is None:
            raise KeyError("Graph resource no longer exists")
        payload: bytes | None = None
        source: Path | None = None
        if source_path:
            source = Path(source_path).expanduser().resolve()
        elif resource.source_path:
            source = Path(resource.source_path).expanduser().resolve()
        if source is not None and source.is_file():
            payload = source.read_bytes()
        elif resource.embedded_data:
            try:
                payload = base64.b64decode(resource.embedded_data, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("The embedded resource data is damaged") from exc
        if payload is None:
            raise FileNotFoundError("The linked source and embedded recovery copy are both unavailable")
        original = source.name if source is not None else (resource.embedded_name or resource.name)
        resource.source_path = ""
        resource.embedded = True
        resource.embedded_data = base64.b64encode(payload).decode("ascii")
        resource.embedded_name = original
        resource.original_name = original
        resource.sha256 = hashlib.sha256(payload).hexdigest()
        resource.size_bytes = len(payload)
        resource.mtime_ns = 0
        return resource

    def restore_embedded(self, resource_uid: str, destination: str | Path, *, relink: bool = True) -> Path:
        resource = self.by_id(resource_uid)
        if resource is None or not resource.embedded_data:
            raise ValueError("This graph resource has no embedded data")
        try:
            payload = base64.b64decode(resource.embedded_data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("The embedded resource data is damaged") from exc
        path = Path(destination).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        if relink:
            self.relink(resource.uid, path)
        return path


def migrate_project_resources(data: MutableMapping[str, Any]) -> GraphResourceLibrary:
    """Ensure every imported image/mesh node has a graph-owned resource.

    This is intentionally idempotent and can be called on current files as well
    as graph format 18 and earlier. Existing Image Input parameters remain valid,
    so graph assets and old evaluation paths continue to work unchanged.
    """

    library = GraphResourceLibrary.from_project_data(data)
    data["resources"] = library.to_dict()
    return library
