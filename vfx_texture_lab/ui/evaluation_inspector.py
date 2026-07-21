from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(slots=True)
class _LiveNode:
    item: QTreeWidgetItem
    started: float


class EvaluationInspector(QWidget):
    """Persistent, dockable view of current and most recent graph evaluation."""

    nodeRequested = Signal(str)

    COLUMNS = ("Node / Stage", "Backend", "State", "Time", "Cache", "Output", "Memory", "Details")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._job_id = 0
        self._job_started = 0.0
        self._job_active = False
        self._live: dict[str, _LiveNode] = {}
        self._last_live_refresh = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        self.state_label = QLabel("Idle")
        self.state_label.setObjectName("evaluationState")
        self.target_label = QLabel("No evaluation has run yet")
        self.target_label.setObjectName("muted")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.clear_button = QPushButton("Clear completed")
        self.clear_button.clicked.connect(self.clear_completed)
        top.addWidget(self.state_label)
        top.addWidget(self.target_label, 1)
        top.addWidget(self.clear_button)
        root.addLayout(top)

        meta = QGridLayout()
        meta.setHorizontalSpacing(14)
        self.mode_value = QLabel("—")
        self.resolution_value = QLabel("—")
        self.elapsed_value = QLabel("—")
        for widget in (self.mode_value, self.resolution_value, self.elapsed_value):
            widget.setObjectName("muted")
        meta.addWidget(QLabel("Mode"), 0, 0)
        meta.addWidget(self.mode_value, 0, 1)
        meta.addWidget(QLabel("Resolution"), 0, 2)
        meta.addWidget(self.resolution_value, 0, 3)
        meta.addWidget(QLabel("Elapsed"), 0, 4)
        meta.addWidget(self.elapsed_value, 0, 5)
        meta.setColumnStretch(6, 1)
        root.addLayout(meta)

        self.background_label = QLabel()
        self.background_label.setObjectName("muted")
        self.background_label.setTextFormat(Qt.TextFormat.PlainText)
        self.background_label.setVisible(False)
        root.addWidget(self.background_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLUMNS))
        self.tree.setHeaderLabels(self.COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 85)
        self.tree.setColumnWidth(2, 105)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 75)
        self.tree.setColumnWidth(5, 115)
        self.tree.setColumnWidth(6, 80)
        root.addWidget(self.tree, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _format_bytes(value: int) -> str:
        value = max(int(value), 0)
        if value >= 1024 ** 3:
            return f"{value / 1024 ** 3:.2f} GB"
        if value >= 1024 ** 2:
            return f"{value / 1024 ** 2:.1f} MB"
        if value >= 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value} B" if value else "—"

    @staticmethod
    def _format_ms(value: float) -> str:
        value = max(float(value), 0.0)
        return f"{value / 1000.0:.2f} s" if value >= 1000.0 else f"{value:.1f} ms"

    def set_background_activity(self, active: bool, message: str = "") -> None:
        self.background_label.setText(f"Background: {str(message or 'working…')}" if active else "")
        self.background_label.setToolTip(str(message or ""))
        self.background_label.setVisible(bool(active))

    def begin_job(self, job_id: int, label: str, target_name: str, width: int, height: int, mode: str) -> None:
        self._job_id = int(job_id)
        self._job_started = time.perf_counter()
        self._job_active = True
        self._live.clear()
        self.tree.clear()
        self.state_label.setText(str(label or "Evaluating"))
        self.target_label.setText(str(target_name or "Graph evaluation"))
        self.mode_value.setText(str(mode or "preview").replace("_", " ").title())
        self.resolution_value.setText(f"{max(int(width), 1)} × {max(int(height), 1)}")
        self.elapsed_value.setText("0 ms")
        self.progress.setRange(0, 0)
        self.progress.setFormat("Working…")
        self._timer.start()

    def update_node(
        self,
        job_id: int,
        node_uid: str,
        node_name: str,
        active: bool,
        current: int = 0,
        target: int = 0,
        message: str = "",
    ) -> None:
        if int(job_id) != self._job_id:
            return
        live = self._live.get(node_uid)
        if active:
            if live is None:
                item = QTreeWidgetItem([str(node_name or "Node"), "", "Working", "", "", "", "", str(message or "")])
                item.setData(0, Qt.ItemDataRole.UserRole, str(node_uid))
                self.tree.insertTopLevelItem(0, item)
                live = _LiveNode(item, time.perf_counter())
                self._live[node_uid] = live
            live.item.setText(2, "Working")
            live.item.setText(7, str(message or ""))
            if target > 0:
                percent = max(0, min(int(round(current * 100.0 / target)), 100))
                live.item.setText(2, f"Working {percent}%")
                self.progress.setRange(0, max(int(target), 1))
                self.progress.setValue(max(0, min(int(current), int(target))))
                self.progress.setFormat(f"{node_name}: %p%")
            else:
                self.progress.setRange(0, 0)
                self.progress.setFormat(f"{node_name}: working…")
        elif live is not None:
            live.item.setText(2, "Completed")
            live.item.setText(3, self._format_ms((time.perf_counter() - live.started) * 1000.0))
            self._live.pop(node_uid, None)

    def finish_job(self, job_id: int, result: Any, upload_ms: float = 0.0) -> None:
        if int(job_id) != self._job_id:
            return
        self._job_active = False
        self._timer.stop()
        elapsed = float(getattr(result, "elapsed_ms", 0.0)) + max(float(upload_ms), 0.0)
        self.elapsed_value.setText(self._format_ms(elapsed))
        self.state_label.setText("Completed")
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setFormat("Complete")
        traces = tuple(getattr(result, "node_traces", ()) or ())
        items: list[QTreeWidgetItem] = []
        for trace in traces:
            output = "—"
            width = int(getattr(trace, "width", 0))
            height = int(getattr(trace, "height", 0))
            precision = str(getattr(trace, "precision", "") or "")
            if width and height:
                output = f"{width}×{height}"
                if precision:
                    output += f" · {precision}"
            stage = str(getattr(trace, "stage", "node") or "node")
            cache_text = (
                "Hit" if bool(getattr(trace, "cache_hit", False)) else "Miss"
            ) if stage == "node" else "—"
            item = QTreeWidgetItem([
                str(getattr(trace, "name", "Node")),
                str(getattr(trace, "backend", "")),
                str(getattr(trace, "state", "Completed")),
                self._format_ms(float(getattr(trace, "elapsed_ms", 0.0))),
                cache_text,
                output,
                self._format_bytes(int(getattr(trace, "bytes_used", 0))),
                str(getattr(trace, "details", "") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, str(getattr(trace, "node_uid", "") or ""))
            items.append(item)
        # Populate large traces in one batch so diagnostics never delay the
        # texture becoming visible in the 2D preview.
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            if items:
                self.tree.addTopLevelItems(items)
        finally:
            self.tree.setUpdatesEnabled(True)
            self.tree.viewport().update()
        if upload_ms > 0.0:
            self.add_stage("Renderer upload", "CPU → GPU", upload_ms, "3D material textures uploaded")

    def add_stage(self, name: str, backend: str, elapsed_ms: float, details: str = "") -> None:
        item = QTreeWidgetItem([
            str(name), str(backend), "Completed", self._format_ms(elapsed_ms), "—", "—", "—", str(details),
        ])
        self.tree.addTopLevelItem(item)

    def fail_job(self, job_id: int, message: str) -> None:
        if int(job_id) != self._job_id:
            return
        self._job_active = False
        self._timer.stop()
        self.state_label.setText("Failed")
        self.target_label.setText(str(message))
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Failed")

    def cancel_job(self, job_id: int | None = None) -> None:
        if job_id is not None and int(job_id) != self._job_id:
            return
        if not self._job_active:
            return
        self._job_active = False
        self._timer.stop()
        self.state_label.setText("Cancelled")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Cancelled")

    def clear_completed(self) -> None:
        if self._job_active:
            return
        self.tree.clear()
        self.state_label.setText("Idle")
        self.target_label.setText("No active evaluation")
        self.mode_value.setText("—")
        self.resolution_value.setText("—")
        self.elapsed_value.setText("—")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("")

    def _tick(self) -> None:
        if not self._job_active:
            return
        elapsed = (time.perf_counter() - self._job_started) * 1000.0
        self.elapsed_value.setText(self._format_ms(elapsed))

    def _item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        uid = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if uid:
            self.nodeRequested.emit(uid)
