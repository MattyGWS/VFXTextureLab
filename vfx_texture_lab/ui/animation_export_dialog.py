from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..animation_export import (
    AnimationExportRequest,
    LAYOUT_PRESETS,
    SAMPLING_MODES,
    SOURCE_RANGES,
    animation_sample_positions,
)
from ..document import DocumentSettings
from .spinboxes import CompactDoubleSpinBox, CompactSpinBox
from ..exporting import ExportOptions


class AnimationExportDialog(QDialog):
    def __init__(self, outputs: list[tuple[str, str, dict]], document: DocumentSettings, directory: Path, parent=None) -> None:
        super().__init__(parent)
        self.outputs = outputs
        self.document = document
        self.setWindowTitle("Export Animation")
        self.setMinimumWidth(570)

        outer = QVBoxLayout(self)
        info = QLabel(
            "Flipbook frame count is independent of timeline FPS. By default the selected grid samples the document loop evenly, without duplicating the first frame at the end."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        outer.addWidget(info)

        form = QFormLayout()
        self.output = QComboBox()
        for uid, name, _params in outputs:
            self.output.addItem(name, uid)
        self.output.currentIndexChanged.connect(self._load_output_defaults)
        form.addRow("Flipbook output", self.output)

        self.mode = QComboBox()
        self.mode.addItems(("Flipbook", "Image Sequence"))
        self.mode.currentTextChanged.connect(self._refresh_summary)
        form.addRow("Mode", self.mode)

        self.directory = QLineEdit(str(directory))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.directory, 1)
        directory_row.addWidget(browse)
        form.addRow("Output folder", directory_row)

        self.base_name = QLineEdit("animation")
        form.addRow("Base filename", self.base_name)

        self.format = QComboBox()
        self.format.addItems(("PNG", "TGA"))
        self.format.currentTextChanged.connect(self._format_changed)
        form.addRow("Format", self.format)

        self.bit_depth = QComboBox()
        self.bit_depth.addItems(("8-bit", "16-bit"))
        form.addRow("Bit depth", self.bit_depth)

        self.encoding = QComboBox()
        self.encoding.addItems(("Linear", "sRGB"))
        self.encoding.setCurrentText(document.colour_space)
        form.addRow("Colour encoding", self.encoding)

        self.width = CompactSpinBox()
        self.width.setRange(1, 16384)
        self.width.setValue(document.width)
        self.height = CompactSpinBox()
        self.height.setRange(1, 16384)
        self.height.setValue(document.height)
        form.addRow("Frame width", self.width)
        form.addRow("Frame height", self.height)

        self.layout = QComboBox()
        self.layout.addItems((*LAYOUT_PRESETS.keys(), "Custom"))
        self.layout.setCurrentText("8 × 8")
        form.addRow("Layout", self.layout)

        self.columns = CompactSpinBox()
        self.columns.setRange(1, 64)
        self.columns.setValue(8)
        self.rows = CompactSpinBox()
        self.rows.setRange(1, 64)
        self.rows.setValue(8)
        form.addRow("Custom columns", self.columns)
        form.addRow("Custom rows", self.rows)

        self.use_full_grid = QCheckBox("Use every cell in the grid")
        self.use_full_grid.setChecked(True)
        form.addRow("Frame count", self.use_full_grid)
        self.frame_count = CompactSpinBox()
        self.frame_count.setRange(1, 4096)
        self.frame_count.setValue(64)
        form.addRow("Custom frame count", self.frame_count)

        self.source_range = QComboBox()
        self.source_range.addItems(SOURCE_RANGES)
        form.addRow("Source range", self.source_range)

        self.sampling = QComboBox()
        self.sampling.addItems(SAMPLING_MODES)
        form.addRow("Sampling", self.sampling)

        self.include_end = QCheckBox("Duplicate the exact loop endpoint")
        self.include_end.setChecked(False)
        self.include_end.setToolTip("Usually leave this off for looping flipbooks. Turning it on includes both phase 0 and phase 1.")
        form.addRow("Include loop endpoint", self.include_end)

        self.start = CompactSpinBox()
        self.start.setRange(0, document.last_frame)
        self.start.setValue(document.loop_start_frame)
        self.end = CompactSpinBox()
        self.end.setRange(0, document.last_frame)
        self.end.setValue(document.loop_end_frame)
        self.step = CompactSpinBox()
        self.step.setRange(1, max(document.frame_count, 1))
        self.step.setValue(1)
        form.addRow("Custom start frame", self.start)
        form.addRow("Custom end frame", self.end)
        form.addRow("Consecutive frame step", self.step)

        self.padding = CompactSpinBox()
        self.padding.setRange(0, 64)
        form.addRow("Cell padding", self.padding)
        outer.addLayout(form)

        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)

        for control in (
            self.start, self.end, self.step, self.columns, self.rows, self.padding,
            self.width, self.height, self.frame_count,
        ):
            control.valueChanged.connect(self._refresh_summary)
        for control in (self.layout, self.source_range, self.sampling):
            control.currentTextChanged.connect(self._controls_changed)
        self.use_full_grid.toggled.connect(self._controls_changed)
        self.include_end.toggled.connect(self._refresh_summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._load_output_defaults()
        self._format_changed()
        self._controls_changed()

    def _current_output(self) -> tuple[str, str, dict]:
        index = max(self.output.currentIndex(), 0)
        return self.outputs[index]

    def _grid(self) -> tuple[int, int]:
        preset = LAYOUT_PRESETS.get(self.layout.currentText())
        return preset if preset else (self.columns.value(), self.rows.value())

    def _effective_frame_count(self) -> int:
        columns, rows = self._grid()
        return columns * rows if self.use_full_grid.isChecked() else self.frame_count.value()

    def _sample_positions(self) -> list[float]:
        return animation_sample_positions(
            self.document,
            source_range=self.source_range.currentText(),
            sampling_mode=self.sampling.currentText(),
            frame_count=self._effective_frame_count(),
            start_frame=self.start.value(),
            end_frame=self.end.value(),
            frame_step=self.step.value(),
            include_end_frame=self.include_end.isChecked(),
        )

    def _load_output_defaults(self) -> None:
        if not self.outputs:
            return
        _uid, name, params = self._current_output()
        self.base_name.setText(re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "animation")
        layout = str(params.get("layout", "Custom"))
        if layout not in (*LAYOUT_PRESETS.keys(), "Custom"):
            layout = "Custom"
        self.layout.setCurrentText(layout)
        self.columns.setValue(max(int(params.get("columns", 8)), 1))
        self.rows.setValue(max(int(params.get("rows", 8)), 1))
        self.use_full_grid.setChecked(bool(params.get("use_full_grid", True)))
        self.frame_count.setValue(max(int(params.get("frame_count", 64)), 1))
        self.source_range.setCurrentText(str(params.get("source_range", "Document Loop")))
        self.sampling.setCurrentText(str(params.get("sampling", "Evenly Across Range")))
        self.include_end.setChecked(bool(params.get("include_end_frame", False)))
        self.start.setValue(min(max(int(params.get("start_frame", self.document.loop_start_frame)), 0), self.document.last_frame))
        self.end.setValue(min(max(int(params.get("end_frame", self.document.loop_end_frame)), 0), self.document.last_frame))
        self.step.setValue(max(int(params.get("frame_step", 1)), 1))
        self.padding.setValue(max(int(params.get("padding", 0)), 0))
        self._controls_changed()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose animation export folder", self.directory.text())
        if selected:
            self.directory.setText(selected)

    def _format_changed(self) -> None:
        tga = self.format.currentText() == "TGA"
        self.bit_depth.setCurrentText("8-bit" if tga else self.bit_depth.currentText())
        self.bit_depth.setEnabled(not tga)

    def _controls_changed(self, *_args) -> None:
        custom_layout = self.layout.currentText() == "Custom"
        self.columns.setEnabled(custom_layout)
        self.rows.setEnabled(custom_layout)
        self.frame_count.setEnabled(not self.use_full_grid.isChecked())
        custom_range = self.source_range.currentText() == "Custom Frame Range"
        self.start.setEnabled(custom_range)
        self.end.setEnabled(custom_range)
        consecutive = self.sampling.currentText() == "Consecutive Timeline Frames"
        self.step.setEnabled(consecutive)
        self.include_end.setEnabled(not consecutive)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        samples = self._sample_positions()
        columns, rows = self._grid()
        if self.mode.currentText() == "Flipbook":
            sheet_width = columns * self.width.value() + max(columns - 1, 0) * self.padding.value()
            sheet_height = rows * self.height.value() + max(rows - 1, 0) * self.padding.value()
            endpoint = "including endpoint" if self.include_end.isChecked() else "exclusive endpoint"
            self.summary.setText(
                f"{len(samples)} sample(s) · capacity {columns * rows} · sprite sheet {sheet_width} × {sheet_height} · "
                f"{self.sampling.currentText()} from {self.source_range.currentText()} ({endpoint})"
            )
        else:
            self.summary.setText(
                f"{len(samples)} numbered image(s), each {self.width.value()} × {self.height.value()} · "
                f"{self.sampling.currentText()} from {self.source_range.currentText()}"
            )

    def _validate_accept(self) -> None:
        samples = self._sample_positions()
        if not samples:
            QMessageBox.warning(self, "Invalid sample range", "The selected source range contains no samples.")
            return
        columns, rows = self._grid()
        if self.mode.currentText() == "Flipbook" and len(samples) > columns * rows:
            minimum_rows = math.ceil(len(samples) / columns)
            QMessageBox.warning(
                self,
                "Frames do not fit",
                f"The export contains {len(samples)} frames but the sheet holds {columns * rows}. Increase Rows to at least {minimum_rows}, use a larger preset, or lower Frame count.",
            )
            return
        if not self.directory.text().strip():
            QMessageBox.warning(self, "Missing output folder", "Choose an output folder.")
            return
        self.accept()

    def request(self) -> AnimationExportRequest:
        uid, name, params = self._current_output()
        bit_depth = 16 if self.bit_depth.currentText().startswith("16") else 8
        columns, rows = self._grid()
        samples = tuple(self._sample_positions())
        return AnimationExportRequest(
            node_uid=uid,
            output_name=name,
            mode=self.mode.currentText(),
            directory=Path(self.directory.text()).expanduser(),
            base_name=re.sub(r"[^A-Za-z0-9._-]+", "_", self.base_name.text().strip()).strip("._") or "animation",
            width=self.width.value(),
            height=self.height.value(),
            start_frame=self.start.value(),
            end_frame=self.end.value(),
            frame_step=self.step.value(),
            columns=columns,
            rows=rows,
            padding=self.padding.value(),
            background=str(params.get("background", "#00000000")),
            options=ExportOptions(
                format_name=self.format.currentText(),
                bit_depth=bit_depth,
                channels="RGBA",
                colour_encoding=self.encoding.currentText(),
            ),
            sample_positions=samples,
            sampling_mode=self.sampling.currentText(),
        )
