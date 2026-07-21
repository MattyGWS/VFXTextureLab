from __future__ import annotations

import threading
import time


from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..animation_export import assemble_flipbook
from .evaluator import EvaluationCancelled, EvaluationResult, GraphEvaluator, GraphSnapshot
from .formats import TextureFormat


class _WorkerSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int, str)
    nodeState = Signal(int, str, bool, int, int, str)


class _EvaluationWorker(QRunnable):
    def __init__(
        self,
        request_id: int,
        evaluator: GraphEvaluator,
        snapshot: GraphSnapshot,
        node_uid: str | None,
        width: int,
        height: int,
        precision: TextureFormat,
        colour_space: str,
        animation: dict,
        cancel_event: threading.Event,
        *,
        prepare_display: bool = False,
        display_width: int | None = None,
        display_height: int | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.evaluator = evaluator
        self.snapshot = snapshot
        self.node_uid = node_uid
        self.width = width
        self.height = height
        self.precision = precision
        self.colour_space = colour_space
        self.animation = animation
        self.cancel_event = cancel_event
        self.prepare_display = bool(prepare_display)
        self.display_width = display_width
        self.display_height = display_height
        self.signals = _WorkerSignals()
        self._last_node_state_emit: dict[str, float] = {}

    def _emit_node_state(
        self,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        # Painting a graph node thousands of times per second can cost more UI
        # time than the progress indicator is worth. Keep start/final/clear
        # events exact and cap intermediate visual updates to roughly 12 Hz.
        now = time.perf_counter()
        last = self._last_node_state_emit.get(node_uid, 0.0)
        is_boundary = (not active) or target <= 0 or current <= 0 or current >= target
        if active and not is_boundary and (now - last) < (1.0 / 12.0):
            return
        self._last_node_state_emit[node_uid] = now
        try:
            self.signals.nodeState.emit(
                self.request_id, node_uid, active, current, target, message
            )
        except RuntimeError:
            return

    def run(self) -> None:
        try:
            collect_traces = bool(self.animation.get("collect_traces", True))
            result = self.evaluator.evaluate_snapshot(
                self.snapshot,
                self.node_uid,
                self.width,
                self.height,
                cancel_check=self.cancel_event.is_set,
                progress_callback=(
                    (lambda current, target, name: self.signals.progress.emit(
                        self.request_id, current, target, name
                    )) if collect_traces else None
                ),
                node_activity_callback=self._emit_node_state if collect_traces else None,
                precision=self.precision,
                colour_space=self.colour_space,
                prepare_display=self.prepare_display,
                display_width=self.display_width,
                display_height=self.display_height,
                **self.animation,
            )
            if not self.cancel_event.is_set():
                try:
                    self.signals.finished.emit(self.request_id, result)
                except RuntimeError:
                    return
        except EvaluationCancelled:
            return
        except Exception as exc:
            try:
                self.signals.failed.emit(self.request_id, f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                return


class _FlipbookEvaluationWorker(QRunnable):
    """Render a low-resolution sprite sheet without blocking the Qt UI thread."""

    def __init__(
        self,
        request_id: int,
        evaluator: GraphEvaluator,
        snapshot: GraphSnapshot,
        node_uid: str,
        width: int,
        height: int,
        precision: TextureFormat,
        colour_space: str,
        animations: list[dict],
        columns: int,
        rows: int,
        padding: int,
        background: str,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.evaluator = evaluator
        self.snapshot = snapshot
        self.node_uid = node_uid
        self.width = width
        self.height = height
        self.precision = precision
        self.colour_space = colour_space
        self.animations = animations
        self.columns = columns
        self.rows = rows
        self.padding = padding
        self.background = background
        self.cancel_event = cancel_event
        self.signals = _WorkerSignals()

    def run(self) -> None:
        started = time.perf_counter()
        try:
            images = []
            results: list[EvaluationResult] = []
            for animation in self.animations:
                if self.cancel_event.is_set():
                    raise EvaluationCancelled()
                result = self.evaluator.evaluate_snapshot(
                    self.snapshot,
                    self.node_uid,
                    self.width,
                    self.height,
                    cancel_check=self.cancel_event.is_set,
                    precision=self.precision,
                    colour_space=self.colour_space,
                    **animation,
                )
                if result.error:
                    if not self.cancel_event.is_set():
                        self.signals.finished.emit(self.request_id, result)
                    return
                images.append(result.image.copy())
                results.append(result)

            if self.cancel_event.is_set():
                raise EvaluationCancelled()
            sheet = assemble_flipbook(
                images,
                columns=self.columns,
                rows=self.rows,
                padding=self.padding,
                background=self.background,
            )
            backends = {result.backend for result in results}
            backend = next(iter(backends)) if len(backends) == 1 else "Hybrid"
            fallbacks = tuple(sorted({item for result in results for item in result.fallback_nodes}))
            combined = EvaluationResult(
                image=sheet,
                backend=backend,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                gpu_nodes=sum(result.gpu_nodes for result in results),
                cpu_nodes=sum(result.cpu_nodes for result in results),
                signal_nodes=sum(result.signal_nodes for result in results),
                cache_hits=sum(result.cache_hits for result in results),
                fallback_nodes=fallbacks,
                reachable_nodes=max((result.reachable_nodes for result in results), default=0),
                frame_number=int(self.animations[0].get("frame_number", 0)) if self.animations else 0,
                time_seconds=float(self.animations[0].get("time_seconds", 0.0)) if self.animations else 0.0,
                data_kind=results[0].data_kind if results else "grayscale",
                precision=results[0].precision if results else "16-bit",
                simulation_steps=sum(result.simulation_steps for result in results),
                simulation_nodes=sum(result.simulation_nodes for result in results),
                simulation_checkpoint=max((result.simulation_checkpoint for result in results), default=-1),
            )
            if not self.cancel_event.is_set():
                self.signals.finished.emit(self.request_id, combined)
        except EvaluationCancelled:
            return
        except Exception as exc:
            try:
                self.signals.failed.emit(self.request_id, f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                return


class AsyncEvaluationController(QObject):
    resultReady = Signal(object)
    evaluationStarted = Signal()
    evaluationFailed = Signal(str)
    evaluationProgress = Signal(int, int, str)
    evaluationNodeState = Signal(str, bool, int, int, str)

    def __init__(self, evaluator: GraphEvaluator, parent=None) -> None:
        super().__init__(parent)
        self.evaluator = evaluator
        self.pool = QThreadPool.globalInstance()
        self._request_id = 0
        self._cancel_event: threading.Event | None = None

    def request(
        self,
        snapshot: GraphSnapshot,
        node_uid: str | None,
        width: int,
        height: int,
        precision: TextureFormat = TextureFormat.RGBA16F,
        colour_space: str = "Linear",
        *,
        time_seconds: float = 0.0,
        frame_number: int = 0,
        frame_position: float | None = None,
        delta_time: float = 1.0 / 30.0,
        duration_seconds: float = 4.0,
        normalised_time: float = 0.0,
        loop_phase: float = 0.0,
        frames_per_second: float = 30.0,
        document_frame_count: int = 120,
        loop_start_frame: int = 0,
        loop_end_frame: int = 119,
        render_mode: str = "preview",
        interactive_node_uid: str | None = None,
        output_name: str = "Image",
        prepare_display: bool = False,
        display_width: int | None = None,
        display_height: int | None = None,
        collect_traces: bool = True,
        priority: int = 0,
    ) -> int:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._request_id += 1
        request_id = self._request_id
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        worker = _EvaluationWorker(
            request_id,
            self.evaluator,
            snapshot,
            node_uid,
            width,
            height,
            precision,
            colour_space,
            {
                "time_seconds": time_seconds,
                "frame_number": frame_number,
                "frame_position": frame_number if frame_position is None else frame_position,
                "delta_time": delta_time,
                "duration_seconds": duration_seconds,
                "normalised_time": normalised_time,
                "loop_phase": loop_phase,
                "frames_per_second": frames_per_second,
                "document_frame_count": document_frame_count,
                "loop_start_frame": loop_start_frame,
                "loop_end_frame": loop_end_frame,
                "render_mode": str(render_mode or "preview"),
                "interactive_node_uid": str(interactive_node_uid) if interactive_node_uid else None,
                "output_name": str(output_name or "Image"),
                "collect_traces": bool(collect_traces),
            },
            cancel_event,
            prepare_display=prepare_display,
            display_width=display_width,
            display_height=display_height,
        )
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        worker.signals.progress.connect(self._progress)
        worker.signals.nodeState.connect(self._node_state)
        self.evaluationStarted.emit()
        self.pool.start(worker, int(priority))
        return request_id

    def request_flipbook(
        self,
        snapshot: GraphSnapshot,
        node_uid: str,
        width: int,
        height: int,
        animations: list[dict],
        *,
        columns: int,
        rows: int,
        padding: int = 0,
        background: str = "#00000000",
        precision: TextureFormat = TextureFormat.RGBA16F,
        colour_space: str = "Linear",
    ) -> int:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._request_id += 1
        request_id = self._request_id
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        worker = _FlipbookEvaluationWorker(
            request_id,
            self.evaluator,
            snapshot,
            node_uid,
            width,
            height,
            precision,
            colour_space,
            animations,
            max(int(columns), 1),
            max(int(rows), 1),
            max(int(padding), 0),
            background,
            cancel_event,
        )
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        self.evaluationStarted.emit()
        self.pool.start(worker)
        return request_id

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        # Invalidate queued worker signals as well as cooperative evaluation.
        # A worker can finish just before observing its cancel event; advancing
        # the generation prevents that stale result from reaching the preview.
        self._request_id += 1
        self._cancel_event = None

    def _finished(self, request_id: int, result: EvaluationResult) -> None:
        if request_id != self._request_id:
            return
        self.resultReady.emit(result)

    def _progress(self, request_id: int, current: int, target: int, name: str) -> None:
        if request_id != self._request_id:
            return
        self.evaluationProgress.emit(current, target, name)

    def _node_state(
        self,
        request_id: int,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        if request_id != self._request_id:
            return
        self.evaluationNodeState.emit(node_uid, active, current, target, message)

    def _failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self.evaluationFailed.emit(message)
