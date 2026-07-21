from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..export_template_library import (
    ExportTemplateLibraryError,
    export_template_directory,
    installed_export_templates,
    install_vfxexport,
    read_vfxexport,
    remove_installed_template,
)


class ExportTemplateLibraryDialog(QDialog):
    """Small manager for reusable user-installed .vfxexport templates."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("User Export Templates")
        self.resize(720, 520)

        outer = QVBoxLayout(self)
        heading = QLabel("User Export Templates", self)
        heading.setObjectName("sectionTitle")
        outer.addWidget(heading)
        note = QLabel(
            "Installed templates are copied into the VFX Texture Lab user library. They can be used as multi-target layouts or loaded as starting points for graph-local templates.",
            self,
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        outer.addWidget(note)

        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._selection_changed)
        outer.addWidget(self.list, 1)

        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.details)

        buttons = QHBoxLayout()
        install = QPushButton("Install .vfxexport…", self)
        remove = QPushButton("Remove", self)
        reveal = QPushButton("Open Folder", self)
        refresh = QPushButton("Refresh", self)
        close = QPushButton("Close", self)
        install.clicked.connect(self._install)
        remove.clicked.connect(self._remove)
        reveal.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_template_directory())))
        )
        refresh.clicked.connect(self.refresh)
        close.clicked.connect(self.accept)
        buttons.addWidget(install)
        buttons.addWidget(remove)
        buttons.addWidget(reveal)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        buttons.addWidget(close)
        outer.addLayout(buttons)

        self._entries = []
        self.refresh()

    def refresh(self) -> None:
        selected_id = ""
        row = self.list.currentRow()
        if 0 <= row < len(self._entries):
            selected_id = self._entries[row].template.template_id
        self._entries = list(installed_export_templates())
        self.list.clear()
        selected_row = -1
        for index, entry in enumerate(self._entries):
            template = entry.template
            self.list.addItem(
                f"{template.name}  ·  {template.target or 'Generic'}  ·  v{template.asset_version}"
            )
            if template.template_id == selected_id:
                selected_row = index
        if self._entries:
            self.list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self.details.setText("No user export templates are installed.")

    def _selection_changed(self, row: int) -> None:
        if not 0 <= row < len(self._entries):
            self.details.setText("No user export template selected.")
            return
        entry = self._entries[row]
        template = entry.template
        self.details.setText(
            f"<b>{template.name}</b><br>"
            f"{template.description or 'No description'}<br><br>"
            f"Author: {template.author or 'Unknown'} · Version: {template.asset_version}<br>"
            f"Engine / purpose: {template.target or 'Generic'}<br>"
            f"Files: {len(template.files)} · Template ID: {template.template_id}<br>"
            f"Source: {entry.path}"
        )

    def _install(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Install Export Template", "", "VFX Export Template (*.vfxexport)"
        )
        if not path:
            return
        try:
            incoming = read_vfxexport(path)
            try:
                _target, _installed, _action = install_vfxexport(path, conflict="ask")
            except ExportTemplateLibraryError as exc:
                if "already exists" not in str(exc):
                    raise
                box = QMessageBox(self)
                box.setWindowTitle("Template already installed")
                box.setText(
                    f"{incoming.name} has the same stable Template ID as an installed template."
                )
                update = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
                side = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
                cancel = box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() is cancel or box.clickedButton() is None:
                    return
                mode = "update" if box.clickedButton() is update else "side-by-side"
                install_vfxexport(path, conflict=mode)
        except ExportTemplateLibraryError as exc:
            QMessageBox.warning(self, "Could not install export template", str(exc))
            return
        self.refresh()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self._entries):
            return
        template = self._entries[row].template
        answer = QMessageBox.question(
            self,
            "Remove export template?",
            f"Remove {template.name} from the user template library?\n\nGraphs and export profiles that already contain a local snapshot will keep working.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        remove_installed_template(template.template_id)
        self.refresh()
