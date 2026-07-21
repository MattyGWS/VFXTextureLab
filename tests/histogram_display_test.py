from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx_texture_lab.histogram import (
    HISTOGRAM_INTERNAL_BINS,
    aggregate_histogram,
    compute_histogram_distribution,
    stratified_image_sample,
)


def assert_linear_distribution_and_overflow() -> None:
    values = np.array([-2.0, 0.0, 0.25, 0.5, 0.75, 1.0, 3.0], dtype=np.float32)
    result = compute_histogram_distribution(values)
    assert result.counts.size == HISTOGRAM_INTERNAL_BINS
    assert int(np.sum(result.counts)) == 5
    assert result.underflow == 1
    assert result.overflow == 1
    assert result.clipped_minimum == 0.0
    assert result.clipped_maximum == 1.0
    assert result.counts[0] == 1
    assert result.counts[-1] == 1


def assert_rebinning_preserves_population() -> None:
    source = np.arange(1, HISTOGRAM_INTERNAL_BINS + 1, dtype=np.float64)
    reduced = aggregate_histogram(source, 317)
    assert reduced.size == 317
    assert np.isclose(np.sum(reduced), np.sum(source), rtol=1e-12, atol=1e-8)
    assert np.all(reduced >= 0.0)


def assert_sampling_does_not_lock_to_a_periodic_grid() -> None:
    yy, xx = np.indices((2048, 2048))
    cells = (((xx // 2) + (yy // 2)) % 2).astype(np.float32)
    rgba = np.repeat(cells[..., None], 4, axis=2)
    sample = stratified_image_sample(rgba, 512)
    assert sample.shape == (512, 512, 4)
    mean = float(np.mean(sample[..., 0]))
    assert 0.46 < mean < 0.54, mean


def assert_shared_ui_uses_linear_step_display() -> None:
    source = (ROOT / "vfx_texture_lab" / "ui" / "visual_editor_foundation.py").read_text()
    assert "np.log1p" not in source
    assert "heights = display / maximum" in source
    assert "Half-bin padding" in source
    assert "aggregate_histogram" in source


def main() -> None:
    assert_linear_distribution_and_overflow()
    assert_rebinning_preserves_population()
    assert_sampling_does_not_lock_to_a_periodic_grid()
    assert_shared_ui_uses_linear_step_display()
    print("histogram display tests passed")


if __name__ == "__main__":
    main()
