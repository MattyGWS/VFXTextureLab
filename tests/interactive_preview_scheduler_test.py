from __future__ import annotations

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vfx_texture_lab.main_window import MainWindow


class FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.starts: list[int] = []
        self.stops = 0

    def isActive(self) -> bool:
        return self.active

    def start(self, delay: int = 0) -> None:
        self.active = True
        self.starts.append(int(delay))

    def stop(self) -> None:
        self.active = False
        self.stops += 1

    def fire(self) -> None:
        self.active = False


class PreviewHarness:
    _remaining_dispatch_delay_ms = staticmethod(MainWindow._remaining_dispatch_delay_ms)
    _arm_preview_dispatch = MainWindow._arm_preview_dispatch
    _schedule_preview = MainWindow._schedule_preview
    _dispatch_pending_preview = MainWindow._dispatch_pending_preview
    _continue_pending_preview = MainWindow._continue_pending_preview

    class Controller:
        def __init__(self) -> None:
            self.cancels = 0

        def cancel(self) -> None:
            self.cancels += 1

    def __init__(self) -> None:
        self._playing = False
        self._preview_in_flight = False
        self._preview_pending = False
        self._preview_last_dispatch = 0.0
        self._preview_interval_ms = 33
        self._interactive_preview_interval_ms = 16
        self._interactive_parameter_edit_depth = 0
        self._pending_preview_kind = "frame"
        self._playback_preview_pending = False
        self.preview_timer = FakeTimer()
        self.eval_controller = self.Controller()
        self.evaluations = 0

    def _find_3d_output(self):
        return None

    def _active_is_flipbook(self) -> bool:
        return False

    def _request_playback_preview(self) -> None:
        raise AssertionError("Stopped editing must not use the playback path")

    def _evaluate_active(self) -> None:
        self.evaluations += 1
        self._preview_in_flight = True


class MaterialHarness:
    _remaining_dispatch_delay_ms = staticmethod(MainWindow._remaining_dispatch_delay_ms)
    _arm_material_preview_dispatch = MainWindow._arm_material_preview_dispatch
    _schedule_3d_preview = MainWindow._schedule_3d_preview
    _dispatch_pending_3d_preview = MainWindow._dispatch_pending_3d_preview

    class Panel:
        available = True

    def __init__(self) -> None:
        self._playing = False
        self.active_material = True
        self._material_preview_in_flight = False
        self._material_preview_pending = False
        self._interactive_parameter_edit_depth = 0
        self._preview_in_flight = False
        self._preview_pending = False
        self._material_preview_last_dispatch = 0.0
        self._material_preview_interval_ms = 66
        self._material_preview_idle_delay_ms = 300
        self.material_preview_timer = FakeTimer()
        self.preview_3d_panel = self.Panel()
        self.evaluations = 0

    def _find_3d_output(self):
        return object() if self.active_material else None

    def _request_3d_preview(self) -> None:
        self.evaluations += 1
        self._material_preview_in_flight = True


class InteractionHarness:
    _remaining_dispatch_delay_ms = staticmethod(MainWindow._remaining_dispatch_delay_ms)
    _arm_preview_dispatch = MainWindow._arm_preview_dispatch
    _preempt_material_preview_for_2d = MainWindow._preempt_material_preview_for_2d
    _parameter_interaction_started = MainWindow._parameter_interaction_started
    _parameter_interaction_finished = MainWindow._parameter_interaction_finished

    class Controller:
        def __init__(self) -> None:
            self.cancels = 0

        def cancel(self) -> None:
            self.cancels += 1

    class Scene:
        def __init__(self) -> None:
            self.clears = 0

        def clear_node_evaluation_states(self) -> None:
            self.clears += 1

    class Panel:
        def __init__(self) -> None:
            self.busy = None

        def set_busy(self, value: bool) -> None:
            self.busy = value

    def __init__(self) -> None:
        self._playing = False
        self._interactive_parameter_edit_depth = 0
        self._interactive_parameter_node_uid = None
        self._material_preview_in_flight = True
        self._material_preview_pending = False
        self._pending_material_request_key = "material-old"
        self._last_material_result_key = None
        self._material_node_activity = {}
        self._preview_in_flight = True
        self._preview_pending = False
        self._playback_preview_pending = True
        self._preview_last_dispatch = time.perf_counter()
        self._preview_interval_ms = 33
        self.material_preview_timer = FakeTimer()
        self.material_preview_timer.start(1)
        self.preview_timer = FakeTimer()
        self.material_controller = self.Controller()
        self.eval_controller = self.Controller()
        self.scene = self.Scene()
        self.preview_3d_panel = self.Panel()

    def _find_3d_output(self):
        return None

    def _current_material_request_key(self) -> str:
        return "material-current"

    def _clear_material_node_activity(self) -> None:
        self._material_node_activity.clear()


