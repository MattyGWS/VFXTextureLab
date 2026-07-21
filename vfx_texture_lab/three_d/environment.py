from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Final

import numpy as np

ENVIRONMENT_PRESETS: Final[tuple[str, ...]] = (
    "Studio Small 02",
    "Cayley Interior",
    "Overcast Soil",
    "Chalk Quarry Sunset",
)

_ENVIRONMENT_FILES: Final[dict[str, str]] = {
    "Studio Small 02": "studio_small_02.npz",
    "Cayley Interior": "cayley_interior.npz",
    "Overcast Soil": "overcast_soil.npz",
    "Chalk Quarry Sunset": "chalk_quarry_sunset.npz",
}


def _box_downsample(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    if height == 1 and width == 1:
        return image
    padded = image
    if height % 2:
        padded = np.concatenate((padded, padded[-1:, :, :]), axis=0)
    if width % 2:
        padded = np.concatenate((padded, padded[:, -1:, :]), axis=1)
    return (
        padded[0::2, 0::2]
        + padded[1::2, 0::2]
        + padded[0::2, 1::2]
        + padded[1::2, 1::2]
    ) * 0.25


def mip_chain(image: np.ndarray, *, minimum_size: int = 1) -> tuple[np.ndarray, ...]:
    current = np.ascontiguousarray(image, dtype=np.float32)
    levels = [current]
    while max(current.shape[0], current.shape[1]) > max(int(minimum_size), 1):
        current = np.ascontiguousarray(_box_downsample(current), dtype=np.float32)
        levels.append(current)
        if current.shape[0] == 1 and current.shape[1] == 1:
            break
    return tuple(levels)


@lru_cache(maxsize=len(ENVIRONMENT_PRESETS))
def load_environment(name: str) -> np.ndarray:
    preset = name if name in _ENVIRONMENT_FILES else ENVIRONMENT_PRESETS[0]
    resource = files("vfx_texture_lab.assets.environments").joinpath(_ENVIRONMENT_FILES[preset])
    with resource.open("rb") as handle, np.load(handle) as archive:
        image = np.asarray(archive["image"], dtype=np.float32)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Invalid environment map {preset!r}: {image.shape}")
    return np.ascontiguousarray(np.maximum(image, 0.0), dtype=np.float32)
