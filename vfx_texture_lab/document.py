from __future__ import annotations

from dataclasses import asdict, dataclass, field
import uuid

from .engine.formats import TextureFormat


@dataclass(slots=True)
class GraphAssetMetadata:
    """Persistent document-level identity and library metadata for a graph."""

    asset_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Untitled Graph"
    description: str = ""
    category: str = "Graph Assets"
    tags: list[str] = field(default_factory=list)
    author: str = ""
    version: str = "1.0.0"
    created_with: str = ""
    thumbnail_png: str = ""
    thumbnail_source: str = ""

    def normalise(self) -> None:
        self.asset_id = str(self.asset_id or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        self.name = str(self.name or "Untitled Graph").strip() or "Untitled Graph"
        self.description = str(self.description or "").strip()
        self.category = str(self.category or "Graph Assets").strip() or "Graph Assets"
        if isinstance(self.tags, str):
            raw_tags = self.tags.split(",")
        else:
            raw_tags = list(self.tags or [])
        seen: set[str] = set()
        tags: list[str] = []
        for value in raw_tags:
            tag = str(value).strip()
            key = tag.casefold()
            if tag and key not in seen:
                seen.add(key)
                tags.append(tag)
        self.tags = tags
        self.author = str(self.author or "").strip()
        self.version = str(self.version or "1.0.0").strip() or "1.0.0"
        self.created_with = str(self.created_with or "").strip()
        self.thumbnail_png = str(self.thumbnail_png or "").strip()
        self.thumbnail_source = str(self.thumbnail_source or "").strip().casefold()
        if self.thumbnail_source not in {"", "2d", "3d", "imported"}:
            self.thumbnail_source = "imported" if self.thumbnail_png else ""
        if not self.thumbnail_png:
            self.thumbnail_source = ""

    def to_dict(self) -> dict:
        self.normalise()
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
            "author": self.author,
            "version": self.version,
            "created_with": self.created_with,
            "thumbnail_png": self.thumbnail_png,
            "thumbnail_source": self.thumbnail_source,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict | None,
        *,
        default_name: str = "Untitled Graph",
        created_with: str = "",
    ) -> "GraphAssetMetadata":
        payload = dict(data or {})
        metadata = cls(
            asset_id=str(payload.get("asset_id") or uuid.uuid4().hex),
            name=str(payload.get("name") or default_name),
            description=str(payload.get("description") or ""),
            category=str(payload.get("category") or "Graph Assets"),
            tags=payload.get("tags", []),
            author=str(payload.get("author") or ""),
            version=str(payload.get("version") or "1.0.0"),
            created_with=str(payload.get("created_with") or created_with),
            thumbnail_png=str(payload.get("thumbnail_png") or ""),
            thumbnail_source=str(payload.get("thumbnail_source") or ""),
        )
        metadata.normalise()
        return metadata

    def regenerate_identity(self) -> str:
        self.asset_id = uuid.uuid4().hex
        return self.asset_id


