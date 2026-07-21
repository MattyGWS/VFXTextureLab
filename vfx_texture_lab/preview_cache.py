from __future__ import annotations

"""Small byte-budgeted presentation-cache payloads.

The graph evaluator already caches CPU/GPU node resources.  These wrappers cover
one layer above that cache: display-ready 2D pixels and fully resolved material
bundles.  Keeping this layer separate means merely changing graph focus does not
repeat final readback, material composition, or renderer upload work.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class CachedPreviewResult:
    result: Any

    @property
    def bytes_used(self) -> int:
        total = 0
        for name in ("display_rgba", "image"):
            array = getattr(self.result, name, None)
            if isinstance(array, np.ndarray):
                total += int(array.nbytes)
        return total


@dataclass(slots=True)
class CachedMaterialResult:
    result: Any

    @property
    def bytes_used(self) -> int:
        textures = getattr(self.result, "textures", {}) or {}
        return sum(int(array.nbytes) for array in textures.values() if isinstance(array, np.ndarray))


@dataclass(slots=True)
class CachedThumbnail:
    rgba: np.ndarray | None = None
    signal_value: Any = None

    @property
    def bytes_used(self) -> int:
        return int(self.rgba.nbytes) if isinstance(self.rgba, np.ndarray) else 64


@dataclass(slots=True)
class PresentationCacheTrace:
    node_uid: str
    name: str
    type_id: str = "internal.presentation_cache"
    stage: str = "presentation cache"
    backend: str = "Memory"
    state: str = "Reused"
    elapsed_ms: float = 0.0
    cache_hit: bool = True
    width: int = 0
    height: int = 0
    precision: str = ""
    data_kind: str = ""
    bytes_used: int = 0
    render_mode: str = "preview"
    details: str = ""
