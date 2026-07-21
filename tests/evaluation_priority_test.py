from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.evaluation_gate import EvaluationGate


def assert_2d_priority_over_queued_3d() -> None:
    gate = EvaluationGate()
    low_holds = threading.Event()
    release_low = threading.Event()
    order: list[str] = []

    def first_3d() -> None:
        with gate.slot(low_priority=True):
            low_holds.set()
            release_low.wait(2.0)

    def direct_2d() -> None:
        with gate.slot(low_priority=False):
            order.append("2d")

    def second_3d() -> None:
        with gate.slot(low_priority=True):
            order.append("3d")

    first = threading.Thread(target=first_3d)
    first.start()
    assert low_holds.wait(1.0)

    high = threading.Thread(target=direct_2d)
    high.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        with gate.condition:
            if gate.waiting_direct > 0:
                break
        time.sleep(0.005)
    else:
        raise AssertionError("2D evaluation did not enter the priority queue")

    second = threading.Thread(target=second_3d)
    second.start()
    release_low.set()
    for thread in (first, high, second):
        thread.join(2.0)
        assert not thread.is_alive()

    assert order == ["2d", "3d"], order


def assert_reentrant_slot() -> None:
    gate = EvaluationGate()
    with gate.slot(low_priority=False):
        with gate.slot(low_priority=False):
            assert gate.depth == 2
    assert gate.owner is None
    assert gate.depth == 0


def main() -> None:
    assert_2d_priority_over_queued_3d()
    assert_reentrant_slot()
    print("evaluation priority test passed")


if __name__ == "__main__":
    main()