def assert_heavy_slider_uses_draft_then_exact_release() -> None:
    harness = InteractionHarness()
    harness._parameter_interaction_started("erosion")
    assert harness._interactive_parameter_edit_depth == 1
    assert harness._interactive_parameter_node_uid == "erosion"
    assert harness.material_controller.cancels == 1
    assert not harness._material_preview_in_flight
    assert harness._pending_material_request_key is None
    assert harness._material_preview_pending
    assert harness.preview_3d_panel.busy is False

    harness._parameter_interaction_finished("erosion")
    assert harness._interactive_parameter_edit_depth == 0
    assert harness._interactive_parameter_node_uid is None
    assert harness.eval_controller.cancels == 1
    assert not harness._preview_in_flight
    assert harness._preview_pending
    assert harness.preview_timer.starts[-1] == 0
    assert harness.scene.clears == 1


def assert_2d_latest_value_wins() -> None:
    harness = PreviewHarness()

    # The first edit is leading-edge: it is queued immediately rather than
    # waiting for an inactivity debounce.
    harness._schedule_preview()
    assert harness._preview_pending
    assert harness.preview_timer.starts == [0]

    # More slider events before the dispatch do not restart the timer.
    for _ in range(12):
        harness._schedule_preview()
    assert harness.preview_timer.starts == [0]

    harness.preview_timer.fire()
    harness._dispatch_pending_preview()
    assert harness.evaluations == 1
    assert harness._preview_in_flight
    assert not harness._preview_pending

    # While a render is in flight, any number of edits collapse into one
    # pending newest-state request. No overlapping work is started.
    for _ in range(20):
        harness._schedule_preview()
    assert harness._preview_pending
    assert harness.evaluations == 1
    assert not harness.preview_timer.isActive()

    harness._preview_in_flight = False
    harness._continue_pending_preview()
    assert len(harness.preview_timer.starts) == 2
    assert 0 <= harness.preview_timer.starts[-1] <= harness._preview_interval_ms

    harness.preview_timer.fire()
    harness._dispatch_pending_preview()
    assert harness.evaluations == 2
    assert not harness._preview_pending


def assert_fast_drag_presents_intermediate_frames_without_cancellation_starvation() -> None:
    harness = PreviewHarness()
    harness._interactive_parameter_edit_depth = 1

    harness._schedule_preview()
    assert harness.preview_timer.starts == [0]
    harness.preview_timer.fire()
    harness._dispatch_pending_preview()
    assert harness._preview_in_flight
    assert harness.evaluations == 1

    # A rapid drag may emit many parameter changes while the first draft is in
    # flight. They must collapse into one newest-state request without killing
    # the current frame before it can be shown.
    for _ in range(100):
        harness._schedule_preview()
    assert harness.eval_controller.cancels == 0
    assert harness._preview_in_flight
    assert harness._preview_pending
    assert harness.evaluations == 1

    # Once that intermediate frame is presented, the newest accumulated value
    # is dispatched at the faster interactive cadence.
    harness._preview_in_flight = False
    harness._continue_pending_preview()
    assert harness.preview_timer.starts[-1] <= harness._interactive_preview_interval_ms
    harness.preview_timer.fire()
    harness._dispatch_pending_preview()
    assert harness.evaluations == 2
    assert not harness._preview_pending


def assert_3d_is_coalesced_and_lower_cadence() -> None:
    harness = MaterialHarness()

    # Material evaluation is held behind direct 2D feedback and active slider
    # interactions instead of queueing duplicate heavy graph work.
    harness._preview_pending = True
    harness._schedule_3d_preview()
    assert harness.material_preview_timer.starts == []
    assert harness._material_preview_pending
    harness._preview_pending = False
    harness._interactive_parameter_edit_depth = 1
    harness._arm_material_preview_dispatch()
    assert harness.material_preview_timer.starts == []
    harness._interactive_parameter_edit_depth = 0
    harness._arm_material_preview_dispatch()
    assert harness.material_preview_timer.starts == [300]
    harness.material_preview_timer.fire()
    harness._dispatch_pending_3d_preview()
    assert harness.evaluations == 1

    for _ in range(10):
        harness._schedule_3d_preview()
    assert harness._material_preview_pending
    assert harness.evaluations == 1

    harness._material_preview_in_flight = False
    harness._arm_material_preview_dispatch()
    assert len(harness.material_preview_timer.starts) == 2
    assert harness.material_preview_timer.starts[-1] == harness._material_preview_idle_delay_ms

    # Merely having a Material node somewhere in the graph is no longer enough to
    # schedule it. Once it is not the active double-clicked node, edits are free.
    inactive = MaterialHarness()
    inactive.active_material = False
    inactive._schedule_3d_preview()
    assert not inactive._material_preview_pending
    assert inactive.material_preview_timer.starts == []


def assert_dispatch_delay_math() -> None:
    assert MainWindow._remaining_dispatch_delay_ms(0.0, 33) == 0
    recent = time.perf_counter()
    delay = MainWindow._remaining_dispatch_delay_ms(recent, 33)
    assert 0 <= delay <= 33
    old = time.perf_counter() - 1.0
    assert MainWindow._remaining_dispatch_delay_ms(old, 33) == 0


def main() -> None:
    assert_dispatch_delay_math()
    assert_2d_latest_value_wins()
    assert_fast_drag_presents_intermediate_frames_without_cancellation_starvation()
    assert_heavy_slider_uses_draft_then_exact_release()
    assert_3d_is_coalesced_and_lower_cadence()
    print("interactive preview scheduler test passed")


if __name__ == "__main__":
    main()
