from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class FlipbookFrameSelection:
    atlas_index: int
    relative_index: int
    frame_count: int
    phase: float
    playback_mode: str


_PRESET_GRIDS = {
    "2 × 2": (2, 2),
    "4 × 4": (4, 4),
    "8 × 8": (8, 8),
}


def flipbook_grid(params: Mapping[str, Any]) -> tuple[int, int]:
    layout = str(params.get("layout", "4 × 4"))
    if layout in _PRESET_GRIDS:
        return _PRESET_GRIDS[layout]
    return max(int(params.get("columns", 4)), 1), max(int(params.get("rows", 4)), 1)


def flipbook_count(
    params: Mapping[str, Any],
    *,
    inherited_count: int | None = None,
    capacity_override: int | None = None,
) -> tuple[int, int, int]:
    columns, rows = flipbook_grid(params)
    capacity = max(int(capacity_override) if capacity_override is not None else columns * rows, 1)
    start = min(max(int(params.get("start_frame", 0)), 0), capacity - 1)
    available = max(capacity - start, 1)
    if inherited_count is not None:
        count = min(max(int(inherited_count), 1), available)
    elif bool(params.get("use_full_grid", True)):
        count = available
    else:
        count = min(max(int(params.get("frame_count", available)), 1), available)
    return start, count, capacity


def _float_parameter(params: Mapping[str, Any], name: str, fallback: float) -> float:
    try:
        return float(params.get(name, fallback))
    except (TypeError, ValueError):
        return float(fallback)


def flipbook_phase(params: Mapping[str, Any], context: Any, frame_count: int) -> tuple[float, str]:
    """Return the continuous cycle phase used to select a flipbook frame.

    A connected Phase socket always wins. Otherwise imported sheets default to
    their own Source FPS rather than being stretched across an unrelated
    document loop. This keeps ordinary 30 FPS atlases playing at 30 FPS while
    retaining explicit fit-to-loop and one-cell-per-timeline-frame modes.
    """

    if "__input_Phase" in params:
        raw_phase = _float_parameter(params, "__input_Phase", float(getattr(context, "loop_phase", 0.0)))
        mode = "External Phase"
    else:
        mode = str(params.get("playback_mode", "Source FPS"))
        if mode == "Fit to Document Loop":
            raw_phase = float(getattr(context, "loop_phase", 0.0))
        elif mode == "One Cell per Timeline Frame":
            frame_position = float(getattr(context, "frame_position", getattr(context, "frame_number", 0)))
            loop_start = float(getattr(context, "loop_start_frame", 0))
            raw_phase = (frame_position - loop_start) / max(frame_count, 1)
        else:
            mode = "Source FPS"
            source_fps = max(_float_parameter(params, "source_fps", 30.0), 0.001)
            frame_position = float(getattr(context, "frame_position", getattr(context, "frame_number", 0)))
            loop_start = float(getattr(context, "loop_start_frame", 0))
            document_fps = max(float(getattr(context, "frames_per_second", 30.0)), 0.001)
            elapsed_seconds = (frame_position - loop_start) / document_fps
            raw_phase = elapsed_seconds * source_fps / max(frame_count, 1)

    phase = (raw_phase + _float_parameter(params, "phase_offset", 0.0)) % 1.0
    if bool(params.get("ping_pong", False)):
        phase = 1.0 - abs(phase * 2.0 - 1.0)
    return phase, mode


def flipbook_relative_index(
    params: Mapping[str, Any],
    context: Any,
    frame_count: int,
) -> tuple[int, float, str]:
    count = max(int(frame_count), 1)
    phase, mode = flipbook_phase(params, context, count)
    relative = min(int(math.floor(phase * count)), count - 1)
    if bool(params.get("reverse", False)):
        relative = count - 1 - relative
    return relative, phase, mode


def flipbook_frame_selection(
    params: Mapping[str, Any],
    context: Any,
    *,
    inherited_count: int | None = None,
    capacity_override: int | None = None,
) -> FlipbookFrameSelection:
    start, count, capacity = flipbook_count(
        params,
        inherited_count=inherited_count,
        capacity_override=capacity_override,
    )
    relative, phase, mode = flipbook_relative_index(params, context, count)
    atlas_index = min(max(start + relative, 0), capacity - 1)
    return FlipbookFrameSelection(atlas_index, relative, count, phase, mode)


def flipbook_cell_coordinates(
    atlas_index: int,
    columns: int,
    rows: int,
    order: str,
) -> tuple[int, int]:
    capacity = max(columns * rows, 1)
    index = min(max(int(atlas_index), 0), capacity - 1)
    if order == "Top to Bottom, Left to Right":
        column = index // rows
        row = index % rows
    else:
        row = index // columns
        column = index % columns
    return min(max(column, 0), columns - 1), min(max(row, 0), rows - 1)


def extract_native_flipbook_cell(
    source: np.ndarray,
    params: Mapping[str, Any],
    context: Any,
    *,
    inherited_count: int | None = None,
) -> tuple[np.ndarray, FlipbookFrameSelection, tuple[int, int]]:
    """Extract the selected cell without resizing it to the document resolution.

    This is used by the dedicated 2D-preview fast path. The atlas is evaluated
    and cached once; playback then becomes a cheap slice and QImage update rather
    than a full graph evaluation and GPU readback for every timeline tick.
    """

    if source.ndim != 3:
        raise ValueError("Flipbook source must be an H × W × C image")
    if source.shape[2] == 1:
        scalar = source[..., 0:1]
        source = np.concatenate((scalar, scalar, scalar, np.ones_like(scalar)), axis=2)
    elif source.shape[2] == 2:
        source = np.concatenate((source, np.zeros_like(source[..., :1]), np.ones_like(source[..., :1])), axis=2)
    elif source.shape[2] == 3:
        source = np.concatenate((source, np.ones_like(source[..., :1])), axis=2)
    elif source.shape[2] > 4:
        source = source[..., :4]

    columns, rows = flipbook_grid(params)
    selection = flipbook_frame_selection(params, context, inherited_count=inherited_count)
    column, row = flipbook_cell_coordinates(
        selection.atlas_index,
        columns,
        rows,
        str(params.get("order", "Left to Right, Top to Bottom")),
    )

    height, width = source.shape[:2]
    padding = max(int(params.get("padding", 0)), 0)
    cell_width = max((width - max(columns - 1, 0) * padding) / columns, 1.0)
    cell_height = max((height - max(rows - 1, 0) * padding) / rows, 1.0)
    x0 = min(max(int(round(column * (cell_width + padding))), 0), width - 1)
    y0 = min(max(int(round(row * (cell_height + padding))), 0), height - 1)
    x1 = min(max(int(round(x0 + cell_width)), x0 + 1), width)
    y1 = min(max(int(round(y0 + cell_height)), y0 + 1), height)
    return source[y0:y1, x0:x1].copy(), selection, (column, row)
