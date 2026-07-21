from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..document import DocumentSettings
from .spinboxes import CompactDoubleSpinBox, CompactSpinBox


class TimelinePanel(QWidget):
    """Compact timeline transport shared by every graph document."""

    frameChanged = Signal(int)
    playToggled = Signal(bool)
    stopRequested = Signal()
    settingsChanged = Signal()
    performanceSettingsChanged = Signal()
    resetSimulationsRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._document = DocumentSettings()
        self._updating = False
        self._playing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(5)

        transport = QHBoxLayout()
        transport.setSpacing(5)
        self.first_button = QPushButton()
        self.previous_button = QPushButton()
        self.play_button = QPushButton()
        self.play_button.setCheckable(True)
        self.stop_button = QPushButton()
        self.reset_simulations_button = QPushButton()
        self.next_button = QPushButton()
        self.last_button = QPushButton()

        style = self.style()
        self.first_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.previous_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
        self.play_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.stop_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.reset_simulations_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.next_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward))
        self.last_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))

        self.first_button.setToolTip("Jump to loop start")
        self.previous_button.setToolTip("Previous frame")
        self.play_button.setToolTip("Play / pause")
        self.stop_button.setToolTip("Stop and return to loop start")
        self.reset_simulations_button.setToolTip("Reset all stateful simulations to frame zero")
        self.next_button.setToolTip("Next frame")
        self.last_button.setToolTip("Jump to loop end")
        for button in (
            self.first_button,
            self.previous_button,
            self.play_button,
            self.stop_button,
            self.reset_simulations_button,
            self.next_button,
            self.last_button,
        ):
            button.setFixedSize(38, 32)
            button.setIconSize(QSize(18, 18))
            transport.addWidget(button)

        transport.addSpacing(8)
        transport.addWidget(QLabel("Frame"))
        self.frame_spin = CompactSpinBox()
        self.frame_spin.setRange(0, self._document.last_frame)
        self.frame_spin.setKeyboardTracking(False)
        self.frame_spin.setFixedWidth(86)
        transport.addWidget(self.frame_spin)
        self.time_label = QLabel("0.000 s")
        self.time_label.setObjectName("muted")
        self.time_label.setMinimumWidth(90)
        transport.addWidget(self.time_label)
        transport.addStretch(1)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.setChecked(True)
        transport.addWidget(self.loop_check)
        transport.addWidget(QLabel("Start"))
        self.loop_start = CompactSpinBox()
        self.loop_start.setRange(0, self._document.last_frame)
        self.loop_start.setValue(self._document.loop_start_frame)
        self.loop_start.setFixedWidth(76)
        transport.addWidget(self.loop_start)
        transport.addWidget(QLabel("End"))
        self.loop_end = CompactSpinBox()
        self.loop_end.setRange(0, self._document.last_frame)
        self.loop_end.setValue(self._document.loop_end_frame)
        self.loop_end.setFixedWidth(76)
        transport.addWidget(self.loop_end)
        transport.addWidget(QLabel("Speed"))
        self.speed = CompactDoubleSpinBox()
        self.speed.setRange(0.05, 8.0)
        self.speed.setSingleStep(0.05)
        self.speed.setDecimals(2)
        self.speed.setSuffix("×")
        self.speed.setValue(self._document.playback_speed)
        self.speed.setFixedWidth(78)
        transport.addWidget(self.speed)

        transport.addWidget(QLabel("Playback"))
        self.playback_mode = QComboBox()
        self.playback_mode.addItems(("Real-time", "Every frame"))
        self.playback_mode.setToolTip(
            "Real-time keeps timeline timing exact and may skip display frames. "
            "Every frame waits for each rendered frame before advancing."
        )
        self.playback_mode.setFixedWidth(112)
        transport.addWidget(self.playback_mode)

        self.profiler_check = QCheckBox("Profiler")
        self.profiler_check.setToolTip("Show compact playback and graph evaluation timing.")
        transport.addWidget(self.profiler_check)
        outer.addLayout(transport)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._document.last_frame)
        self.slider.setTracking(True)
        outer.addWidget(self.slider)

        self.info_label = QLabel()
        self.info_label.setObjectName("muted")
        outer.addWidget(self.info_label)

        self.performance_label = QLabel()
        self.performance_label.setObjectName("muted")
        self.performance_label.setTextFormat(Qt.TextFormat.PlainText)
        self.performance_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.performance_label.setVisible(False)
        outer.addWidget(self.performance_label)

        self.first_button.clicked.connect(lambda: self.set_frame(self.loop_start.value()))
        self.previous_button.clicked.connect(lambda: self.set_frame(self.frame_spin.value() - 1))
        self.next_button.clicked.connect(lambda: self.set_frame(self.frame_spin.value() + 1))
        self.last_button.clicked.connect(lambda: self.set_frame(self.loop_end.value()))
        self.play_button.toggled.connect(self._play_toggled)
        self.stop_button.clicked.connect(self._stop)
        self.reset_simulations_button.clicked.connect(self.resetSimulationsRequested.emit)
        self.slider.valueChanged.connect(self._slider_changed)
        self.frame_spin.valueChanged.connect(self._spin_changed)
        self.loop_start.valueChanged.connect(self._loop_changed)
        self.loop_end.valueChanged.connect(self._loop_changed)
        self.speed.valueChanged.connect(self._speed_changed)
        self.playback_mode.currentTextChanged.connect(lambda _text: self.performanceSettingsChanged.emit())
        self.profiler_check.toggled.connect(self._profiler_toggled)
        self.loop_check.toggled.connect(lambda _checked: self.settingsChanged.emit())
        self.set_document(self._document)

    @property
    def frame(self) -> int:
        return self.frame_spin.value()

    @property
    def loop_enabled(self) -> bool:
        return self.loop_check.isChecked()

    @property
    def playback_speed(self) -> float:
        return self.speed.value()

    @property
    def playback_mode_name(self) -> str:
        return str(self.playback_mode.currentText() or "Real-time")

    @property
    def profiler_enabled(self) -> bool:
        return self.profiler_check.isChecked()

    def set_playback_mode(self, mode: str) -> None:
        text = "Every frame" if str(mode).lower().startswith("every") else "Real-time"
        self.playback_mode.blockSignals(True)
        self.playback_mode.setCurrentText(text)
        self.playback_mode.blockSignals(False)

    def set_profiler_enabled(self, enabled: bool) -> None:
        self.profiler_check.blockSignals(True)
        self.profiler_check.setChecked(bool(enabled))
        self.profiler_check.blockSignals(False)
        self.performance_label.setVisible(bool(enabled))

    def set_performance_text(self, text: str) -> None:
        self.performance_label.setText(str(text or ""))
        self.performance_label.setVisible(self.profiler_enabled and bool(text))

    def set_document(self, document: DocumentSettings) -> None:
        self._document = document
        last = document.last_frame
        self._updating = True
        try:
            self.slider.setRange(0, last)
            self.frame_spin.setRange(0, last)
            self.loop_start.setRange(0, last)
            self.loop_end.setRange(0, last)
            self.loop_start.setValue(min(document.loop_start_frame, last))
            self.loop_end.setValue(min(max(document.loop_end_frame, self.loop_start.value()), last))
            self.speed.setValue(document.playback_speed)
            self.set_frame(min(self.frame, last), emit=False)
        finally:
            self._updating = False
        self._refresh_info()

    def set_frame(self, frame: int, *, emit: bool = True) -> None:
        frame = min(max(int(frame), 0), self._document.last_frame)
        self._updating = True
        try:
            self.slider.setValue(frame)
            self.frame_spin.setValue(frame)
        finally:
            self._updating = False
        self.time_label.setText(f"{self._document.time_for_frame(frame):.3f} s")
        self._refresh_info()
        if emit:
            self.frameChanged.emit(frame)

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.play_button.blockSignals(True)
        self.play_button.setChecked(self._playing)
        icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaPause if self._playing
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_button.setIcon(icon)
        self.play_button.blockSignals(False)

    def _slider_changed(self, value: int) -> None:
        if not self._updating:
            self.set_frame(value)

    def _spin_changed(self, value: int) -> None:
        if not self._updating:
            self.set_frame(value)

    def _play_toggled(self, checked: bool) -> None:
        self.set_playing(checked)
        self.playToggled.emit(checked)

    def _stop(self) -> None:
        self.set_playing(False)
        self.stopRequested.emit()

    def _loop_changed(self) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            if self.sender() is self.loop_start and self.loop_start.value() > self.loop_end.value():
                self.loop_end.setValue(self.loop_start.value())
            elif self.sender() is self.loop_end and self.loop_end.value() < self.loop_start.value():
                self.loop_start.setValue(self.loop_end.value())
        finally:
            self._updating = False
        self._refresh_info()
        self.settingsChanged.emit()

    def _speed_changed(self, value: float) -> None:
        if self._updating:
            return
        self._document.playback_speed = float(value)
        self.settingsChanged.emit()

    def _profiler_toggled(self, enabled: bool) -> None:
        self.performance_label.setVisible(bool(enabled) and bool(self.performance_label.text()))
        self.performanceSettingsChanged.emit()

    def _refresh_info(self) -> None:
        self.info_label.setText(
            f"{self._document.frames_per_second:g} FPS · {self._document.duration_seconds:g} s · "
            f"frames 0–{self._document.last_frame} · loop {self.loop_start.value()}–{self.loop_end.value()}"
        )
