from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..custom_nodes import CustomNodePackageManager, PackageDiagnostic

ROLE_LIBRARY_UID = Qt.ItemDataRole.UserRole
ROLE_PACKAGE_ID = Qt.ItemDataRole.UserRole + 1


class CustomNodeLibrariesDialog(QDialog):
    rescanRequested = Signal()

    def __init__(self, manager: CustomNodePackageManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Custom Node & Graph Asset Libraries")
        self.resize(820, 460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Add folders containing custom node packages, reusable .vfxgraph assets, or both. Node packages are hot-reloaded; graph assets appear in the Node Library immediately."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        managed_row = QHBoxLayout()
        managed_label = QLabel(f"Managed custom-node install folder: {manager.managed_directory}")
        managed_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_managed = QPushButton("Open Folder")
        open_managed.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(manager.managed_directory)))
        )
        managed_row.addWidget(managed_label, 1)
        managed_row.addWidget(open_managed)
        layout.addLayout(managed_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("Enabled", "Library name", "Node packages / graph assets folder"))
        self.tree.setColumnWidth(0, 80)
        self.tree.setColumnWidth(1, 190)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)

        row = QHBoxLayout()
        add = QPushButton("Add Folder…")
        remove = QPushButton("Remove")
        open_selected = QPushButton("Open Selected")
        rescan = QPushButton("Rescan Now")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        open_selected.clicked.connect(self._open_selected)
        rescan.clicked.connect(self.rescanRequested.emit)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(open_selected)
        row.addStretch(1)
        row.addWidget(rescan)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.rebuild()

    def rebuild(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for library in self.manager.libraries():
            item = QTreeWidgetItem(("", library.name, library.path))
            item.setData(0, ROLE_LIBRARY_UID, library.uid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(0, Qt.CheckState.Checked if library.enabled else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)

    def _add(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add custom node or graph asset library folder")
        if not folder:
            return
        suggested = Path(folder).name or "Custom Node Library"
        name, accepted = QInputDialog.getText(self, "Library name", "Name shown in diagnostics:", text=suggested)
        if not accepted:
            return
        self.manager.add_library(folder, name)
        self.rebuild()
        self.rescanRequested.emit()

    def _remove(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        uid = str(item.data(0, ROLE_LIBRARY_UID) or "")
        if not uid:
            return
        self.manager.remove_library(uid)
        self.rebuild()
        self.rescanRequested.emit()

    def _open_selected(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.text(2)))

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        uid = str(item.data(0, ROLE_LIBRARY_UID) or "")
        if not uid:
            return
        if column == 0:
            self.manager.set_library_enabled(uid, item.checkState(0) == Qt.CheckState.Checked)
            self.rescanRequested.emit()
        elif column == 1:
            self.manager.set_library_name(uid, item.text(1))
            self.rescanRequested.emit()


class CustomNodeDiagnosticsDialog(QDialog):
    reloadRequested = Signal()

    def __init__(self, manager: CustomNodePackageManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Custom Node Diagnostics")
        self.resize(980, 610)

        layout = QVBoxLayout(self)
        summary = QLabel(
            "Manifest and WGSL errors are isolated to their package. During hot reload, a failed edit keeps the last successfully compiled shader active."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("Status", "Node", "Version", "Source", "Message"))
        self.tree.setColumnWidth(0, 85)
        self.tree.setColumnWidth(1, 230)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 160)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.details)
        splitter.setSizes((310, 220))
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.open_folder = QPushButton("Open Package Folder")
        self.open_shader = QPushButton("Open Shader")
        self.toggle_disabled = QPushButton("Disable Package")
        reload_button = QPushButton("Reload All")
        self.open_folder.clicked.connect(self._open_package_folder)
        self.open_shader.clicked.connect(self._open_shader_file)
        self.toggle_disabled.clicked.connect(self._toggle_package)
        reload_button.clicked.connect(self.reloadRequested.emit)
        actions.addWidget(self.open_folder)
        actions.addWidget(self.open_shader)
        actions.addWidget(self.toggle_disabled)
        actions.addStretch(1)
        actions.addWidget(reload_button)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.manager.diagnosticsChanged.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        selected_id = self._selected_package_id()
        self.tree.clear()
        diagnostics = sorted(
            self.manager.diagnostics(),
            key=lambda item: ({"error": 0, "warning": 1, "disabled": 2, "ok": 3}.get(item.severity, 4), item.name.lower()),
        )
        for diagnostic in diagnostics:
            short_message = diagnostic.message.splitlines()[0]
            item = QTreeWidgetItem(
                (
                    diagnostic.status_label,
                    diagnostic.name,
                    diagnostic.version,
                    diagnostic.library_name,
                    short_message,
                )
            )
            item.setData(0, ROLE_PACKAGE_ID, diagnostic.package_id)
            if diagnostic.severity == "error":
                item.setForeground(0, Qt.GlobalColor.red)
            elif diagnostic.severity == "warning":
                item.setForeground(0, Qt.GlobalColor.yellow)
            self.tree.addTopLevelItem(item)
            if selected_id and diagnostic.package_id == selected_id:
                self.tree.setCurrentItem(item)
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._selection_changed(self.tree.currentItem(), None)

    def _selected_package_id(self) -> str:
        item = self.tree.currentItem()
        return str(item.data(0, ROLE_PACKAGE_ID) or "") if item is not None else ""

    def _selected_diagnostic(self) -> PackageDiagnostic | None:
        return self.manager.diagnostic_for(self._selected_package_id())

    def _selection_changed(self, current, previous) -> None:
        del previous
        diagnostic = self._selected_diagnostic()
        enabled = diagnostic is not None
        self.open_folder.setEnabled(enabled and bool(diagnostic.root))
        self.open_shader.setEnabled(enabled and bool(diagnostic.shader_path))
        self.toggle_disabled.setEnabled(enabled and not diagnostic.package_id.startswith("library:"))
        if diagnostic is None:
            self.details.clear()
            return
        self.toggle_disabled.setText(
            "Enable Package" if self.manager.is_disabled(diagnostic.package_id) else "Disable Package"
        )
        lines = [
            f"Node: {diagnostic.name}",
            f"Permanent ID: {diagnostic.package_id}",
            f"Version: {diagnostic.version or '—'}",
            f"Source: {diagnostic.library_name} ({diagnostic.source_kind})",
            f"Folder: {diagnostic.root}",
        ]
        if diagnostic.manifest_path:
            lines.append(f"Manifest: {diagnostic.manifest_path}")
        if diagnostic.shader_path:
            lines.append(f"Shader: {diagnostic.shader_path}")
        if diagnostic.line is not None:
            lines.append(f"Location: line {diagnostic.line}, column {diagnostic.column or '?'}")
        lines.extend(("", diagnostic.message))
        if diagnostic.shader_path and diagnostic.line is not None:
            lines.extend(("", self._source_context(Path(diagnostic.shader_path), diagnostic.line)))
        self.details.setPlainText("\n".join(lines))

    @staticmethod
    def _source_context(path: Path, line_number: int) -> str:
        try:
            source = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        start = max(line_number - 4, 0)
        stop = min(line_number + 3, len(source))
        rendered = []
        for index in range(start, stop):
            marker = ">" if index + 1 == line_number else " "
            rendered.append(f"{marker} {index + 1:4d} │ {source[index]}")
        return "\n".join(rendered)

    def _open_package_folder(self) -> None:
        diagnostic = self._selected_diagnostic()
        if diagnostic is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(diagnostic.root))

    def _open_shader_file(self) -> None:
        diagnostic = self._selected_diagnostic()
        if diagnostic is not None and diagnostic.shader_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(diagnostic.shader_path))

    def _toggle_package(self) -> None:
        diagnostic = self._selected_diagnostic()
        if diagnostic is None:
            return
        disabled = not self.manager.is_disabled(diagnostic.package_id)
        self.manager.set_disabled(diagnostic.package_id, disabled)
        self.reloadRequested.emit()
