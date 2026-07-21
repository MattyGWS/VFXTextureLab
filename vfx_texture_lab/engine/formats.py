from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TextureFormat(str, Enum):
    """Logical image formats used by the graph engine."""

    R16F = "r16f"
    R32F = "r32f"
    RG16F = "rg16f"
    RGBA16F = "rgba16f"
    RGBA32F = "rgba32f"

    @property
    def channels(self) -> int:
        return {
            TextureFormat.R16F: 1,
            TextureFormat.R32F: 1,
            TextureFormat.RG16F: 2,
            TextureFormat.RGBA16F: 4,
            TextureFormat.RGBA32F: 4,
        }[self]

    @property
    def bytes_per_channel(self) -> int:
        if self in (TextureFormat.R32F, TextureFormat.RGBA32F):
            return 4
        return 2

    def estimate_bytes(self, width: int, height: int) -> int:
        return int(width) * int(height) * self.channels * self.bytes_per_channel


@dataclass(frozen=True, slots=True)
class RenderContext:
    width: int
    height: int
    precision: TextureFormat = TextureFormat.RGBA16F
    colour_space: str = "Linear"
    time_seconds: float = 0.0
    frame_number: int = 0
    frame_position: float = 0.0
    delta_time: float = 1.0 / 30.0
    duration_seconds: float = 4.0
    normalised_time: float = 0.0
    loop_phase: float = 0.0
    frames_per_second: float = 30.0
    document_frame_count: int = 120
    loop_start_frame: int = 0
    loop_end_frame: int = 119
    render_mode: str = "preview"

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def animation_signature(self) -> tuple[float, int, float, float, float, float, int, int]:
        return (
            round(float(self.time_seconds), 9),
            int(self.frame_number),
            round(float(self.frame_position), 9),
            round(float(self.delta_time), 9),
            round(float(self.normalised_time), 9),
            round(float(self.loop_phase), 9),
            int(self.loop_start_frame),
            int(self.loop_end_frame),
        )
