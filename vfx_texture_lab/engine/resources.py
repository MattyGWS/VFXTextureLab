from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .formats import TextureFormat


@dataclass(slots=True)
class CpuImage:
    array: np.ndarray
    logical_format: TextureFormat = TextureFormat.RGBA16F
    cache_key: str = ""
    provenance: frozenset[str] = field(default_factory=frozenset)
    data_kind: str = "color"
    precision: str = "16-bit"

    @property
    def width(self) -> int:
        return int(self.array.shape[1])

    @property
    def height(self) -> int:
        return int(self.array.shape[0])

    @property
    def bytes_used(self) -> int:
        return int(self.array.nbytes)

    def pin(self) -> None:
        return

    def unpin(self) -> None:
        return

    def release(self) -> None:
        return


@dataclass(slots=True)
class GpuImage:
    texture: Any
    view: Any
    width: int
    height: int
    logical_format: TextureFormat = TextureFormat.RGBA16F
    cache_key: str = ""
    physical_format: str = "rgba16float"
    provenance: frozenset[str] = field(default_factory=lambda: frozenset({"gpu"}))
    data_kind: str = "color"
    precision: str = "16-bit"
    _released: bool = field(default=False, init=False)
    _release_requested: bool = field(default=False, init=False)
    _pins: int = field(default=0, init=False)

    @property
    def bytes_used(self) -> int:
        bytes_per_pixel = {
            "r32float": 4,
            "rg32float": 8,
            "rgba16float": 8,
            "rgba32float": 16,
        }.get(self.physical_format, 16)
        return self.width * self.height * bytes_per_pixel

    def pin(self) -> None:
        if self._released:
            raise RuntimeError("Attempted to use a released GPU texture")
        self._pins += 1

    def unpin(self) -> None:
        self._pins = max(self._pins - 1, 0)
        if self._pins == 0 and self._release_requested:
            self._destroy_now()

    def release(self) -> None:
        if self._released:
            return
        if self._pins:
            self._release_requested = True
            return
        self._destroy_now()

    def _destroy_now(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self.texture.destroy()
        except Exception:
            pass


@dataclass(slots=True)
class SignalValue:
    """A tiny CPU-side scalar/vector graph value.

    Signal processing remains in Python because it is a handful of arithmetic
    operations per node, not millions of per-pixel operations. The value can be
    a scalar or a short tuple and participates in the same content cache as
    image resources.
    """

    value: float | tuple[float, ...] | dict[str, float | tuple[float, ...]]
    kind: str = "scalar"
    cache_key: str = ""
    provenance: frozenset[str] = field(default_factory=lambda: frozenset({"signal"}))

    @property
    def bytes_used(self) -> int:
        return 32

    def pin(self) -> None:
        return

    def unpin(self) -> None:
        return

    def release(self) -> None:
        return

    def output(self, name: str = "Value") -> float | tuple[float, ...]:
        value = self.value
        if isinstance(value, dict):
            if name in value:
                return value[name]
            if value:
                return next(iter(value.values()))
            return 0.0
        return value

    def scalar(self, name: str = "Value") -> float:
        value = self.output(name)
        if isinstance(value, tuple):
            return float(value[0]) if value else 0.0
        return float(value)


ImageResource = CpuImage | GpuImage
GraphResource = CpuImage | GpuImage | SignalValue
