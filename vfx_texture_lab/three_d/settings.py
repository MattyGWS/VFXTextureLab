from __future__ import annotations

from typing import Any, Mapping

from ..material import SURFACE_MODES


PREVIEW_MESH_OPTIONS = ("Terrain Plane", "Flat Plane", "Sphere", "Cube", "Rounded Cube", "Rounded Cylinder", "Custom Mesh")
GEOMETRY_QUALITY_OPTIONS = ("Low", "Medium", "High", "Ultra")
# Kept as a compatibility input for 0.31.x settings and old graphs. New UI uses
# mesh_quality because each built-in mesh needs a different useful tessellation.
MESH_RESOLUTION_OPTIONS = ("32 × 32", "64 × 64", "128 × 128", "256 × 256", "512 × 512")
TILE_PREVIEW_OPTIONS = ("1 × 1", "3 × 3")
TEXTURE_RESOLUTION_OPTIONS = ("256", "512", "1024", "2048", "4096", "Match 2D Preview")
PROJECTION_OPTIONS = ("Perspective", "Orthographic")
CAMERA_VIEW_OPTIONS = ("Free", "Front", "Back", "Left", "Right", "Top", "Bottom")
LIGHTING_PRESET_OPTIONS = ("VFX Studio", "Studio", "Soft", "Dramatic", "Flat", "Unlit", "Custom")
ENVIRONMENT_PRESET_OPTIONS = ("Studio Small 02", "Cayley Interior", "Overcast Soil", "Chalk Quarry Sunset")
TONE_MAPPING_OPTIONS = ("ACES", "Neutral", "Reinhard", "Linear")
ANTI_ALIASING_OPTIONS = ("Off", "4× MSAA")
WIREFRAME_OPTIONS = ("Auto", "Always", "Off")
DEBUG_VIEW_OPTIONS = (
    "Final Material",
    "Base Colour",
    "Normal Map (Tangent)",
    "Surface Normals (World)",
    "Height",
    "Roughness",
    "Metallic",
    "Ambient Occlusion",
    "Emissive",
    "Opacity",
    "UV Checker",
    "Mesh Normals",
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

VIEWPORT_DEFAULTS: dict[str, Any] = {
    "preview_mesh": "Terrain Plane",
    "mesh_quality": "High",
    "mesh_resolution": "256 × 256",  # legacy compatibility only
    "custom_mesh": "",
    "tile_preview": "1 × 1",
    "material_tiling": 1,
    "texture_resolution": "Match 2D Preview",
    "displacement_amount": 0.25,
    "height_midpoint": 0.5,
    "invert_height": False,
    "camera_projection": "Perspective",
    "camera_fov": 40.0,
    "lighting_preset": "VFX Studio",
    "lighting_mode": "Lit",
    "environment_preset": "Cayley Interior",
    "environment_rotation": 301.0,
    "environment_intensity": 0.20,
    "show_environment": False,
    "sun_intensity": 2.5,
    "sun_azimuth": 328.0,
    "sun_elevation": 35.0,
    "shadows": True,
    "shadow_strength": 0.77,
    "background": "#2d2938ff",
    "background_brightness": 1.0,
    "show_grid": False,
    "show_uv_grid": False,
    "debug_view": "Final Material",
    "tone_mapping": "ACES",
    "exposure": 0.05,
    "anti_aliasing": "4× MSAA",
    "wireframe": "Auto",
    "bloom": True,
    "bloom_intensity": 1.58,
    "bloom_threshold": 1.60,
    "bloom_radius": 21.0,
    "sharpen": True,
    "sharpen_strength": 1.0,
    "vignette": True,
    "vignette_strength": 0.58,
    "turntable": False,
    "turntable_speed": 20.0,
}

VIEWPORT_SETTING_NAMES = tuple(VIEWPORT_DEFAULTS)
DISPLACEMENT_SETTING_NAMES = ("displacement_amount", "height_midpoint", "invert_height")

LEGACY_INPUT_ALIASES = {
    "Albedo": "Base Colour",
    "Specular": "Specular Level",
}

LEGACY_SURFACE_MODE_ALIASES = {
    "Cutout": "Alpha Cutout",
    "Transparent": "Alpha Blend",
}


QUALITY_FROM_LEGACY_RESOLUTION = {
    "32 × 32": "Low",
    "64 × 64": "Low",
    "128 × 128": "Medium",
    "256 × 256": "High",
    "512 × 512": "Ultra",
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


def viewport_settings(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = dict(VIEWPORT_DEFAULTS)
    if values:
        for name in VIEWPORT_SETTING_NAMES:
            if name in values:
                result[name] = values[name]
        if "mesh_quality" not in values and "mesh_resolution" in values:
            result["mesh_quality"] = QUALITY_FROM_LEGACY_RESOLUTION.get(
                str(values["mesh_resolution"]), "High"
            )
    if result["preview_mesh"] not in PREVIEW_MESH_OPTIONS:
        result["preview_mesh"] = VIEWPORT_DEFAULTS["preview_mesh"]
    if result["mesh_quality"] not in GEOMETRY_QUALITY_OPTIONS:
        result["mesh_quality"] = VIEWPORT_DEFAULTS["mesh_quality"]
    if result["camera_projection"] not in PROJECTION_OPTIONS:
        result["camera_projection"] = "Perspective"
    if result["environment_preset"] not in ENVIRONMENT_PRESET_OPTIONS:
        result["environment_preset"] = VIEWPORT_DEFAULTS["environment_preset"]
    if result["tone_mapping"] not in TONE_MAPPING_OPTIONS:
        result["tone_mapping"] = VIEWPORT_DEFAULTS["tone_mapping"]
    if result["anti_aliasing"] not in ANTI_ALIASING_OPTIONS:
        result["anti_aliasing"] = VIEWPORT_DEFAULTS["anti_aliasing"]
    if result["wireframe"] not in WIREFRAME_OPTIONS:
        result["wireframe"] = VIEWPORT_DEFAULTS["wireframe"]
    try:
        result["material_tiling"] = min(max(int(round(float(result["material_tiling"]))), 1), 32)
    except (TypeError, ValueError):
        result["material_tiling"] = VIEWPORT_DEFAULTS["material_tiling"]
    try:
        result["displacement_amount"] = min(max(float(result["displacement_amount"]), -5.0), 5.0)
    except (TypeError, ValueError):
        result["displacement_amount"] = VIEWPORT_DEFAULTS["displacement_amount"]
    try:
        result["height_midpoint"] = min(max(float(result["height_midpoint"]), 0.0), 1.0)
    except (TypeError, ValueError):
        result["height_midpoint"] = VIEWPORT_DEFAULTS["height_midpoint"]
    result["invert_height"] = bool(result.get("invert_height", False))
    try:
        result["background_brightness"] = min(max(float(result["background_brightness"]), 0.0), 1.0)
    except (TypeError, ValueError):
        result["background_brightness"] = VIEWPORT_DEFAULTS["background_brightness"]
    # 0.32.0 called the final world-space surface-normal view simply
    # "Normal". Preserve that meaning while using an explicit label.
    if result["debug_view"] == "Normal":
        result["debug_view"] = "Surface Normals (World)"
    if result["debug_view"] not in DEBUG_VIEW_OPTIONS:
        result["debug_view"] = "Final Material"
    return result