@dataclass(slots=True)
class DocumentSettings:
    width: int = 1024
    height: int = 1024
    preview_max_dimension: int = 512
    working_precision: str = "16-bit float"
    colour_space: str = "Linear"
    default_tiling: bool = True
    default_geometric_rasterization: str = "Antialiased"

    # Animation is document data rather than an application preference so a
    # shared graph always plays and exports with the same timing.
    frames_per_second: float = 30.0
    duration_seconds: float = 4.0
    loop_start_frame: int = 0
    loop_end_frame: int = 119
    playback_speed: float = 1.0

    def normalise(self) -> None:
        self.width = max(1, min(int(self.width), 16384))
        self.height = max(1, min(int(self.height), 16384))
        self.preview_max_dimension = max(64, min(int(self.preview_max_dimension), 4096))
        if self.working_precision not in ("16-bit float", "32-bit float"):
            self.working_precision = "16-bit float"
        if self.colour_space not in ("Linear", "sRGB"):
            self.colour_space = "Linear"
        self.default_tiling = bool(self.default_tiling)
        if self.default_geometric_rasterization not in ("Antialiased", "Pixel Exact"):
            self.default_geometric_rasterization = "Antialiased"

        self.frames_per_second = max(1.0, min(float(self.frames_per_second), 240.0))
        self.duration_seconds = max(1.0 / self.frames_per_second, min(float(self.duration_seconds), 3600.0))
        self.playback_speed = max(0.05, min(float(self.playback_speed), 8.0))
        last = max(self.frame_count - 1, 0)
        self.loop_start_frame = max(0, min(int(self.loop_start_frame), last))
        self.loop_end_frame = max(self.loop_start_frame, min(int(self.loop_end_frame), last))

    @property
    def texture_precision(self) -> TextureFormat:
        return TextureFormat.RGBA32F if self.working_precision == "32-bit float" else TextureFormat.RGBA16F

    @property
    def frame_count(self) -> int:
        return max(1, int(round(float(self.duration_seconds) * float(self.frames_per_second))))

    @property
    def last_frame(self) -> int:
        return self.frame_count - 1

    @property
    def loop_frame_count(self) -> int:
        self.normalise()
        return max(self.loop_end_frame - self.loop_start_frame + 1, 1)

    def clamp_frame_position(self, frame: float | int) -> float:
        """Clamp a possibly sub-frame sample to the document time domain.

        Animation export can evaluate between timeline frames. The upper bound
        is the exclusive end of the document, allowing a sample such as 119.5
        in a 120-frame document without forcing it back onto frame 119.
        """
        self.normalise()
        return min(max(float(frame), 0.0), float(self.frame_count))

    def time_for_frame(self, frame: float | int) -> float:
        return self.clamp_frame_position(frame) / self.frames_per_second

    def normalised_time_for_frame(self, frame: float | int) -> float:
        """Inclusive document progress used by the Time.Document Phase output.

        The final integer timeline frame remains 1.0 for compatibility with
        existing 0.8 graphs. Looping work should use loop_phase_for_frame(),
        which deliberately uses exclusive-end sampling and never duplicates the
        first frame at the end of a loop.
        """
        self.normalise()
        if self.frame_count <= 1:
            return 0.0
        return min(max(float(frame), 0.0), float(self.last_frame)) / float(self.last_frame)

    def loop_phase_for_frame(self, frame: float | int) -> float:
        """Return a seamless 0<=phase<1 signal over the configured loop.

        With a 0-63 loop this yields 0/64 ... 63/64. The next playback frame is
        frame 0 again, so a wrapped transform has 64 unique frames and no
        duplicated endpoint.
        """
        self.normalise()
        span = float(self.loop_frame_count)
        return ((float(frame) - float(self.loop_start_frame)) / span) % 1.0

    def phase_for_range(self, frame: float | int, start: int, end: int) -> float:
        start = int(start)
        end = max(int(end), start)
        span = float(end - start + 1)
        return ((float(frame) - float(start)) / span) % 1.0

    def preview_size(self) -> tuple[int, int]:
        self.normalise()
        longest = max(self.width, self.height)
        if longest <= self.preview_max_dimension:
            return self.width, self.height
        scale = self.preview_max_dimension / longest
        return max(1, round(self.width * scale)), max(1, round(self.height * scale))

    def to_dict(self) -> dict:
        self.normalise()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "DocumentSettings":
        data = dict(data or {})
        fps = data.get("frames_per_second", data.get("fps", 30.0))
        duration = data.get("duration_seconds", data.get("duration", 4.0))
        guessed_last = max(0, int(round(float(fps) * float(duration))) - 1)
        settings = cls(
            width=data.get("width", 1024),
            height=data.get("height", 1024),
            preview_max_dimension=data.get("preview_max_dimension", 512),
            working_precision=data.get("working_precision", "16-bit float"),
            colour_space=data.get("colour_space", "Linear"),
            default_tiling=data.get("default_tiling", True),
            default_geometric_rasterization=data.get("default_geometric_rasterization", "Antialiased"),
            frames_per_second=fps,
            duration_seconds=duration,
            loop_start_frame=data.get("loop_start_frame", 0),
            loop_end_frame=data.get("loop_end_frame", guessed_last),
            playback_speed=data.get("playback_speed", 1.0),
        )
        settings.normalise()
        return settings
