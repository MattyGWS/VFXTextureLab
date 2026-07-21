from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np

from ..nodes.base import EvalContext, NodeDefinition
from .backends.base import BackendCancelled
from .formats import RenderContext, TextureFormat
from .resources import CpuImage, GpuImage, ImageResource


FrameProvider = Callable[[int], tuple[dict[str, ImageResource], dict[str, Any], RenderContext]]


@dataclass(slots=True)
class SimulationCheckpoint:
    frame: int
    state: dict[str, CpuImage]
    output: CpuImage


@dataclass(slots=True)
class SimulationTrack:
    key: tuple[Any, ...]
    node_uid: str
    current_frame: int = -1
    state: dict[str, ImageResource] = field(default_factory=dict)
    output: ImageResource | None = None
    checkpoints: OrderedDict[int, SimulationCheckpoint] = field(default_factory=OrderedDict)


@dataclass(frozen=True, slots=True)
class SimulationEvaluation:
    output: ImageResource
    steps: int
    restored_checkpoint: int
    backend: str


class SimulationStateManager:
    """Own deterministic runtime state for every stateful graph node.

    Tracks keep the most recent frame hot, making ordinary sequential playback a
    single simulation step. Periodic CPU checkpoints make backwards scrubbing
    and non-sequential export restart from a nearby frame rather than frame zero.
    Runtime textures never enter graph files and are invalidated by a branch
    revision key supplied by the graph evaluator.
    """

    def __init__(self, *, maximum_tracks: int = 64, maximum_checkpoints: int = 32) -> None:
        self.maximum_tracks = max(int(maximum_tracks), 4)
        self.maximum_checkpoints = max(int(maximum_checkpoints), 4)
        self._tracks: OrderedDict[tuple[Any, ...], SimulationTrack] = OrderedDict()

    def clear(self, node_uid: str | None = None) -> None:
        keys = [
            key for key, track in self._tracks.items()
            if node_uid is None or track.node_uid == node_uid
        ]
        for key in keys:
            track = self._tracks.pop(key)
            self._release_track(track)

    def track_count(self) -> int:
        return len(self._tracks)

    def evaluate(
        self,
        *,
        definition: NodeDefinition,
        node_uid: str,
        revision: str,
        target_frame: int,
        current_inputs: Mapping[str, ImageResource],
        current_parameters: Mapping[str, Any],
        context: RenderContext,
        backend_key: str,
        logical_format: TextureFormat,
        frame_provider: FrameProvider,
        cpu_backend,
        gpu_backend=None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> SimulationEvaluation:
        spec = definition.stateful
        if spec is None:
            raise TypeError(f"{definition.name} is not stateful")
        target_frame = max(int(target_frame), 0)
        backend = "gpu" if backend_key == "gpu" and gpu_backend is not None and spec.gpu_supported else "cpu"
        key = (
            node_uid,
            revision,
            int(context.width),
            int(context.height),
            context.precision.value,
            context.colour_space,
            backend,
        )

        # A changed branch revision makes every older state for this node stale.
        for stale_key, stale_track in list(self._tracks.items()):
            if stale_track.node_uid == node_uid and stale_key != key:
                self._tracks.pop(stale_key, None)
                self._release_track(stale_track)

        track = self._tracks.get(key)
        if track is None:
            track = SimulationTrack(key=key, node_uid=node_uid)
            self._tracks[key] = track
            self._trim_tracks()
        else:
            self._tracks.move_to_end(key)

        if track.current_frame == target_frame and track.output is not None:
            return SimulationEvaluation(track.output, 0, target_frame, backend)

        restored = -1
        if track.current_frame < 0 or track.current_frame > target_frame:
            checkpoint = self._nearest_checkpoint(track, target_frame)
            self._release_current(track)
            if checkpoint is not None:
                track.current_frame = checkpoint.frame
                track.state = {
                    name: self._copy_cpu(image, f"{image.cache_key}:restore:{target_frame}")
                    for name, image in checkpoint.state.items()
                }
                track.output = self._copy_cpu(
                    checkpoint.output, f"{checkpoint.output.cache_key}:restore:{target_frame}"
                )
                restored = checkpoint.frame
            else:
                track.current_frame = -1
                track.state = {}
                track.output = None

        steps = 0
        if track.current_frame < 0:
            inputs, parameters, frame_context = (
                (dict(current_inputs), dict(current_parameters), context)
                if target_frame == 0
                else frame_provider(0)
            )
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("Simulation initialisation was cancelled")
            state, output = self._initialise(
                definition,
                inputs,
                parameters,
                frame_context,
                backend,
                logical_format,
                f"simulation:{revision}:{node_uid}:0",
                cpu_backend,
                gpu_backend,
                cancel_check,
            )
            track.state = state
            track.output = output
            track.current_frame = 0
            self._store_checkpoint(track, 0, cpu_backend)
            steps += 1
            restored = 0
            if progress_callback is not None:
                progress_callback(0, target_frame, definition.name)

        start_frame = track.current_frame + 1
        for frame in range(start_frame, target_frame + 1):
            if cancel_check is not None and cancel_check():
                raise BackendCancelled("Simulation replay was cancelled")
            inputs, parameters, frame_context = (
                (dict(current_inputs), dict(current_parameters), context)
                if frame == target_frame
                else frame_provider(frame)
            )
            new_state, new_output = self._step(
                definition,
                track.state,
                inputs,
                parameters,
                frame_context,
                backend,
                logical_format,
                f"simulation:{revision}:{node_uid}:{frame}",
                cpu_backend,
                gpu_backend,
                cancel_check,
            )
            old_state = track.state
            old_output = track.output
            track.state = new_state
            track.output = new_output
            track.current_frame = frame
            self._release_replaced(old_state, old_output, new_state, new_output)
            steps += 1
            if progress_callback is not None:
                progress_callback(frame, target_frame, definition.name)
            interval = max(int(spec.checkpoint_interval), 1)
            if frame % interval == 0 or frame == context.loop_start_frame:
                self._store_checkpoint(track, frame, cpu_backend)

        if track.output is None:
            raise RuntimeError(f"{definition.name} produced no simulation output")
        return SimulationEvaluation(track.output, steps, restored, backend)

    @staticmethod
    def _eval_context(context: RenderContext) -> EvalContext:
        return EvalContext(
            width=context.width,
            height=context.height,
            time_seconds=context.time_seconds,
            frame_number=context.frame_number,
            frame_position=context.frame_position,
            delta_time=context.delta_time,
            duration_seconds=context.duration_seconds,
            normalised_time=context.normalised_time,
            loop_phase=context.loop_phase,
            frames_per_second=context.frames_per_second,
            document_frame_count=context.document_frame_count,
            loop_start_frame=context.loop_start_frame,
            loop_end_frame=context.loop_end_frame,
            render_mode=context.render_mode,
        )

    def _initialise(
        self,
        definition: NodeDefinition,
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        backend: str,
        logical_format: TextureFormat,
        cache_key: str,
        cpu_backend,
        gpu_backend,
        cancel_check,
    ) -> tuple[dict[str, ImageResource], ImageResource]:
        if backend == "gpu":
            return gpu_backend.evaluate_stateful_initial(
                definition, inputs, parameters, context, cache_key, logical_format, cancel_check
            )
        spec = definition.stateful
        assert spec is not None
        cpu_inputs = {name: cpu_backend.to_cpu(resource).array for name, resource in inputs.items()}
        frame = spec.initializer(cpu_inputs, parameters, self._eval_context(context))
        return self._wrap_cpu_frame(frame.state, frame.output, logical_format, cache_key, inputs)

    def _step(
        self,
        definition: NodeDefinition,
        previous_state: Mapping[str, ImageResource],
        inputs: Mapping[str, ImageResource],
        parameters: Mapping[str, Any],
        context: RenderContext,
        backend: str,
        logical_format: TextureFormat,
        cache_key: str,
        cpu_backend,
        gpu_backend,
        cancel_check,
    ) -> tuple[dict[str, ImageResource], ImageResource]:
        if backend == "gpu":
            return gpu_backend.evaluate_stateful_step(
                definition, previous_state, inputs, parameters, context,
                cache_key, logical_format, cancel_check
            )
        spec = definition.stateful
        assert spec is not None
        previous_cpu = {
            name: cpu_backend.to_cpu(resource).array for name, resource in previous_state.items()
        }
        cpu_inputs = {name: cpu_backend.to_cpu(resource).array for name, resource in inputs.items()}
        frame = spec.stepper(previous_cpu, cpu_inputs, parameters, self._eval_context(context))
        return self._wrap_cpu_frame(frame.state, frame.output, logical_format, cache_key, inputs)

    @staticmethod
    def _wrap_cpu_frame(
        state: Mapping[str, np.ndarray],
        output: np.ndarray,
        logical_format: TextureFormat,
        cache_key: str,
        inputs: Mapping[str, ImageResource],
    ) -> tuple[dict[str, ImageResource], ImageResource]:
        provenance = frozenset({"cpu"})
        data_kind = "grayscale"
        precision = "16-bit"
        if inputs:
            first = next(iter(inputs.values()))
            data_kind = getattr(first, "data_kind", data_kind)
            precision = getattr(first, "precision", precision)
            for resource in inputs.values():
                provenance |= resource.provenance
        wrapped_state = {
            name: CpuImage(
                np.ascontiguousarray(array, dtype=np.float32),
                TextureFormat.RGBA16F,
                f"{cache_key}:state:{name}",
                provenance,
                "color",
                precision,
            )
            for name, array in state.items()
        }
        wrapped_output = CpuImage(
            np.ascontiguousarray(output, dtype=np.float32),
            logical_format,
            f"{cache_key}:output",
            provenance,
            data_kind,
            precision,
        )
        return wrapped_state, wrapped_output

    def _store_checkpoint(self, track: SimulationTrack, frame: int, cpu_backend) -> None:
        if track.output is None:
            return
        state = {
            name: self._copy_cpu(cpu_backend.to_cpu(resource), f"checkpoint:{track.node_uid}:{frame}:{name}")
            for name, resource in track.state.items()
        }
        output = self._copy_cpu(
            cpu_backend.to_cpu(track.output), f"checkpoint:{track.node_uid}:{frame}:output"
        )
        track.checkpoints[frame] = SimulationCheckpoint(frame, state, output)
        track.checkpoints.move_to_end(frame)
        while len(track.checkpoints) > self.maximum_checkpoints:
            oldest = next(iter(track.checkpoints))
            if oldest == 0 and len(track.checkpoints) > 1:
                track.checkpoints.move_to_end(oldest)
                oldest = next(iter(track.checkpoints))
            track.checkpoints.pop(oldest, None)

    @staticmethod
    def _nearest_checkpoint(track: SimulationTrack, target_frame: int) -> SimulationCheckpoint | None:
        frames = [frame for frame in track.checkpoints if frame <= target_frame]
        if not frames:
            return None
        return track.checkpoints[max(frames)]

    @staticmethod
    def _copy_cpu(image: CpuImage, cache_key: str) -> CpuImage:
        return CpuImage(
            np.ascontiguousarray(image.array.copy(), dtype=np.float32),
            image.logical_format,
            cache_key,
            image.provenance,
            image.data_kind,
            image.precision,
        )

    @staticmethod
    def _resource_ids(state: Mapping[str, ImageResource], output: ImageResource | None) -> set[int]:
        values = list(state.values())
        if output is not None:
            values.append(output)
        return {id(value) for value in values}

    def _release_replaced(
        self,
        old_state: Mapping[str, ImageResource],
        old_output: ImageResource | None,
        new_state: Mapping[str, ImageResource],
        new_output: ImageResource | None,
    ) -> None:
        retained = self._resource_ids(new_state, new_output)
        released: set[int] = set()
        for resource in list(old_state.values()) + ([old_output] if old_output is not None else []):
            if id(resource) in retained or id(resource) in released:
                continue
            released.add(id(resource))
            if isinstance(resource, GpuImage):
                resource.release()

    def _release_current(self, track: SimulationTrack) -> None:
        self._release_replaced(track.state, track.output, {}, None)
        track.state = {}
        track.output = None

    def _release_track(self, track: SimulationTrack) -> None:
        self._release_current(track)
        track.checkpoints.clear()

    def _trim_tracks(self) -> None:
        while len(self._tracks) > self.maximum_tracks:
            _key, track = self._tracks.popitem(last=False)
            self._release_track(track)
