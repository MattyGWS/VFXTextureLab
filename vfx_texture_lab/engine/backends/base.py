from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ...nodes.base import NodeDefinition
from ..formats import RenderContext, TextureFormat
from ..resources import CpuImage, ImageResource


class BackendCancelled(RuntimeError):
    """Raised when a long-running backend node is superseded or cancelled."""


@dataclass(frozen=True, slots=True)
class BackendInfo:
    key: str
    name: str
    available: bool
    detail: str = ""


class RenderBackend(ABC):
    key = "base"
    name = "Base"

    @abstractmethod
    def info(self) -> BackendInfo:
        raise NotImplementedError

    @abstractmethod
    def supports(self, definition: NodeDefinition) -> bool:
        raise NotImplementedError

    @abstractmethod
    def evaluate_node(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        cache_key: str,
        logical_format: TextureFormat | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ImageResource:
        raise NotImplementedError

    @abstractmethod
    def to_cpu(self, image: ImageResource) -> CpuImage:
        raise NotImplementedError

    def clear(self) -> None:
        return
