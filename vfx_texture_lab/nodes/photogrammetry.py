from __future__ import annotations

"""Photogrammetry and scan-preparation nodes.

The image nodes in this module deliberately share the same fixed-canvas and
semantic image-kind rules as the rest of VFX Texture Lab. Material wrappers are
registered here too, while their lazy per-channel execution lives in
``material_graph.py``.
"""

import math
from typing import Any, Mapping

import numpy as np

from .base import EvalContext, ImageArray, NodeDefinition, ParameterSpec
from .flood_fill import _connected_components
from .image_ops import ensure_rgba, empty_image, grayscale_rgba, linear_to_srgb, luminance, srgb_to_linear
from .processing import (
    _auto_crop_sample,
    _input,
    _normalise_vector_pixels,
    _pixel_grids,
    _sample_clamp_bilinear,
    _sample_clamp_nearest,
    _sample_wrap,
    eval_blur,
)
from .registry import NodeRegistry
from .resampling import FILTERING_OPTIONS, estimate_coordinate_footprint, sample_image

_SCAN_ACCENT = "#c08a58"


def _resolved_kind(params: Mapping[str, Any]) -> str:
    value = str(params.get("_resolved_kind", "grayscale"))
    return value if value in {"grayscale", "color", "vector"} else "grayscale"


