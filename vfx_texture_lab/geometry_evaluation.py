"""Asynchronous, latest-request-wins geometry preview evaluation."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .geometry import GeometryEvaluationCancelled
from .geometry_graph import GeometryEvaluationResult, GeometryEvaluationSession


class _GeometrySignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int, str)
    nodeState = Signal(int, str, bool, int, int, str)


class _GeometryWorker(QRunnable):
    def __init__(
        self,
        request_id: int,
        session: GeometryEvaluationSession,
        node_uid: str,
        output_name: str,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.session = session
        self.node_uid = str(node_uid)
        self.output_name = str(output_name or "Geometry")
        self.signals = _GeometrySignals()
        self._last_node_emit: dict[str, float] = {}

    def emit_progress(self, current: int, target: int, message: str) -> None:
        try:
            self.signals.progress.emit(
                self.request_id, int(current), int(target), str(message or "Geometry")
            )
        except RuntimeError:
            return

    def emit_node_state(
        self,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        now = time.perf_counter()
        last = self._last_node_emit.get(node_uid, 0.0)
        boundary = (not active) or target <= 0 or current <= 0 or current >= target
        if active and not boundary and now - last < (1.0 / 12.0):
            return
        self._last_node_emit[node_uid] = now
        try:
            self.signals.nodeState.emit(
                self.request_id,
                str(node_uid),
                bool(active),
                int(current),
                int(target),
                str(message or ""),
            )
        except RuntimeError:
            return

    def run(self) -> None:
        self.session.progress_callback = self.emit_progress
        self.session.node_activity_callback = self.emit_node_state
        try:
            result = self.session.evaluate(self.node_uid, self.output_name)
            if self.session.cancel_check is not None and self.session.cancel_check():
                return
            try:
                self.signals.finished.emit(self.request_id, result)
            except RuntimeError:
                return
        except GeometryEvaluationCancelled:
            return
        except Exception as exc:
            try:
                self.signals.failed.emit(
                    self.request_id, f"{type(exc).__name__}: {exc}"
                )
            except RuntimeError:
                return


class GeometryEvaluationController(QObject):
    resultReady = Signal(object)
    evaluationStarted = Signal()
    evaluationFailed = Signal(str)
    evaluationProgress = Signal(int, int, str)
    evaluationNodeState = Signal(str, bool, int, int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # One dedicated lane prevents superseded native calls from competing
        # for every CPU core. A request already inside C++ is allowed to finish
        # and populate the collapse cache; queued stale requests then cancel at
        # their first checkpoint and the newest request replays that work.
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._request_id = 0
        self._cancel_event: threading.Event | None = None

    def request(
        self,
        session: GeometryEvaluationSession,
        node_uid: str,
        output_name: str = "Geometry",
        *,
        priority: int = 0,
    ) -> int:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._request_id += 1
        request_id = self._request_id
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        session.cancel_check = cancel_event.is_set
        worker = _GeometryWorker(request_id, session, node_uid, output_name)
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        worker.signals.progress.connect(self._progress)
        worker.signals.nodeState.connect(self._node_state)
        self.evaluationStarted.emit()
        self.pool.start(worker, int(priority))
        return request_id

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._request_id += 1
        self._cancel_event = None

    def _finished(self, request_id: int, result: GeometryEvaluationResult) -> None:
        if request_id != self._request_id:
            return
        self.resultReady.emit(result)

    def _failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self.evaluationFailed.emit(str(message))

    def _progress(self, request_id: int, current: int, target: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self.evaluationProgress.emit(int(current), int(target), str(message))

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
        self.evaluationNodeState.emit(
            str(node_uid), bool(active), int(current), int(target), str(message)
        )
