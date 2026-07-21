from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator


class EvaluationGateCancelled(RuntimeError):
    """Raised when a queued evaluation is superseded before it can run."""


class EvaluationGate:
    """Fair, re-entrant execution gate with direct-preview priority.

    Only one graph solve may own shared renderer/cache resources at a time.
    Low-priority automatic 3D material and histogram work yields whenever
    direct 2D preview, playback, or export work is waiting.
    """

    def __init__(self) -> None:
        self.condition = threading.Condition(threading.Lock())
        self.owner: int | None = None
        self.depth = 0
        self.waiting_direct = 0

    @contextmanager
    def slot(
        self,
        *,
        low_priority: bool,
        cancel_check: Callable[[], bool] | None = None,
        wait_callback: Callable[[float], None] | None = None,
    ) -> Iterator[float]:
        thread_id = threading.get_ident()
        started = time.perf_counter()
        reentrant = False

        with self.condition:
            if self.owner == thread_id:
                self.depth += 1
                reentrant = True
            else:
                if not low_priority:
                    self.waiting_direct += 1
                try:
                    while self.owner is not None or (
                        low_priority and self.waiting_direct > 0
                    ):
                        if cancel_check is not None and cancel_check():
                            raise EvaluationGateCancelled()
                        self.condition.wait(timeout=0.025)
                        waited_ms = (time.perf_counter() - started) * 1000.0
                        if waited_ms >= 180.0 and wait_callback is not None:
                            wait_callback(waited_ms)
                    self.owner = thread_id
                    self.depth = 1
                finally:
                    if not low_priority:
                        self.waiting_direct = max(self.waiting_direct - 1, 0)

        wait_ms = 0.0 if reentrant else (time.perf_counter() - started) * 1000.0
        try:
            yield wait_ms
        finally:
            with self.condition:
                if self.owner == thread_id:
                    self.depth -= 1
                    if self.depth <= 0:
                        self.owner = None
                        self.depth = 0
                        self.condition.notify_all()
