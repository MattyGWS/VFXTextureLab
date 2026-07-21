from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..document import DocumentSettings
from .spinboxes import CompactDoubleSpinBox, CompactSpinBox


class DocumentSettingsDialog(QDialog):
    PRESETS = {
        "Square 1024": (1024, 1024),
        "Square 2048": (2048, 2048),
        "Trail 2048 × 512": (2048, 512),
        "Beam 2048 × 256": (2048, 256),
        "Flipbook 2048 × 2048": (2048, 2048),
    }
    ANIMATION_PRESETS = {
        "1 second @ 30 FPS": (30.0, 1.0),
        "2 seconds @ 30 FPS": (30.0, 2.0),
        "4 seconds @ 30 FPS": (30.0, 4.0),
        "1 second @ 60 FPS": (60.0, 1.0),
        "2 seconds @ 60 FPS": (60.0, 2.0),
        "4 seconds @ 60 FPS": (60.0, 4.0),
    }

    def __init__(self, settings: DocumentSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Settings")
        self.setMinimumWidth(470)

        outer = QVBoxLayout(self)
        info = QLabel(
            "The document size is the full-resolution target. Interactive previews are evaluated at a cheaper, aspect-correct resolution. Animation settings belong to the graph and drive the timeline and flipbook export."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        outer.addWidget(info)

        texture_group = QGroupBox("Texture")
        form = QFormLayout(texture_group)
        preset_row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("Custom")
        self.preset.addItems(self.PRESETS)
        apply_preset = QPushButton("Apply")
        apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.preset, 1)
        preset_row.addWidget(apply_preset)
        form.addRow("Preset", preset_row)

        self.width = CompactSpinBox()
        self.width.setRange(1, 16384)
        self.width.setValue(settings.width)
        self.height = CompactSpinBox()
        self.height.setRange(1, 16384)
        self.height.setValue(settings.height)
        form.addRow("Width", self.width)
        form.addRow("Height", self.height)

        self.preview = QComboBox()
        for value in (128, 256, 512, 1024, 2048, 4096):
            self.preview.addItem(str(value), value)
        index = self.preview.findData(settings.preview_max_dimension)
        if index < 0:
            self.preview.addItem(str(settings.preview_max_dimension), settings.preview_max_dimension)
            index = self.preview.count() - 1
        self.preview.setCurrentIndex(index)
        form.addRow("Preview max dimension", self.preview)

        self.precision = QComboBox()
        self.precision.addItems(("16-bit float", "32-bit float"))
        self.precision.setCurrentText(settings.working_precision)
        self.precision.setToolTip("16-bit float is appropriate for most VFX work. 32-bit float is available for precision-sensitive graphs.")
        form.addRow("Working precision", self.precision)

        self.colour_space = QComboBox()
        self.colour_space.addItems(("Linear", "sRGB"))
        self.colour_space.setCurrentText(settings.colour_space)
        self.colour_space.setToolTip(
            "Graph colour-processing metadata. Export encoding is controlled semantically by each output: "
            "Colour may be sRGB, while normals, masks and scalar data remain numeric/linear."
        )
        form.addRow("Working colour space", self.colour_space)

        self.default_tiling = QCheckBox("New tile-aware nodes default to wrapping")
        self.default_tiling.setChecked(settings.default_tiling)
        form.addRow("Default tiling", self.default_tiling)

        self.geometric_rasterization = QComboBox()
        self.geometric_rasterization.addItems(("Antialiased", "Pixel Exact"))
        self.geometric_rasterization.setCurrentText(settings.default_geometric_rasterization)
        self.geometric_rasterization.setToolTip(
            "Default edge rasterisation for newly created analytic Shape, Polygon, Polygon Burst and Tile Sampler nodes. "
            "Antialiased stores fractional pixel coverage; Pixel Exact stores hard binary edges when Edge Softness is zero."
        )
        form.addRow("Geometric rasterisation", self.geometric_rasterization)
        outer.addWidget(texture_group)

        animation_group = QGroupBox("Animation")
        animation_form = QFormLayout(animation_group)
        animation_preset_row = QHBoxLayout()
        self.animation_preset = QComboBox()
        self.animation_preset.addItem("Custom")
        self.animation_preset.addItems(self.ANIMATION_PRESETS)
        animation_apply = QPushButton("Apply")
        animation_apply.clicked.connect(self._apply_animation_preset)
        animation_preset_row.addWidget(self.animation_preset, 1)
        animation_preset_row.addWidget(animation_apply)
        animation_form.addRow("Preset", animation_preset_row)

        animation_note = QLabel("Timeline FPS controls playback precision. Flipbook frame count is configured independently on Flipbook Generator.")
        animation_note.setWordWrap(True)
        animation_note.setObjectName("muted")
        animation_form.addRow(animation_note)

        self.fps = CompactDoubleSpinBox()
        self.fps.setRange(1.0, 240.0)
        self.fps.setDecimals(3)
        self.fps.setSingleStep(1.0)
        self.fps.setValue(settings.frames_per_second)
        self.fps.setSuffix(" FPS")
        animation_form.addRow("Frame rate", self.fps)

        self.duration = CompactDoubleSpinBox()
        self.duration.setRange(0.01, 3600.0)
        self.duration.setDecimals(3)
        self.duration.setSingleStep(0.25)
        self.duration.setValue(settings.duration_seconds)
        self.duration.setSuffix(" s")
        animation_form.addRow("Duration", self.duration)

        self.loop_start = CompactSpinBox()
        self.loop_end = CompactSpinBox()
        initial_last = max(0, round(settings.frames_per_second * settings.duration_seconds) - 1)
        self.loop_start.setRange(0, initial_last)
        self.loop_end.setRange(0, initial_last)
        self.loop_start.setValue(settings.loop_start_frame)
        self.loop_end.setValue(settings.loop_end_frame)
        animation_form.addRow("Loop start frame", self.loop_start)
        animation_form.addRow("Loop end frame", self.loop_end)

        self.playback_speed = CompactDoubleSpinBox()
        self.playback_speed.setRange(0.05, 8.0)
        self.playback_speed.setDecimals(2)
        self.playback_speed.setSingleStep(0.05)
        self.playback_speed.setValue(settings.playback_speed)
        self.playback_speed.setSuffix("×")
        animation_form.addRow("Playback speed", self.playback_speed)
        outer.addWidget(animation_group)

        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        for control in (self.width, self.height, self.fps, self.duration):
            control.valueChanged.connect(self._refresh_summary)
        self.preview.currentIndexChanged.connect(self._refresh_summary)
        self.precision.currentTextChanged.connect(self._refresh_summary)
        self.loop_start.valueChanged.connect(self._normalise_loop)
        self.loop_end.valueChanged.connect(self._normalise_loop)
        self._refresh_summary()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _apply_preset(self) -> None:
        values = self.PRESETS.get(self.preset.currentText())
        if values:
            self.width.setValue(values[0])
            self.height.setValue(values[1])

    def _apply_animation_preset(self) -> None:
        values = self.ANIMATION_PRESETS.get(self.animation_preset.currentText())
        if not values:
            return
        self.fps.setValue(values[0])
        self.duration.setValue(values[1])
        last = self._frame_count() - 1
        self.loop_start.setValue(0)
        self.loop_end.setValue(last)

    def _frame_count(self) -> int:
        return max(1, round(self.fps.value() * self.duration.value()))

    def _normalise_loop(self) -> None:
        sender = self.sender()
        if sender is self.loop_start and self.loop_start.value() > self.loop_end.value():
            self.loop_end.blockSignals(True)
            self.loop_end.setValue(self.loop_start.value())
            self.loop_end.blockSignals(False)
        elif sender is self.loop_end and self.loop_end.value() < self.loop_start.value():
            self.loop_start.blockSignals(True)
            self.loop_start.setValue(self.loop_end.value())
            self.loop_start.blockSignals(False)

    def _refresh_summary(self) -> None:
        width = self.width.value()
        height = self.height.value()
        maximum = int(self.preview.currentData())
        scale = min(1.0, maximum / max(width, height))
        pw, ph = max(1, round(width * scale)), max(1, round(height * scale))
        bytes_per_pixel = 16 if self.precision.currentText() == "32-bit float" else 8
        mib = width * height * bytes_per_pixel / 1048576
        last = self._frame_count() - 1
        self.loop_start.setRange(0, last)
        self.loop_end.setRange(0, last)
        if self.loop_end.value() > last:
            self.loop_end.setValue(last)
        if self.loop_end.value() < self.loop_start.value():
            self.loop_end.setValue(self.loop_start.value())
        self.summary.setText(
            f"Interactive preview: {pw} × {ph} · One full RGBA intermediate: approximately {mib:.1f} MiB · "
            f"Animation: {self._frame_count()} frames (0–{last})"
        )

    def result_settings(self) -> DocumentSettings:
        settings = DocumentSettings(
            width=self.width.value(),
            height=self.height.value(),
            preview_max_dimension=int(self.preview.currentData()),
            working_precision=self.precision.currentText(),
            colour_space=self.colour_space.currentText(),
            default_tiling=self.default_tiling.isChecked(),
            default_geometric_rasterization=self.geometric_rasterization.currentText(),
            frames_per_second=self.fps.value(),
            duration_seconds=self.duration.value(),
            loop_start_frame=self.loop_start.value(),
            loop_end_frame=self.loop_end.value(),
            playback_speed=self.playback_speed.value(),
        )
        settings.normalise()
        return settings
