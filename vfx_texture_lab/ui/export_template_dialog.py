from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
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
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..export_templates import (
    BIT_DEPTH_OPTIONS,
    CHANNEL_LAYOUT_OPTIONS,
    COLOUR_ENCODING_OPTIONS,
    FORMAT_OPTIONS,
    ExportChannelBinding,
    ExportFileTemplate,
    ExportTemplate,
    builtin_template,
    builtin_template_names,
    clone_as_custom,
    source_labels,
    validate_export_template,
)
from ..export_template_library import (
    VFXEXPORT_EXTENSION,
    ExportTemplateLibraryError,
    installed_export_templates,
    install_template_object,
    read_vfxexport,
    write_vfxexport,
)


class ExportTemplateDialog(QDialog):
    """Artist-facing editor for graph-local Texture Set Output templates."""

    def __init__(self, template: ExportTemplate, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Template Editor")
        self.resize(1040, 720)
        self._files = [deepcopy(file.to_dict()) for file in template.files]
        self._editing_index = -1
        self._template_id = template.template_id or "custom"

        outer = QVBoxLayout(self)
        heading = QLabel("Export Template")
        heading.setObjectName("sectionTitle")
        outer.addWidget(heading)
        note = QLabel(
            "Define the files produced by this Texture Set Output, then assign semantic material data to each R, G, B and A channel. "
            "Built-in templates are safe starting points; saving creates a graph-local Custom Template."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)

        top = QHBoxLayout()
        top.addWidget(QLabel("Template name"))
        self.template_name = QLineEdit(template.name if not template.built_in else f"Custom {template.name}")
        top.addWidget(self.template_name, 1)
        top.addSpacing(12)
        top.addWidget(QLabel("Start from"))
        self.builtin_combo = QComboBox()
        self._starter_templates = {name: builtin_template(name) for name in builtin_template_names()}
        self._starter_templates.update({entry.template.name: entry.template for entry in installed_export_templates()})
        self.builtin_combo.addItems(tuple(self._starter_templates))
        self.builtin_combo.setCurrentText(template.name if template.name in self._starter_templates else "Generic PBR Separate")
        top.addWidget(self.builtin_combo)
        load_builtin = QPushButton("Load")
        load_builtin.setToolTip("Replace this editor's current files and metadata with a fresh copy of the selected template.")
        load_builtin.clicked.connect(self._load_builtin)
        top.addWidget(load_builtin)
        outer.addLayout(top)

        metadata = QFormLayout()
        self.template_description = QLineEdit(template.description)
        self.template_author = QLineEdit(template.author)
        self.template_version = QLineEdit(template.asset_version or "1.0.0")
        self.template_target = QLineEdit(template.target or "Generic")
        metadata.addRow("Description", self.template_description)
        metadata.addRow("Author", self.template_author)
        metadata.addRow("Template version", self.template_version)
        metadata.addRow("Engine / purpose", self.template_target)
        outer.addLayout(metadata)

        share = QHBoxLayout()
        import_button = QPushButton("Import .vfxexport…")
        export_button = QPushButton("Export .vfxexport…")
        install_button = QPushButton("Install in User Templates")
        import_button.clicked.connect(self._import_template)
        export_button.clicked.connect(self._export_template)
        install_button.clicked.connect(self._install_template)
        share.addWidget(import_button)
        share.addWidget(export_button)
        share.addWidget(install_button)
        share.addStretch(1)
        outer.addLayout(share)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_title = QLabel("Output files")
        left_title.setObjectName("sectionTitle")
        left_layout.addWidget(left_title)
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._file_selection_changed)
        left_layout.addWidget(self.file_list, 1)
        file_buttons = QHBoxLayout()
        add = QPushButton("Add")
        duplicate = QPushButton("Duplicate")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add_file)
        duplicate.clicked.connect(self._duplicate_file)
        remove.clicked.connect(self._remove_file)
        file_buttons.addWidget(add)
        file_buttons.addWidget(duplicate)
        file_buttons.addWidget(remove)
        left_layout.addLayout(file_buttons)
        splitter.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        editor = QWidget()
        self.form = QFormLayout(editor)
        self.form.setContentsMargins(10, 4, 10, 8)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(10)
        scroll.setWidget(editor)
        splitter.addWidget(scroll)
        splitter.setSizes((300, 700))

        self.file_name = QLineEdit()
        self.map_name = QLineEdit()
        self.filename = QLineEdit()
        self.use_node_filename = QCheckBox("Use the Texture Set Output file-name pattern")
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMAT_OPTIONS)
        self.bit_depth = QComboBox()
        self.bit_depth.addItems(BIT_DEPTH_OPTIONS)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(CHANNEL_LAYOUT_OPTIONS)
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(COLOUR_ENCODING_OPTIONS)
        self.always_export = QCheckBox("Write this file even when every assigned source is absent")

        self.form.addRow("File label", self.file_name)
        self.form.addRow("{map} value", self.map_name)
        self.form.addRow("File name", self.filename)
        self.form.addRow("", self.use_node_filename)
        self.form.addRow("Image format", self.format_combo)
        self.form.addRow("Bit depth", self.bit_depth)
        self.form.addRow("Channels", self.layout_combo)
        self.form.addRow("Colour handling", self.encoding_combo)
        self.form.addRow("", self.always_export)

        channel_heading = QLabel("Channel assignments")
        channel_heading.setObjectName("sectionTitle")
        self.form.addRow(channel_heading)
        source_choices = source_labels()
        self.channel_rows: dict[str, tuple[QWidget, QComboBox, QCheckBox]] = {}
        for channel in ("R", "G", "B", "A"):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            source = QComboBox()
            for label, binding in source_choices:
                source.addItem(label, binding.to_dict())
            invert = QCheckBox("Invert")
            row_layout.addWidget(source, 1)
            row_layout.addWidget(invert)
            self.form.addRow(channel, row)
            self.channel_rows[channel] = (row, source, invert)
            source.currentIndexChanged.connect(self._control_changed)
            invert.toggled.connect(self._control_changed)

        self.file_name.textEdited.connect(self._control_changed)
        self.map_name.textEdited.connect(self._control_changed)
        self.filename.textEdited.connect(self._control_changed)
        self.use_node_filename.toggled.connect(self._use_node_filename_changed)
        self.format_combo.currentTextChanged.connect(self._format_changed)
        self.bit_depth.currentTextChanged.connect(self._control_changed)
        self.layout_combo.currentTextChanged.connect(self._layout_changed)
        self.encoding_combo.currentTextChanged.connect(self._control_changed)
        self.always_export.toggled.connect(self._control_changed)

        help_label = QLabel(
            "Tokens: {set}, {map}, {output}, {graph}, {version}, {profile}, {target}, {width}, {height}. Leave File name on the node pattern to keep one naming convention across all files. "
            "Normal · Green / Y convention automatically follows the output node's OpenGL or DirectX setting."
        )
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        self.form.addRow(help_label)

        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.form.addRow("Template status", self.validation)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Use Custom Template")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._rebuild_file_list(select=0)
        self._update_validation()

    def _block_controls(self, blocked: bool) -> None:
        widgets = [
            self.file_name,
            self.map_name,
            self.filename,
            self.use_node_filename,
            self.format_combo,
            self.bit_depth,
            self.layout_combo,
            self.encoding_combo,
            self.always_export,
        ]
        for _channel, (_row, combo, invert) in self.channel_rows.items():
            widgets.extend((combo, invert))
        for widget in widgets:
            widget.blockSignals(blocked)

    def _default_file(self, ordinal: int) -> dict:
        return ExportFileTemplate.from_dict(
            {
                "name": f"Output {ordinal}",
                "map_name": f"Map{ordinal}",
                "filename": "",
                "format": "Texture-set setting",
                "bit_depth": "8",
                "channels": "RGBA",
                "colour_encoding": "Linear",
                "always_export": True,
                "bindings": {
                    "R": ExportChannelBinding(constant=0.0).to_dict(),
                    "G": ExportChannelBinding(constant=0.0).to_dict(),
                    "B": ExportChannelBinding(constant=0.0).to_dict(),
                    "A": ExportChannelBinding(constant=1.0).to_dict(),
                },
            },
            ordinal=ordinal,
        ).to_dict()

    def _rebuild_file_list(self, *, select: int | None = None) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for raw in self._files:
            file = ExportFileTemplate.from_dict(raw)
            self.file_list.addItem(f"{file.name}\n{{map}} = {file.map_name} · {file.channels}")
        self.file_list.blockSignals(False)
        if self._files:
            row = min(max(0 if select is None else int(select), 0), len(self._files) - 1)
            self.file_list.setCurrentRow(row)
            self._show_file(row)
        else:
            self._editing_index = -1
            self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.file_name,
            self.map_name,
            self.filename,
            self.use_node_filename,
            self.format_combo,
            self.bit_depth,
            self.layout_combo,
            self.encoding_combo,
            self.always_export,
        ):
            widget.setEnabled(enabled)
        for row, combo, invert in self.channel_rows.values():
            row.setEnabled(enabled)
            combo.setEnabled(enabled)
            invert.setEnabled(enabled)

    def _file_selection_changed(self, current, previous) -> None:
        if self._editing_index >= 0:
            self._commit_file(self._editing_index)
        row = self.file_list.row(current) if current is not None else -1
        self._show_file(row)

    def _show_file(self, index: int) -> None:
        if index < 0 or index >= len(self._files):
            self._editing_index = -1
            self._set_editor_enabled(False)
            return
        self._editing_index = index
        file = ExportFileTemplate.from_dict(self._files[index], ordinal=index + 1)
        self._set_editor_enabled(True)
        self._block_controls(True)
        try:
            self.file_name.setText(file.name)
            self.map_name.setText(file.map_name)
            self.filename.setText(file.filename)
            self.use_node_filename.setChecked(not bool(file.filename.strip()))
            self.filename.setEnabled(bool(file.filename.strip()))
            self.format_combo.setCurrentText(file.format_name)
            self.bit_depth.setCurrentText(file.bit_depth)
            self.layout_combo.setCurrentText(file.channels)
            self.encoding_combo.setCurrentText(file.colour_encoding)
            self.always_export.setChecked(file.always_export)
            for channel, (_row, combo, invert) in self.channel_rows.items():
                binding = file.binding(channel)
                self._select_binding(combo, binding)
                invert.setChecked(binding.invert)
        finally:
            self._block_controls(False)
        self._update_channel_visibility()

    @staticmethod
    def _binding_key(binding: ExportChannelBinding) -> tuple:
        return (
            binding.source,
            binding.component,
            round(float(binding.constant), 6),
            bool(binding.normal_y),
        )

    def _select_binding(self, combo: QComboBox, binding: ExportChannelBinding) -> None:
        target = self._binding_key(binding)
        for index in range(combo.count()):
            candidate = ExportChannelBinding.from_dict(combo.itemData(index))
            if self._binding_key(candidate) == target:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _commit_file(self, index: int) -> None:
        if index < 0 or index >= len(self._files):
            return
        bindings: dict[str, dict] = {}
        for channel, (_row, combo, invert) in self.channel_rows.items():
            binding = ExportChannelBinding.from_dict(combo.currentData())
            binding = ExportChannelBinding(
                source=binding.source,
                component=binding.component,
                invert=invert.isChecked(),
                constant=binding.constant,
                normal_y=binding.normal_y,
            )
            bindings[channel] = binding.to_dict()
        self._files[index] = ExportFileTemplate.from_dict(
            {
                "name": self.file_name.text(),
                "map_name": self.map_name.text(),
                "filename": "" if self.use_node_filename.isChecked() else self.filename.text(),
                "format": self.format_combo.currentText(),
                "bit_depth": self.bit_depth.currentText(),
                "channels": self.layout_combo.currentText(),
                "colour_encoding": self.encoding_combo.currentText(),
                "always_export": self.always_export.isChecked(),
                "bindings": bindings,
            },
            ordinal=index + 1,
        ).to_dict()

    def _control_changed(self, *_args) -> None:
        if self._editing_index < 0:
            return
        self._commit_file(self._editing_index)
        item = self.file_list.item(self._editing_index)
        if item is not None:
            file = ExportFileTemplate.from_dict(self._files[self._editing_index])
            item.setText(f"{file.name}\n{{map}} = {file.map_name} · {file.channels}")
        self._update_validation()

    def _use_node_filename_changed(self, checked: bool) -> None:
        self.filename.setEnabled(not checked)
        self._control_changed()

    def _layout_changed(self, *_args) -> None:
        self._update_channel_visibility()
        self._control_changed()

    def _format_changed(self, value: str) -> None:
        if value == "R16":
            self._block_controls(True)
            try:
                self.layout_combo.setCurrentText("Grayscale")
                self.bit_depth.setCurrentText("16")
                self.encoding_combo.setCurrentText("Linear")
            finally:
                self._block_controls(False)
            self._update_channel_visibility()
        self._control_changed()

    def _update_channel_visibility(self) -> None:
        layout = self.layout_combo.currentText()
        active = {"R"}
        if layout in {"RGB", "RGBA"}:
            active.update(("G", "B"))
        if layout == "RGBA":
            active.add("A")
        for channel, (row, _combo, _invert) in self.channel_rows.items():
            row.setVisible(channel in active)
            label = self.form.labelForField(row)
            if label is not None:
                label.setVisible(channel in active)

    def _add_file(self) -> None:
        if self._editing_index >= 0:
            self._commit_file(self._editing_index)
        self._files.append(self._default_file(len(self._files) + 1))
        self._rebuild_file_list(select=len(self._files) - 1)
        self._update_validation()

    def _duplicate_file(self) -> None:
        if self._editing_index < 0:
            return
        self._commit_file(self._editing_index)
        duplicate = deepcopy(self._files[self._editing_index])
        duplicate["name"] = f"{duplicate.get('name', 'Output')} Copy"
        duplicate["map_name"] = f"{duplicate.get('map_name', 'Map')}Copy"
        self._files.insert(self._editing_index + 1, duplicate)
        self._rebuild_file_list(select=self._editing_index + 1)
        self._update_validation()

    def _remove_file(self) -> None:
        if self._editing_index < 0:
            return
        row = self._editing_index
        self._files.pop(row)
        self._rebuild_file_list(select=min(row, len(self._files) - 1))
        self._update_validation()

    def _load_builtin(self) -> None:
        source = self._starter_templates.get(self.builtin_combo.currentText(), builtin_template("Generic PBR Separate"))
        template = clone_as_custom(source)
        self.template_name.setText(template.name)
        self.template_description.setText(source.description)
        self.template_author.setText(source.author)
        self.template_version.setText(source.asset_version)
        self.template_target.setText(source.target)
        self._template_id = source.template_id if not source.built_in else "custom"
        self._files = [deepcopy(file.to_dict()) for file in template.files]
        self._rebuild_file_list(select=0)
        self._update_validation()

    def _apply_imported_template(self, template: ExportTemplate) -> None:
        self.template_name.setText(template.name)
        self.template_description.setText(template.description)
        self.template_author.setText(template.author)
        self.template_version.setText(template.asset_version)
        self.template_target.setText(template.target)
        self._template_id = template.template_id
        self._files = [deepcopy(file.to_dict()) for file in template.files]
        self._rebuild_file_list(select=0)
        self._update_validation()

    def _import_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Export Template", "", "VFX Export Template (*.vfxexport)")
        if not path:
            return
        try:
            self._apply_imported_template(read_vfxexport(path))
        except ExportTemplateLibraryError as exc:
            QMessageBox.warning(self, "Could not import template", str(exc))

    def _export_template(self) -> None:
        template = self._build_template()
        errors, _warnings = validate_export_template(template)
        if errors:
            self._update_validation()
            return
        suggested = (template.name or "Export Template").replace("/", "-") + VFXEXPORT_EXTENSION
        path, _ = QFileDialog.getSaveFileName(self, "Export Export Template", suggested, "VFX Export Template (*.vfxexport)")
        if not path:
            return
        try:
            written = write_vfxexport(path, template)
        except ExportTemplateLibraryError as exc:
            QMessageBox.warning(self, "Could not export template", str(exc))
            return
        QMessageBox.information(self, "Export template created", f"Created:\n{written}")

    def _install_template(self) -> None:
        template = self._build_template()
        try:
            path, installed, action = install_template_object(template, conflict="reject")
        except ExportTemplateLibraryError as exc:
            if "already exists" not in str(exc):
                QMessageBox.warning(self, "Could not install template", str(exc))
                return
            box = QMessageBox(self)
            box.setWindowTitle("Template already installed")
            box.setText("A user template with the same stable Template ID is already installed.")
            update = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
            side = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
            cancel = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is cancel or box.clickedButton() is None:
                return
            mode = "update" if box.clickedButton() is update else "side-by-side"
            try:
                path, installed, action = install_template_object(template, conflict=mode)
            except ExportTemplateLibraryError as nested:
                QMessageBox.warning(self, "Could not install template", str(nested))
                return
        self._template_id = installed.template_id
        QMessageBox.information(self, "Export template installed", f"{installed.name} was {action}.\n\n{path}")

    def _build_template(self) -> ExportTemplate:
        if self._editing_index >= 0:
            self._commit_file(self._editing_index)
        return ExportTemplate.from_dict(
            {
                "name": self.template_name.text().strip() or "Custom Template",
                "template_id": self._template_id or "custom",
                "description": self.template_description.text().strip(),
                "author": self.template_author.text().strip(),
                "asset_version": self.template_version.text().strip() or "1.0.0",
                "target": self.template_target.text().strip() or "Generic",
                "files": deepcopy(self._files),
            }
        )

    def _update_validation(self) -> None:
        template = self._build_template()
        errors, warnings = validate_export_template(template)
        if errors:
            self.validation.setStyleSheet("color:#ef7785;")
            self.validation.setText("Blocking problems:\n" + "\n".join(f"• {message}" for message in errors))
        elif warnings:
            self.validation.setStyleSheet("color:#d7a449;")
            self.validation.setText("Usable with warnings:\n" + "\n".join(f"• {message}" for message in warnings))
        else:
            self.validation.setStyleSheet("color:#79c79b;")
            self.validation.setText("Ready · the template is structurally valid.")

    def _validate_and_accept(self) -> None:
        errors, _warnings = validate_export_template(self._build_template())
        if errors:
            self._update_validation()
            return
        self.accept()

    def result_template(self) -> ExportTemplate:
        return self._build_template()
