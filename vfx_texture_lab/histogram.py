from __future__ import annotations

from dataclasses import dataclass

import numpy as np


HISTOGRAM_INTERNAL_BINS = 1024


@dataclass(frozen=True, slots=True)
class HistogramDistribution:
    """A truthful 0..1 histogram plus out-of-range population counts.

    Counts are kept linear. Values below/above the graph range are not folded
    into the first/last bins because doing that visually exaggerates endpoint
    populations in Levels-style editors.
    """

    counts: np.ndarray
    underflow: int = 0
    overflow: int = 0
    finite_count: int = 0
    clipped_minimum: float = 0.0
    clipped_maximum: float = 0.0


def compute_histogram_distribution(
    values: np.ndarray,
    *,
    bins: int = HISTOGRAM_INTERNAL_BINS,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> HistogramDistribution:
    """Calculate a linear-frequency histogram without endpoint clipping.

    The returned min/max preserve the previous Levels Auto behaviour by being
    measured after clipping to the requested range, while the visual histogram
    itself only includes genuinely in-range values.
    """

    bin_count = max(int(bins), 1)
    data = np.asarray(values, dtype=np.float32).reshape(-1)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return HistogramDistribution(np.zeros(bin_count, dtype=np.float64))

    low = float(minimum)
    high = float(maximum)
    if high <= low:
        high = low + 1.0

    underflow = int(np.count_nonzero(finite < low))
    overflow = int(np.count_nonzero(finite > high))
    in_range = finite[(finite >= low) & (finite <= high)]
    if in_range.size:
        counts, _edges = np.histogram(in_range, bins=bin_count, range=(low, high))
        counts = counts.astype(np.float64, copy=False)
    else:
        counts = np.zeros(bin_count, dtype=np.float64)

    clipped = np.clip(finite, low, high)
    return HistogramDistribution(
        counts=np.ascontiguousarray(counts, dtype=np.float64),
        underflow=underflow,
        overflow=overflow,
        finite_count=int(finite.size),
        clipped_minimum=float(np.min(clipped)),
        clipped_maximum=float(np.max(clipped)),
    )


def aggregate_histogram(counts: np.ndarray, target_bins: int) -> np.ndarray:
    """Reduce histogram bins by integrating counts, preserving total mass."""

    source = np.maximum(np.asarray(counts, dtype=np.float64).reshape(-1), 0.0)
    if source.size == 0:
        return np.zeros(max(int(target_bins), 1), dtype=np.float64)
    target = max(min(int(target_bins), source.size), 1)
    if target == source.size:
        return source.copy()

    cumulative = np.concatenate(([0.0], np.cumsum(source, dtype=np.float64)))
    source_edges = np.arange(source.size + 1, dtype=np.float64)
    target_edges = np.linspace(0.0, float(source.size), target + 1, dtype=np.float64)
    integrated = np.interp(target_edges, source_edges, cumulative)
    return np.maximum(np.diff(integrated), 0.0)


def stratified_image_sample(image: np.ndarray, maximum_dimension: int = 512) -> np.ndarray:
    """Return a deterministic cell-centred sample instead of every-nth pixels.

    Regular stride sampling can line up with procedural cells or grids. Sampling
    the centre of evenly partitioned cells remains deterministic while avoiding
    the strongest phase-locking artefacts.
    """

    source = np.asarray(image, dtype=np.float32)
    if source.ndim < 2:
        return source
    height, width = source.shape[:2]
    limit = max(int(maximum_dimension), 1)
    sample_height = min(max(height, 1), limit)
    sample_width = min(max(width, 1), limit)
    if sample_height == height and sample_width == width:
        return source

    row_ids = np.arange(sample_height, dtype=np.uint64)[:, None]
    column_ids = np.arange(sample_width, dtype=np.uint64)[None, :]
    # Two inexpensive integer hashes provide one deterministic sample within
    # each 2-D stratum.  Unlike a regular stride, periodic cells cannot lock to
    # one fixed phase across the whole image.
    hashed_a = (row_ids * np.uint64(0x9E3779B185EBCA87)) ^ (column_ids * np.uint64(0xC2B2AE3D27D4EB4F))
    hashed_b = (row_ids * np.uint64(0x165667B19E3779F9)) ^ (column_ids * np.uint64(0x85EBCA77C2B2AE63))
    unit_a = ((hashed_a >> np.uint64(11)).astype(np.float64) % (1 << 53)) / float(1 << 53)
    unit_b = ((hashed_b >> np.uint64(11)).astype(np.float64) % (1 << 53)) / float(1 << 53)

    row_start = row_ids.astype(np.float64) * height / sample_height
    row_span = height / float(sample_height)
    column_start = column_ids.astype(np.float64) * width / sample_width
    column_span = width / float(sample_width)
    rows = np.floor(row_start + unit_a * row_span).astype(np.int64)
    columns = np.floor(column_start + unit_b * column_span).astype(np.int64)
    rows = np.clip(rows, 0, height - 1)
    columns = np.clip(columns, 0, width - 1)
    return source[rows, columns]


__all__ = [
    "HISTOGRAM_INTERNAL_BINS",
    "HistogramDistribution",
    "aggregate_histogram",
    "compute_histogram_distribution",
    "stratified_image_sample",
]
