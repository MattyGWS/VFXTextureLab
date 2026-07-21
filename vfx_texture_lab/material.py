"""Shared material model constants that do not depend on Qt or the 3D renderer."""

from __future__ import annotations

from typing import Any, Mapping

SURFACE_MODES: tuple[str, ...] = (
    "Opaque",
    "Alpha Cutout",
    "Alpha Blend",
    "Premultiplied Alpha",
    "Additive",
)

MATERIAL_INPUTS = (
    "Base Colour",
    "Emissive",
    "Normal",
    "Height",
    "Ambient Occlusion",
    "Metallic",
    "Roughness",
    "Specular Level",
    "Opacity",
)

MATERIAL_DEFAULT_VALUES: dict[str, tuple[float, float, float, float]] = {
    "Base Colour": (0.32, 0.32, 0.32, 1.0),
    "Emissive": (0.0, 0.0, 0.0, 1.0),
    "Normal": (0.5, 0.5, 1.0, 1.0),
    "Height": (0.5, 0.5, 0.5, 1.0),
    "Ambient Occlusion": (1.0, 1.0, 1.0, 1.0),
    "Metallic": (0.0, 0.0, 0.0, 1.0),
    "Roughness": (0.5, 0.5, 0.5, 1.0),
    "Specular Level": (0.5, 0.5, 0.5, 1.0),
    "Opacity": (1.0, 1.0, 1.0, 1.0),
}

MATERIAL_PARAMETER_NAMES = (
    "name",
    "surface_mode",
    "cutout_threshold",
    "two_sided",
    "emissive_intensity",
    "normal_strength",
    "normal_y",
    "derive_normals",
)

LEGACY_INPUT_ALIASES = {
    "Albedo": "Base Colour",
    "Specular": "Specular Level",
}

LEGACY_SURFACE_MODE_ALIASES = {
    "Cutout": "Alpha Cutout",
    "Transparent": "Alpha Blend",
}


def normalise_surface_mode(value: Any) -> str:
    text = str(value or "Opaque")
    text = LEGACY_SURFACE_MODE_ALIASES.get(text, text)
    return text if text in SURFACE_MODES else "Opaque"


def material_settings(parameters: Mapping[str, Any]) -> dict[str, Any]:
    settings = {
        name: parameters[name]
        for name in MATERIAL_PARAMETER_NAMES
        if name in parameters
    }
    settings["surface_mode"] = normalise_surface_mode(settings.get("surface_mode", "Opaque"))
    return settings
