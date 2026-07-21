from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from vfx_texture_lab.flipbook import extract_native_flipbook_cell, flipbook_frame_selection
from vfx_texture_lab.nodes import build_registry


def context(frame: float, *, document_fps: float = 30.0, loop_start: int = 0, loop_end: int = 119):
    loop_count = max(loop_end - loop_start + 1, 1)
    loop_phase = ((frame - loop_start) % loop_count) / loop_count
    return SimpleNamespace(
        time_seconds=frame / document_fps,
        frame_number=int(frame),
        frame_position=float(frame),
        loop_phase=loop_phase,
        loop_start_frame=loop_start,
        loop_end_frame=loop_end,
        frames_per_second=document_fps,
    )


def base_params() -> dict:
    return {
        "layout": "8 × 8",
        "use_full_grid": True,
        "start_frame": 0,
        "playback_mode": "Source FPS",
        "source_fps": 30.0,
        "phase_offset": 0.0,
        "reverse": False,
        "ping_pong": False,
        "padding": 0,
        "order": "Left to Right, Top to Bottom",
    }


def assert_source_fps_sequence() -> None:
    params = base_params()
    observed = [flipbook_frame_selection(params, context(frame)).relative_index for frame in range(65)]
    assert observed == list(range(64)) + [0], observed

    # Source FPS is independent of the document duration. At 60 timeline FPS,
    # a 30 FPS atlas should hold each cell for two timeline ticks.
    observed_60 = [
        flipbook_frame_selection(params, context(frame, document_fps=60.0)).relative_index
        for frame in range(8)
    ]
    assert observed_60 == [0, 0, 1, 1, 2, 2, 3, 3], observed_60

    # A non-zero loop start begins the imported atlas at cell zero.
    observed_offset = [
        flipbook_frame_selection(params, context(frame, loop_start=30, loop_end=149)).relative_index
        for frame in range(30, 34)
    ]
    assert observed_offset == [0, 1, 2, 3], observed_offset


def assert_other_playback_modes() -> None:
    params = base_params()
    params["layout"] = "4 × 4"
    params["playback_mode"] = "Fit to Document Loop"
    observed = [
        flipbook_frame_selection(params, context(frame, loop_start=0, loop_end=119)).relative_index
        for frame in (0, 30, 60, 90)
    ]
    assert observed == [0, 4, 8, 12], observed

    params["playback_mode"] = "One Cell per Timeline Frame"
    observed = [flipbook_frame_selection(params, context(frame)).relative_index for frame in range(17)]
    assert observed == list(range(16)) + [0], observed

    params["__input_Phase"] = 0.5
    params["playback_mode"] = "Source FPS"
    assert flipbook_frame_selection(params, context(0)).relative_index == 8


def assert_native_cached_cell_decode() -> None:
    params = base_params()
    params["layout"] = "4 × 4"
    atlas = np.zeros((32, 32, 4), dtype=np.float32)
    atlas[..., 3] = 1.0
    for index in range(16):
        row, column = divmod(index, 4)
        atlas[row * 8 : (row + 1) * 8, column * 8 : (column + 1) * 8, :3] = index / 15.0

    cell, selection, coordinates = extract_native_flipbook_cell(atlas, params, context(7))
    assert selection.relative_index == 7
    assert coordinates == (3, 1)
    assert cell.shape == (8, 8, 4)
    assert np.allclose(cell[..., 0], 7 / 15.0)


def main() -> None:
    registry = build_registry()
    definition = registry.get("animation.flipbook_decode")
    defaults = definition.default_parameters()
    assert defaults["playback_mode"] == "Source FPS"
    assert defaults["source_fps"] == 30.0
    assert_source_fps_sequence()
    assert_other_playback_modes()
    assert_native_cached_cell_decode()
    print(
        "Flipbook playback test passed: fixed source-FPS cadence, loop-relative timing, "
        "fit-to-loop and frame-perfect modes, external Phase override, and cached native-cell decoding"
    )


if __name__ == "__main__":
    main()
