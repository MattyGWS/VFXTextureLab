from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .document import DocumentSettings
from .exporting import ExportOptions, export_image


LAYOUT_PRESETS: dict[str, tuple[int, int]] = {
    "2 × 2": (2, 2),
    "4 × 4": (4, 4),
    "8 × 8": (8, 8),
}
SOURCE_RANGES = ("Document Loop", "Entire Document", "Custom Frame Range")
SAMPLING_MODES = ("Evenly Across Range", "Consecutive Timeline Frames")


def effective_grid(parameters: Mapping[str, Any]) -> tuple[int, int]:
    layout = str(parameters.get("layout", "8 × 8"))
    if layout in LAYOUT_PRESETS:
        return LAYOUT_PRESETS[layout]
    return max(int(parameters.get("columns", 8)), 1), max(int(parameters.get("rows", 8)), 1)


def resolve_source_range(
    document: "DocumentSettings",
    source_range: str,
    custom_start: int,
    custom_end: int,
) -> tuple[int, int]:
    document.normalise()
    if source_range == "Entire Document":
        return 0, document.last_frame
    if source_range == "Custom Frame Range":
        start = min(max(int(custom_start), 0), document.last_frame)
        end = min(max(int(custom_end), start), document.last_frame)
        return start, end
    return document.loop_start_frame, document.loop_end_frame


def animation_sample_positions(
    document: "DocumentSettings",
    *,
    source_range: str = "Document Loop",
    sampling_mode: str = "Evenly Across Range",
    frame_count: int = 16,
    start_frame: int = 0,
    end_frame: int = 63,
    frame_step: int = 1,
    include_end_frame: bool = False,
) -> list[float]:
    """Return timeline positions to evaluate for an animation export.

    Even distribution is independent of document FPS and uses exclusive-end
    sampling by default. A 16-frame loop therefore samples phases 0/16 through
    15/16, avoiding a duplicated first frame in the last cell.
    """
    start, end = resolve_source_range(document, source_range, start_frame, end_frame)
    if end < start:
        return []
    if sampling_mode == "Consecutive Timeline Frames":
        return [float(value) for value in range(start, end + 1, max(int(frame_step), 1))]

    count = max(int(frame_count), 1)
    if count == 1:
        return [float(start)]
    # An inclusive integer range start..end represents a continuous loop domain
    # [start, end+1). Including the endpoint deliberately samples end+1, which
    # duplicates phase zero and is mainly useful for non-looping comparisons.
    span = float(end - start + 1)
    divisor = float(count - 1) if include_end_frame else float(count)
    return [float(start) + span * (index / divisor) for index in range(count)]


def sample_positions_from_node(document: "DocumentSettings", parameters: Mapping[str, Any]) -> list[float]:
    columns, rows = effective_grid(parameters)
    capacity = columns * rows
    use_full_grid = bool(parameters.get("use_full_grid", True))
    frame_count = capacity if use_full_grid else max(int(parameters.get("frame_count", capacity)), 1)
    return animation_sample_positions(
        document,
        source_range=str(parameters.get("source_range", "Document Loop")),
        sampling_mode=str(parameters.get("sampling", "Evenly Across Range")),
        frame_count=frame_count,
        start_frame=int(parameters.get("start_frame", document.loop_start_frame)),
        end_frame=int(parameters.get("end_frame", document.loop_end_frame)),
        frame_step=int(parameters.get("frame_step", 1)),
        include_end_frame=bool(parameters.get("include_end_frame", False)),
    )


@dataclass(slots=True)
class AnimationExportRequest:
    node_uid: str
    output_name: str
    mode: str
    directory: Path
    base_name: str
    width: int
    height: int
    start_frame: int
    end_frame: int
    frame_step: int
    columns: int
    rows: int
    padding: int
    background: str
    options: ExportOptions
    sample_positions: tuple[float, ...] = ()
    sampling_mode: str = "Consecutive Timeline Frames"

    @property
    def samples(self) -> list[float]:
        if self.sample_positions:
            return list(self.sample_positions)
        return [float(value) for value in range(self.start_frame, self.end_frame + 1, max(self.frame_step, 1))]

    @property
    def frames(self) -> list[int]:
        """Compatibility view used by older tests and consecutive exports."""
        return [int(round(value)) for value in self.samples]

    @property
    def sequence_labels(self) -> list[int]:
        if self.sampling_mode == "Consecutive Timeline Frames":
            return self.frames
        return list(range(len(self.samples)))


def parse_rgba(value: str) -> np.ndarray:
    text = str(value).strip().lstrip("#")
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        text = "00000000"
    try:
        return np.array([int(text[index:index + 2], 16) / 255.0 for index in range(0, 8, 2)], dtype=np.float32)
    except ValueError:
        return np.zeros(4, dtype=np.float32)


def assemble_flipbook(
    frames: list[np.ndarray],
    columns: int,
    rows: int,
    padding: int = 0,
    background: str = "#00000000",
) -> np.ndarray:
    if not frames:
        raise ValueError("At least one frame is required")
    first = np.asarray(frames[0], dtype=np.float32)
    height, width, channels = first.shape
    if channels != 4:
        raise ValueError("Flipbook frames must be RGBA")
    columns = max(int(columns), 1)
    rows = max(int(rows), 1)
    padding = max(int(padding), 0)
    if len(frames) > columns * rows:
        raise ValueError(f"{len(frames)} frames do not fit inside a {columns} × {rows} sheet")
    sheet_width = columns * width + max(columns - 1, 0) * padding
    sheet_height = rows * height + max(rows - 1, 0) * padding
    sheet = np.empty((sheet_height, sheet_width, 4), dtype=np.float32)
    sheet[...] = parse_rgba(background)
    for index, frame in enumerate(frames):
        image = np.asarray(frame, dtype=np.float32)
        if image.shape != first.shape:
            raise ValueError("Every flipbook frame must use the same dimensions")
        row, column = divmod(index, columns)
        y = row * (height + padding)
        x = column * (width + padding)
        sheet[y:y + height, x:x + width] = image
    return sheet


def export_animation_frames(request: AnimationExportRequest, images: list[np.ndarray]) -> list[Path]:
    request.directory.mkdir(parents=True, exist_ok=True)
    extension = ".png" if request.options.format_name.upper() == "PNG" else ".tga"
    safe_name = request.base_name or request.output_name or "animation"
    if request.mode == "Flipbook":
        sheet = assemble_flipbook(images, request.columns, request.rows, request.padding, request.background)
        path = request.directory / f"{safe_name}{extension}"
        export_image(path, sheet, request.options)
        return [path]

    exported: list[Path] = []
    for label, image in zip(request.sequence_labels, images):
        path = request.directory / f"{safe_name}_{label:04d}{extension}"
        export_image(path, image, request.options)
        exported.append(path)
    return exported