def _smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    if edge1 <= edge0 + 1.0e-8:
        return (values >= edge1).astype(np.float32)
    t = np.clip((values - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _periodic_mask_warp(values: np.ndarray, phase: float) -> np.ndarray:
    """Return a deterministic seamless one-dimensional fBm-like warp.

    Integer harmonics keep the displacement identical at 0 and 1, which is
    essential because the authored mask must not reintroduce a mismatch at the
    texture boundary it is trying to repair.
    """

    tau = math.tau
    warped = (
        np.sin(tau * (3.0 * values + phase)) * 0.45
        + np.sin(tau * (7.0 * values + phase * 1.73 + 0.19)) * 0.25
        + np.sin(tau * (13.0 * values + phase * 2.41 + 0.37)) * 0.15
        + np.sin(tau * (29.0 * values + phase * 3.17 + 0.11)) * 0.10
        + np.sin(tau * (53.0 * values + phase * 4.03 + 0.43)) * 0.05
    )
    return np.clip(warped, -1.0, 1.0).astype(np.float32)


def _edge_transition_mask(
    distance: np.ndarray,
    cross_axis: np.ndarray,
    size: float,
    precision: float,
    warping: float,
    phase: float,
) -> np.ndarray:
    """Build a warped cut mask measured inward from a pair of opposite edges."""

    authored_size = np.clip(float(size), 0.001, 0.5)
    authored_precision = np.clip(float(precision), 0.0, 1.0)
    warp_strength = np.clip(float(warping), 0.0, 100.0) / 100.0
    displacement = _periodic_mask_warp(cross_axis, phase)
    local_size = authored_size * np.clip(1.0 + displacement * warp_strength * 0.72, 0.2, 1.8)
    normalised = np.clip(distance / np.maximum(local_size, 1.0e-6), 0.0, 1.0)

    # Precision moves the cut farther toward the interior edge of the mask and
    # narrows its feather. Low values provide a broad photographic dissolve;
    # high values preserve detail with a crisp but still antialiased cut.
    cut = 0.52 + authored_precision * 0.30
    feather = 0.46 * (1.0 - authored_precision) + 0.018
    return 1.0 - _smoothstep(cut - feather, cut + feather, normalised)


def eval_make_it_tile_photo(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Make a photograph tile while retaining the original image at its centre.

    The original texture remains untouched through the middle of the canvas.
    Half-period wrapped duplicates are revealed only near the outer borders by
    authored, warped cut masks. Because the same duplicate is sampled at both
    members of each opposite edge pair, the resulting borders are mathematically
    continuous without blurring away the photograph's high-frequency detail.
    """

    image = _input(inputs, "Image", context)
    horizontal = bool(params.get("horizontal", True))
    vertical = bool(params.get("vertical", True))
    if not horizontal and not vertical:
        return image.copy()

    size_h = float(params.get("mask_size_h", 0.14))
    size_v = float(params.get("mask_size_v", 0.10))
    precision_h = float(params.get("mask_precision_h", 0.35))
    precision_v = float(params.get("mask_precision_v", 0.35))
    warping_h = float(params.get("mask_warping_h", 35.0))
    warping_v = float(params.get("mask_warping_v", 35.0))

    grid_x, grid_y = _pixel_grids(context)
    u = (grid_x + 0.5) / max(context.width, 1)
    v = (grid_y + 0.5) / max(context.height, 1)
    edge_x = np.minimum(u, 1.0 - u)
    edge_y = np.minimum(v, 1.0 - v)

    mask_x = (
        _edge_transition_mask(edge_x, v, size_h, precision_h, warping_h, 0.071)
        if horizontal else np.zeros_like(u, dtype=np.float32)
    )
    mask_y = (
        _edge_transition_mask(edge_y, u, size_v, precision_v, warping_v, 0.413)
        if vertical else np.zeros_like(v, dtype=np.float32)
    )

    horizontal_copy = _sample_wrap(image, grid_x + context.width * 0.5, grid_y)
    vertical_copy = _sample_wrap(image, grid_x, grid_y + context.height * 0.5)
    diagonal_copy = _sample_wrap(
        image,
        grid_x + context.width * 0.5,
        grid_y + context.height * 0.5,
    )

    mx = mask_x[..., None]
    my = mask_y[..., None]
    result = (
        image * (1.0 - mx) * (1.0 - my)
        + horizontal_copy * mx * (1.0 - my)
        + vertical_copy * (1.0 - mx) * my
        + diagonal_copy * mx * my
    )
    if _resolved_kind(params) == "vector":
        result = _normalise_vector_pixels(result)
    elif _resolved_kind(params) == "grayscale":
        result[..., 1] = result[..., 0]
        result[..., 2] = result[..., 0]
        result[..., 3] = 1.0
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def eval_lighting_equalisation(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Remove broad illumination while retaining local scan detail."""

    image = _input(inputs, "Image", context)
    kind = _resolved_kind(params)
    if kind == "vector":
        return image.copy()

    working = image.copy()
    if kind == "color":
        working[..., :3] = linear_to_srgb(np.clip(working[..., :3], 0.0, 1.0))
    radius = max(float(params.get("radius", 96.0)), 0.0)
    blurred = eval_blur(
        {"Image": working},
        {"radius": radius, "boundary": str(params.get("boundary", "Clamp"))},
        context,
    )
    target = np.clip(float(params.get("target_luminance", 0.5)), 0.01, 1.0)
    strength = np.clip(float(params.get("strength", 1.0)), 0.0, 1.0)
    mode = str(params.get("mode", "Luminance"))

    if kind == "grayscale":
        low = np.maximum(blurred[..., 0], 0.02)
        factor = target / low
        corrected = working[..., 0] * (1.0 + (factor - 1.0) * strength)
        return grayscale_rgba(np.clip(corrected, 0.0, 1.0))

    if mode == "RGB Channels":
        low = np.maximum(blurred[..., :3], 0.02)
        factor = target / low
    else:
        low_luma = np.maximum(
            blurred[..., 0] * 0.2126 + blurred[..., 1] * 0.7152 + blurred[..., 2] * 0.0722,
            0.02,
        )
        factor = (target / low_luma)[..., None]
    corrected = working[..., :3] * (1.0 + (factor - 1.0) * strength)
    result = image.copy()
    result[..., :3] = srgb_to_linear(np.clip(corrected, 0.0, 1.0))
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def eval_clone_patch(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    """Copy a transformed circular patch from one image location to another."""

    image = _input(inputs, "Image", context)
    mask_input = inputs.get("Mask")
    external_mask = luminance(ensure_rgba(mask_input, context)) if mask_input is not None else None
    grid_x, grid_y = _pixel_grids(context)
    u = (grid_x + 0.5) / max(context.width, 1)
    v = (grid_y + 0.5) / max(context.height, 1)
    source_x = float(params.get("source_x", 0.25))
    source_y = float(params.get("source_y", 0.25))
    target_x = float(params.get("target_x", 0.75))
    target_y = float(params.get("target_y", 0.75))
    radius = max(float(params.get("radius", 0.12)), 1.0e-5)
    feather = np.clip(float(params.get("feather", 0.35)), 0.0, 1.0)
    opacity = np.clip(float(params.get("opacity", 1.0)), 0.0, 1.0)
    scale = max(float(params.get("scale", 1.0)), 1.0e-4)
    angle = math.radians(float(params.get("rotation", 0.0)))

    dx = u - target_x
    dy = v - target_y
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    # Rotate the clone patch in physical pixels so a circular patch remains
    # circular on rectangular documents.
    pixel_dx = dx * context.width
    pixel_dy = dy * context.height
    local_pixel_x = (pixel_dx * cos_a - pixel_dy * sin_a) / scale
    local_pixel_y = (pixel_dx * sin_a + pixel_dy * cos_a) / scale
    sample_u = source_x + local_pixel_x / max(context.width, 1)
    sample_v = source_y + local_pixel_y / max(context.height, 1)
    sample_x = sample_u * context.width - 0.5
    sample_y = sample_v * context.height - 0.5
    boundary = str(params.get("boundary", "Clamp"))
    boundary = "Seamless / Wrap" if boundary == "Seamless / Wrap" else "Clamp"
    patch = sample_image(
        image, sample_x, sample_y,
        filtering=str(params.get("filtering", "Automatic")),
        boundary=boundary, data_kind=_resolved_kind(params),
        footprint_x=1.0 / scale, footprint_y=1.0 / scale,
    )

    distance = np.sqrt((dx * context.width) ** 2 + (dy * context.height) ** 2)
    radius_px = radius * min(context.width, context.height)
    inner = radius_px * (1.0 - feather)
    coverage = 1.0 - _smoothstep(inner, radius_px, distance)
    coverage *= opacity
    if external_mask is not None:
        coverage *= np.clip(external_mask, 0.0, 1.0)
    result = image * (1.0 - coverage[..., None]) + patch * coverage[..., None]
    if _resolved_kind(params) == "vector":
        result = _normalise_vector_pixels(result)
    elif _resolved_kind(params) == "grayscale":
        result[..., 1] = result[..., 0]
        result[..., 2] = result[..., 0]
        result[..., 3] = 1.0
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _solve_homography(source: np.ndarray, destination: np.ndarray) -> np.ndarray:
    """Return a projective transform mapping *source* points to *destination*."""

    matrix: list[tuple[float, ...]] = []
    values: list[float] = []
    for (u, v), (x, y) in zip(source, destination):
        matrix.append((u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v))
        matrix.append((0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v))
        values.extend((x, y))
    try:
        solution = np.linalg.solve(
            np.asarray(matrix, dtype=np.float64),
            np.asarray(values, dtype=np.float64),
        )
        homography = np.asarray(
            (
                (solution[0], solution[1], solution[2]),
                (solution[3], solution[4], solution[5]),
                (solution[6], solution[7], 1.0),
            ),
            dtype=np.float64,
        )
    except np.linalg.LinAlgError:
        homography = np.eye(3, dtype=np.float64)
    return homography


def quad_forward_homography(params: Mapping[str, Any]) -> np.ndarray:
    """Return the source unit-square to authored destination-quad transform.

    The four node handles describe where the original image corners should land
    in the output. This matches the visual editing model: pinching the top pair
    inward makes the top of the image narrower rather than selecting a smaller
    source trapezoid and expanding it back to the full canvas.
    """

    source = np.asarray(
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        dtype=np.float64,
    )
    destination = np.asarray(
        [
            (float(params.get("top_left_x", 0.0)), float(params.get("top_left_y", 0.0))),
            (float(params.get("top_right_x", 1.0)), float(params.get("top_right_y", 0.0))),
            (float(params.get("bottom_right_x", 1.0)), float(params.get("bottom_right_y", 1.0))),
            (float(params.get("bottom_left_x", 0.0)), float(params.get("bottom_left_y", 1.0))),
        ],
        dtype=np.float64,
    )
    return _solve_homography(source, destination).astype(np.float32)


def quad_homography(params: Mapping[str, Any]) -> np.ndarray:
    """Return the authored destination-quad to source-square sampling transform."""

    forward = quad_forward_homography(params).astype(np.float64)
    try:
        inverse = np.linalg.inv(forward)
        normaliser = inverse[2, 2]
        if abs(normaliser) > 1.0e-10:
            inverse /= normaliser
    except np.linalg.LinAlgError:
        inverse = np.eye(3, dtype=np.float64)
    return inverse.astype(np.float32)


def eval_perspective_transform(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    image = _input(inputs, "Image", context)
    identity_corners = (
        abs(float(params.get("top_left_x", 0.0))) <= 1e-12
        and abs(float(params.get("top_left_y", 0.0))) <= 1e-12
        and abs(float(params.get("top_right_x", 1.0)) - 1.0) <= 1e-12
        and abs(float(params.get("top_right_y", 0.0))) <= 1e-12
        and abs(float(params.get("bottom_right_x", 1.0)) - 1.0) <= 1e-12
        and abs(float(params.get("bottom_right_y", 1.0)) - 1.0) <= 1e-12
        and abs(float(params.get("bottom_left_x", 0.0))) <= 1e-12
        and abs(float(params.get("bottom_left_y", 1.0)) - 1.0) <= 1e-12
    )
    if identity_corners:
        return image.copy()
    matrix = quad_homography(params)
    grid_x, grid_y = _pixel_grids(context)
    u = (grid_x + 0.5) / max(context.width, 1)
    v = (grid_y + 0.5) / max(context.height, 1)
    denominator = matrix[2, 0] * u + matrix[2, 1] * v + matrix[2, 2]
    denominator = np.where(np.abs(denominator) < 1.0e-8, 1.0e-8, denominator)
    source_u = (matrix[0, 0] * u + matrix[0, 1] * v + matrix[0, 2]) / denominator
    source_v = (matrix[1, 0] * u + matrix[1, 1] * v + matrix[1, 2]) / denominator
    sx = source_u * context.width - 0.5
    sy = source_v * context.height - 0.5
    # Use the same forward projective derivatives as the WGSL path, including
    # at the final output row/column.  Generic np.gradient switches to a
    # backward difference at those edges, which can make Automatic filtering
    # choose a different footprint near a perspective boundary.
    u_x = u + 1.0 / max(context.width, 1)
    denominator_x = matrix[2, 0] * u_x + matrix[2, 1] * v + matrix[2, 2]
    denominator_x = np.where(np.abs(denominator_x) < 1.0e-8, 1.0e-8, denominator_x)
    source_x_u = (matrix[0, 0] * u_x + matrix[0, 1] * v + matrix[0, 2]) / denominator_x
    source_x_v = (matrix[1, 0] * u_x + matrix[1, 1] * v + matrix[1, 2]) / denominator_x
    v_y = v + 1.0 / max(context.height, 1)
    denominator_y = matrix[2, 0] * u + matrix[2, 1] * v_y + matrix[2, 2]
    denominator_y = np.where(np.abs(denominator_y) < 1.0e-8, 1.0e-8, denominator_y)
    source_y_u = (matrix[0, 0] * u + matrix[0, 1] * v_y + matrix[0, 2]) / denominator_y
    source_y_v = (matrix[1, 0] * u + matrix[1, 1] * v_y + matrix[1, 2]) / denominator_y
    footprint_x = np.sqrt(
        ((source_x_u - source_u) * context.width) ** 2
        + ((source_x_v - source_v) * context.height) ** 2
    ).astype(np.float32)
    footprint_y = np.sqrt(
        ((source_y_u - source_u) * context.width) ** 2
        + ((source_y_v - source_v) * context.height) ** 2
    ).astype(np.float32)
    transparent_outside = str(params.get("outside", "Transparent")) == "Transparent"
    boundary = "Transparent" if transparent_outside else "Clamp"
    result = sample_image(
        image, sx, sy, filtering=str(params.get("filtering", "Automatic")),
        boundary=boundary, data_kind=_resolved_kind(params),
        footprint_x=footprint_x, footprint_y=footprint_y,
    )
    if _resolved_kind(params) == "grayscale":
        result[..., 1] = result[..., 0]
        result[..., 2] = result[..., 0]
        result[..., 3] = 1.0
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _atlas_selection(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> tuple[np.ndarray, tuple[float, float, float, float] | None]:
    image = _input(inputs, "Image", context)
    explicit_mask = inputs.get("Mask")
    if explicit_mask is not None:
        values = luminance(ensure_rgba(explicit_mask, context))
    elif str(params.get("detection", "Luminance")) == "Alpha":
        values = image[..., 3]
    else:
        values = luminance(image)
    threshold = np.clip(float(params.get("threshold", 0.05)), 0.0, 1.0)
    minimum_area = max(float(params.get("minimum_area", 0.0001)), 0.0)
    minimum_pixels = max(int(round(minimum_area * context.width * context.height)), 1)
    labels, components = _connected_components(
        values > threshold,
        diagonal=str(params.get("connectivity", "8-connected")) == "8-connected",
        wrap_x=False,
        wrap_y=False,
        minimum_pixels=minimum_pixels,
    )
    if not components:
        return np.zeros((context.height, context.width), dtype=np.float32), None

    indexed = list(enumerate(components))
    order = str(params.get("order", "Reading Order"))
    if order == "Largest First":
        indexed.sort(key=lambda item: (-int(item[1]["pixels"]), int(item[1]["start_y"]), int(item[1]["start_x"])))
    elif order == "Left to Right":
        indexed.sort(key=lambda item: (float(item[1]["centre_x_pixels"]), float(item[1]["centre_y_pixels"])))
    elif order == "Top to Bottom":
        indexed.sort(key=lambda item: (float(item[1]["centre_y_pixels"]), float(item[1]["centre_x_pixels"])))
    selection = min(max(int(params.get("selection", 1)), 1), len(indexed)) - 1
    component_index, component = indexed[selection]
    selected = (labels == component_index).astype(np.float32)
    padding = np.clip(float(params.get("padding", 0.02)), 0.0, 0.5)
    left = max(float(component["start_x"]) / context.width - padding, 0.0)
    top = max(float(component["start_y"]) / context.height - padding, 0.0)
    right = min((float(component["start_x"]) + float(component["width_pixels"])) / context.width + padding, 1.0)
    bottom = min((float(component["start_y"]) + float(component["height_pixels"])) / context.height + padding, 1.0)
    return selected, (left, top, right, bottom)


def eval_atlas_splitter(
    inputs: Mapping[str, ImageArray], params: Mapping[str, Any], context: EvalContext
) -> ImageArray:
    image = _input(inputs, "Image", context)
    selected, bounds = _atlas_selection(inputs, params, context)
    if bounds is None:
        return np.zeros_like(image, dtype=np.float32)
    sample_params = {
        "mode": str(params.get("mode", "Fit (Keep Ratio)")),
        "filtering": str(params.get("filtering", "Automatic")),
        "_resolved_kind": _resolved_kind(params),
    }
    result = _auto_crop_sample(image, sample_params, context, bounds)
    if bool(params.get("isolate_component", True)):
        selected_rgba = grayscale_rgba(selected)
        sampled_mask = _auto_crop_sample(selected_rgba, {**sample_params, "_resolved_kind": "grayscale"}, context, bounds)[..., 0]
        result[..., :3] *= sampled_mask[..., None]
        if _resolved_kind(params) in {"color", "vector"}:
            result[..., 3] *= sampled_mask
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def register_photogrammetry_nodes(registry: NodeRegistry) -> None:
    f = ParameterSpec
    definitions = [
        NodeDefinition(
            "filter.make_it_tile_photo", "Make It Tile Photo", "Photogrammetry", eval_make_it_tile_photo,
            inputs=("Image",),
            parameters=(
                f("mask_warping_h", "Mask Warping H", "float", 35.0, 0.0, 100.0, 0.1, animatable=True, group="Horizontal Transition", group_order=0, description="Break up the horizontal border cut so it does not read as a straight line."),
                f("mask_size_h", "Transition Size H", "float", 0.14, 0.001, 0.5, 0.001, animatable=True, group="Horizontal Transition", group_order=0),
                f("mask_precision_h", "Transition Precision H", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Horizontal Transition", group_order=0, description="Higher values make the horizontal cut sharper and preserve more local detail."),
                f("mask_warping_v", "Mask Warping V", "float", 35.0, 0.0, 100.0, 0.1, animatable=True, group="Vertical Transition", group_order=10, description="Break up the vertical border cut so it does not read as a straight line."),
                f("mask_size_v", "Transition Size V", "float", 0.10, 0.001, 0.5, 0.001, animatable=True, group="Vertical Transition", group_order=10),
                f("mask_precision_v", "Transition Precision V", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Vertical Transition", group_order=10, description="Higher values make the vertical cut sharper and preserve more local detail."),
                f("horizontal", "Repair Horizontal Tiling", "bool", True, group="Axes", group_order=20),
                f("vertical", "Repair Vertical Tiling", "bool", True, group="Axes", group_order=20),
            ),
            description="Keep the source photograph centred, then reveal wrapped duplicates near its borders through warped cut masks so opposite edges tile without a blurred cross seam.",
            tags=("make it tile", "photo", "seamless", "photogrammetry", "scan", "edge blend"),
            accent=_SCAN_ACCENT, gpu_kernel="make_it_tile_photo.wgsl",
            input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "filter.lighting_equalisation", "Lighting Equalisation", "Photogrammetry", eval_lighting_equalisation,
            inputs=("Image",),
            parameters=(
                f("radius", "Lighting Radius", "float", 96.0, 1.0, 1024.0, 1.0, animatable=True, group="Illumination", group_order=0, slider_maximum=256.0),
                f("strength", "Strength", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Illumination", group_order=0),
                f("target_luminance", "Target Luminance", "float", 0.5, 0.01, 1.0, 0.01, animatable=True, group="Illumination", group_order=0),
                f("mode", "Colour Handling", "enum", "Luminance", options=("Luminance", "RGB Channels"), group="Colour", group_order=10),
                f("boundary", "Boundary", "enum", "Clamp", options=("Clamp", "Seamless / Wrap"), group="Sampling", group_order=20),
            ),
            description="Remove broad lighting and colour cast from a photograph while retaining local surface detail. Vector/normal data passes through unchanged.",
            tags=("lighting cancel", "equalize", "equalise", "scan cleanup", "photogrammetry", "de-light"),
            accent=_SCAN_ACCENT, gpu_kernel="lighting_equalisation.wgsl",
            input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "transform.clone_patch", "Clone Patch", "Photogrammetry", eval_clone_patch,
            inputs=("Image", "Mask"),
            parameters=(
                f("source_x", "Source X", "float", 0.25, -2.0, 3.0, 0.001, animatable=True, group="Source", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("source_y", "Source Y", "float", 0.25, -2.0, 3.0, 0.001, animatable=True, group="Source", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("target_x", "Target X", "float", 0.75, -2.0, 3.0, 0.001, animatable=True, group="Target", group_order=10, slider_minimum=0.0, slider_maximum=1.0),
                f("target_y", "Target Y", "float", 0.75, -2.0, 3.0, 0.001, animatable=True, group="Target", group_order=10, slider_minimum=0.0, slider_maximum=1.0),
                f("radius", "Radius", "float", 0.12, 0.001, 1.0, 0.001, animatable=True, group="Patch", group_order=20),
                f("feather", "Feather", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Patch", group_order=20),
                f("opacity", "Opacity", "float", 1.0, 0.0, 1.0, 0.01, animatable=True, group="Patch", group_order=20),
                f("scale", "Scale", "float", 1.0, 0.05, 20.0, 0.01, animatable=True, group="Transform", group_order=30, slider_maximum=4.0),
                f("rotation", "Rotation", "float", 0.0, -100000.0, 100000.0, 0.1, animatable=True, group="Transform", group_order=30, editor="angle", unit="degrees", angle_wrap=False),
                f("boundary", "Source Boundary", "enum", "Clamp", options=("Clamp", "Seamless / Wrap"), group="Sampling", group_order=40),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=40),
            ),
            description="Copy, rotate, scale and feather a circular source patch over an unwanted feature. The optional Mask further limits the destination coverage.",
            tags=("clone stamp", "heal", "repair", "photogrammetry", "scan", "patch"),
            accent=_SCAN_ACCENT, gpu_kernel="clone_patch.wgsl",
            input_kinds=(("Image", "image_any"), ("Mask", "grayscale")), output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "transform.perspective", "Perspective Transform", "Photogrammetry", eval_perspective_transform,
            inputs=("Image",),
            parameters=(
                f("top_left_x", "Top Left X", "float", 0.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("top_left_y", "Top Left Y", "float", 0.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("top_right_x", "Top Right X", "float", 1.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("top_right_y", "Top Right Y", "float", 0.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("bottom_right_x", "Bottom Right X", "float", 1.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("bottom_right_y", "Bottom Right Y", "float", 1.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("bottom_left_x", "Bottom Left X", "float", 0.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("bottom_left_y", "Bottom Left Y", "float", 1.0, -2.0, 3.0, 0.001, animatable=True, group="Corners", group_order=0, slider_minimum=0.0, slider_maximum=1.0),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=10),
                f("outside", "Outside", "enum", "Transparent", options=("Transparent", "Clamp"), group="Sampling", group_order=10),
            ),
            description="Warp the complete source image into an authored destination quadrilateral with a true projective homography. Drag the four destination corners directly in the 2D Preview.",
            tags=("quad transform", "perspective warp", "rectify", "scan", "photogrammetry"),
            accent=_SCAN_ACCENT, gpu_kernel="perspective_transform.wgsl",
            input_kinds=(("Image", "image_any"),), output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "transform.atlas_splitter", "Atlas Splitter", "Photogrammetry", eval_atlas_splitter,
            inputs=("Image", "Mask"),
            parameters=(
                f("selection", "Shape Selection", "int", 1, 1, 1024, 1, animatable=True, group="Selection", group_order=0),
                f("order", "Selection Order", "enum", "Reading Order", options=("Reading Order", "Largest First", "Left to Right", "Top to Bottom"), group="Selection", group_order=0),
                f("detection", "Detection Source", "enum", "Luminance", options=("Alpha", "Luminance"), group="Detection", group_order=10, description="An attached Mask input takes priority over this setting."),
                f("threshold", "Threshold", "float", 0.05, 0.0, 1.0, 0.001, animatable=True, group="Detection", group_order=10),
                f("minimum_area", "Minimum Area", "float", 0.0001, 0.0, 0.25, 0.0001, animatable=True, group="Detection", group_order=10),
                f("connectivity", "Connectivity", "enum", "8-connected", options=("4-connected", "8-connected"), group="Detection", group_order=10),
                f("padding", "Padding", "float", 0.02, 0.0, 0.5, 0.001, animatable=True, group="Output", group_order=20),
                f("mode", "Output Mode", "enum", "Fit (Keep Ratio)", options=("Crop Auto", "Fit (Keep Ratio)", "Fill (Stretch)"), group="Output", group_order=20),
                f("isolate_component", "Isolate Component", "bool", True, group="Output", group_order=20),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS, group="Sampling", group_order=30),
            ),
            description="Detect disconnected atlas elements, select one by index and fit it into the output canvas. Irregular atlases do not need a square grid.",
            tags=("atlas", "sprite", "scan", "flood fill", "component", "extract shape"),
            accent=_SCAN_ACCENT, gpu_kernel="image_output.wgsl",
            input_kinds=(("Image", "image_any"), ("Mask", "grayscale")), output_kinds=(("Image", "image_any"),),
            type_policy="preserve_primary", primary_input="Image",
        ),
        NodeDefinition(
            "material.crop", "Material Crop", "Materials", None, inputs=("Material",),
            parameters=(
                f("left", "Left", "float", 0.0, 0.0, 1.0, 0.001, animatable=True),
                f("right", "Right", "float", 1.0, 0.0, 1.0, 0.001, animatable=True),
                f("top", "Top", "float", 0.0, 0.0, 1.0, 0.001, animatable=True),
                f("bottom", "Bottom", "float", 1.0, 0.0, 1.0, 0.001, animatable=True),
                f("filtering", "Filtering", "enum", "Automatic", options=FILTERING_OPTIONS),
            ),
            description="Crop every authored channel of a Material coherently while preserving its material settings.",
            tags=("material transform", "scan crop", "pbr crop"), accent="#9e6bc7",
            input_kinds=(("Material", "material"),), output_kinds=(("Material", "material"),), output_name="Material",
        ),
        NodeDefinition(
            "material.make_it_tile_photo", "Material Make It Tile", "Materials", None, inputs=("Material",),
            parameters=(
                f("mask_warping_h", "Mask Warping H", "float", 35.0, 0.0, 100.0, 0.1, animatable=True, group="Horizontal Transition", group_order=0),
                f("mask_size_h", "Transition Size H", "float", 0.14, 0.001, 0.5, 0.001, animatable=True, group="Horizontal Transition", group_order=0),
                f("mask_precision_h", "Transition Precision H", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Horizontal Transition", group_order=0),
                f("mask_warping_v", "Mask Warping V", "float", 35.0, 0.0, 100.0, 0.1, animatable=True, group="Vertical Transition", group_order=10),
                f("mask_size_v", "Transition Size V", "float", 0.10, 0.001, 0.5, 0.001, animatable=True, group="Vertical Transition", group_order=10),
                f("mask_precision_v", "Transition Precision V", "float", 0.35, 0.0, 1.0, 0.01, animatable=True, group="Vertical Transition", group_order=10),
                f("horizontal", "Repair Horizontal Tiling", "bool", True, group="Axes", group_order=20),
                f("vertical", "Repair Vertical Tiling", "bool", True, group="Axes", group_order=20),
            ),
            description="Apply the same centred, warped-cut seamless reconstruction to every authored Material channel, including normal-map renormalisation.",
            tags=("material tile", "pbr seamless", "photogrammetry material"), accent="#9e6bc7",
            input_kinds=(("Material", "material"),), output_kinds=(("Material", "material"),), output_name="Material",
        ),
    ]
    for definition in definitions:
        registry.register(definition)
