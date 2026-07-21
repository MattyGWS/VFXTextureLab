from __future__ import annotations

"""Graph-local multi-target export profiles.

A profile set answers which production targets should be emitted together.
Each target can reuse the Texture Set Output node's current template or select
another built-in template while overriding only the export settings that need
to differ for that destination.
"""

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Mapping
import uuid

RESOLUTION_OPTIONS = (
    "Document", "256 × 256", "512 × 512", "1024 × 1024",
    "2048 × 2048", "4096 × 4096", "8192 × 8192", "Custom",
)
from .export_templates import builtin_template_names

EXPORT_PROFILE_FORMAT_VERSION = 1
NODE_TEMPLATE = "Current node template"
OUTPUT_SETTING = "Output setting"


def _new_id(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class ExportTarget:
    target_id: str
    name: str
    template_name: str = NODE_TEMPLATE
    enabled: bool = True
    subfolder: str = "{target}"
    resolution: str = OUTPUT_SETTING
    normal_convention: str = OUTPUT_SETTING
    texture_format: str = OUTPUT_SETTING
    colour_bit_depth: str = OUTPUT_SETTING
    data_bit_depth: str = OUTPUT_SETTING
    height_format: str = OUTPUT_SETTING
    custom_template: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "name": self.name,
            "template_name": self.template_name,
            "enabled": bool(self.enabled),
            "subfolder": self.subfolder,
            "resolution": self.resolution,
            "normal_convention": self.normal_convention,
            "texture_format": self.texture_format,
            "colour_bit_depth": self.colour_bit_depth,
            "data_bit_depth": self.data_bit_depth,
            "height_format": self.height_format,
            "custom_template": deepcopy(self.custom_template),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, ordinal: int = 1) -> "ExportTarget":
        raw = dict(data or {})
        template_name = str(raw.get("template_name", NODE_TEMPLATE))
        valid_templates = {NODE_TEMPLATE, *builtin_template_names()}
        custom = raw.get("custom_template")
        if template_name not in valid_templates and not isinstance(custom, Mapping):
            template_name = NODE_TEMPLATE
        resolution = str(raw.get("resolution", OUTPUT_SETTING))
        if resolution not in {OUTPUT_SETTING, *RESOLUTION_OPTIONS}:
            resolution = OUTPUT_SETTING
        normal = str(raw.get("normal_convention", OUTPUT_SETTING))
        if normal not in {OUTPUT_SETTING, "OpenGL (+Y)", "DirectX (-Y)"}:
            normal = OUTPUT_SETTING
        texture_format = str(raw.get("texture_format", OUTPUT_SETTING))
        if texture_format not in {OUTPUT_SETTING, "PNG", "TGA"}:
            texture_format = OUTPUT_SETTING
        colour_depth = str(raw.get("colour_bit_depth", OUTPUT_SETTING))
        if colour_depth not in {OUTPUT_SETTING, "8", "16"}:
            colour_depth = OUTPUT_SETTING
        data_depth = str(raw.get("data_bit_depth", OUTPUT_SETTING))
        if data_depth not in {OUTPUT_SETTING, "8", "16"}:
            data_depth = OUTPUT_SETTING
        height_format = str(raw.get("height_format", OUTPUT_SETTING))
        if height_format not in {OUTPUT_SETTING, "PNG 16-bit", "Raw R16"}:
            height_format = OUTPUT_SETTING
        return cls(
            target_id=str(raw.get("target_id", "")).strip() or _new_id("target"),
            name=str(raw.get("name", f"Target {ordinal}")).strip() or f"Target {ordinal}",
            template_name=template_name,
            enabled=bool(raw.get("enabled", True)),
            subfolder=str(raw.get("subfolder", "{target}")),
            resolution=resolution,
            normal_convention=normal,
            texture_format=texture_format,
            colour_bit_depth=colour_depth,
            data_bit_depth=data_depth,
            height_format=height_format,
            custom_template=deepcopy(dict(custom)) if isinstance(custom, Mapping) else None,
        )

    @classmethod
    def current(cls, name: str = "Current Output") -> "ExportTarget":
        return cls(_new_id("target"), name, NODE_TEMPLATE, True, "")

    def duplicate(self, *, name: str | None = None) -> "ExportTarget":
        data = self.to_dict()
        data["target_id"] = _new_id("target")
        data["name"] = name or f"{self.name} Copy"
        return ExportTarget.from_dict(data)


@dataclass(frozen=True, slots=True)
class ExportProfileSet:
    profile_id: str
    name: str
    targets: tuple[ExportTarget, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "targets": [target.to_dict() for target in self.targets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, ordinal: int = 1) -> "ExportProfileSet":
        raw = dict(data or {})
        targets_raw = raw.get("targets", [])
        if not isinstance(targets_raw, list):
            targets_raw = []
        targets = tuple(
            ExportTarget.from_dict(item, ordinal=index)
            for index, item in enumerate(targets_raw, start=1)
            if isinstance(item, Mapping)
        )
        if not targets:
            targets = (ExportTarget.current(),)
        return cls(
            profile_id=str(raw.get("profile_id", "")).strip() or _new_id("profile"),
            name=str(raw.get("name", f"Profile {ordinal}")).strip() or f"Profile {ordinal}",
            targets=targets,
        )

    @classmethod
    def default(cls) -> "ExportProfileSet":
        return cls("profile.default", "Current Output Settings", (ExportTarget.current(),))

    def duplicate(self, *, name: str | None = None) -> "ExportProfileSet":
        return ExportProfileSet(
            _new_id("profile"),
            name or f"{self.name} Copy",
            tuple(target.duplicate(name=target.name) for target in self.targets),
        )


@dataclass(frozen=True, slots=True)
class ExportProfileLibrary:
    active_profile_id: str
    profiles: tuple[ExportProfileSet, ...] = field(default_factory=tuple)
    version: int = EXPORT_PROFILE_FORMAT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "vfx-texture-lab-export-profiles",
            "version": int(self.version),
            "active_profile_id": self.active_profile_id,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }

    @classmethod
    def default(cls) -> "ExportProfileLibrary":
        profile = ExportProfileSet.default()
        return cls(profile.profile_id, (profile,))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ExportProfileLibrary":
        raw = dict(data or {})
        profiles_raw = raw.get("profiles", [])
        if not isinstance(profiles_raw, list):
            profiles_raw = []
        profiles = tuple(
            ExportProfileSet.from_dict(item, ordinal=index)
            for index, item in enumerate(profiles_raw, start=1)
            if isinstance(item, Mapping)
        )
        if not profiles:
            return cls.default()
        active = str(raw.get("active_profile_id", ""))
        if active not in {profile.profile_id for profile in profiles}:
            active = profiles[0].profile_id
        return cls(active, profiles, max(1, int(raw.get("version", EXPORT_PROFILE_FORMAT_VERSION))))

    def active_profile(self) -> ExportProfileSet:
        for profile in self.profiles:
            if profile.profile_id == self.active_profile_id:
                return profile
        return self.profiles[0] if self.profiles else ExportProfileSet.default()

    def with_active(self, profile_id: str) -> "ExportProfileLibrary":
        active = profile_id if profile_id in {p.profile_id for p in self.profiles} else self.active_profile_id
        return ExportProfileLibrary(active, self.profiles, self.version)
