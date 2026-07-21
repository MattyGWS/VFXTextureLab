from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from vfx_texture_lab.engine.evaluator import (
    EvaluationCancelled,
    GraphEvaluator,
    GraphSnapshot,
    SnapshotNode,
)
from vfx_texture_lab.engine.formats import TextureFormat
from vfx_texture_lab.engine.resources import GpuImage
from vfx_texture_lab.nodes.registry import build_registry


class _Texture:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _TransactionBackend:
    available = True

    def __init__(self, *, cancel_during_finalise: bool) -> None:
        self.cancel_during_finalise = cancel_during_finalise
        self.textures: list[_Texture] = []

    def supports(self, _definition) -> bool:
        return True

    @contextmanager
    def command_batch(self):
        yield

    def evaluate_node(
        self,
        _definition,
        _inputs,
        _parameters,
        context,
        cache_key,
        logical_format,
        **_kwargs,
    ) -> GpuImage:
        texture = _Texture()
        self.textures.append(texture)
        return GpuImage(
            texture=texture,
            view=object(),
            width=context.width,
            height=context.height,
            logical_format=logical_format or TextureFormat.RGBA16F,
            cache_key=cache_key,
            physical_format="rgba16float",
            provenance=frozenset({"gpu"}),
            data_kind="color",
            precision="16-bit",
        )

    def prepare_preview_rgba8(self, image, width, height, _kind, **_kwargs):
        if self.cancel_during_finalise:
            raise EvaluationCancelled()
        return np.zeros((height, width, 4), dtype=np.uint8)


def _snapshot() -> tuple[GraphSnapshot, str]:
    definition = build_registry().get("generator.constant")
    node = SnapshotNode(
        "constant",
        definition,
        definition.default_parameters(),
        resolved_kind="color",
    )
    return GraphSnapshot({node.uid: node}, {}), node.uid


def test_gpu_cache_transaction() -> None:
    snapshot, uid = _snapshot()

    cancelled_backend = _TransactionBackend(cancel_during_finalise=True)
    cancelled_evaluator = GraphEvaluator(backend_preference="auto")
    cancelled_evaluator.gpu_backend = cancelled_backend
    try:
        cancelled_evaluator.evaluate_snapshot(
            snapshot,
            uid,
            32,
            32,
            prepare_display=True,
            display_width=32,
            display_height=32,
            collect_traces=False,
        )
    except EvaluationCancelled:
        pass
    else:
        raise AssertionError("The fixture must cancel during finalisation")

    assert cancelled_evaluator.gpu_cache.stats().entries == 0
    assert cancelled_backend.textures
    assert all(texture.destroyed for texture in cancelled_backend.textures)

    successful_backend = _TransactionBackend(cancel_during_finalise=False)
    successful_evaluator = GraphEvaluator(backend_preference="auto")
    successful_evaluator.gpu_backend = successful_backend
    result = successful_evaluator.evaluate_snapshot(
        snapshot,
        uid,
        32,
        32,
        prepare_display=True,
        display_width=32,
        display_height=32,
        collect_traces=False,
    )
    assert result.error is None
    assert successful_evaluator.gpu_cache.stats().entries == 1
    assert successful_backend.textures
    assert not successful_backend.textures[-1].destroyed


if __name__ == "__main__":
    test_gpu_cache_transaction()
    print("GPU cache cancellation regression test passed")
