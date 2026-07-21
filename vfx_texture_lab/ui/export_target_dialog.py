from __future__ import annotations

from string import Formatter

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..export_profiles import ExportTarget, NODE_TEMPLATE, OUTPUT_SETTING, RESOLUTION_OPTIONS
from ..export_templates import builtin_template_names
from ..export_template_library import installed_export_templates


class ExportTargetDialog(QDialog):
    """Compact editor for one production export target."""

    def __init__(self, target: ExportTarget | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Target")
        self.resize(520, 470)
        self._source = target or ExportTarget.current("New Target")

        outer = QVBoxLayout(self)
        note = QLabel(
            "A target applies one texture layout and optional output overrides to every selected Texture Set Output. "
            "Single Image Outputs are still written once using their own settings."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        outer.addWidget(note)

        form = QFormLayout()
        self.name = QLineEdit(self._source.name)
        form.addRow("Target name", self.name)

        self.template = QComboBox()
        self._installed_templates = {entry.template.name: entry.template for entry in installed_export_templates()}
        self.template.addItems((NODE_TEMPLATE, *builtin_template_names(), *self._installed_templates.keys()))
        available = {self.template.itemText(i) for i in range(self.template.count())}
        if self._source.template_name not in available and self._source.custom_template:
            self.template.addItem(self._source.template_name)
            available.add(self._source.template_name)
        if self._source.template_name in available:
            self.template.setCurrentText(self._source.template_name)
        form.addRow("Export template", self.template)

        self.subfolder = QLineEdit(self._source.subfolder)
        self.subfolder.setPlaceholderText("{target}")
        self.subfolder.setToolTip(
            "Relative folder beneath the chosen export destination. Tokens: {graph}, {version}, {profile}, "
            "{target}, {output}, {set}. Leave blank to export directly into the root."
        )
        form.addRow("Subfolder", self.subfolder)

        self.resolution = QComboBox()
        self.resolution.addItems((OUTPUT_SETTING, *RESOLUTION_OPTIONS))
        self.resolution.setCurrentText(self._source.resolution)
        form.addRow("Resolution", self.resolution)

        self.normal = QComboBox()
        self.normal.addItems((OUTPUT_SETTING, "OpenGL (+Y)", "DirectX (-Y)"))
        self.normal.setCurrentText(self._source.normal_convention)
        form.addRow("Normal convention", self.normal)

        self.format = QComboBox()
        self.format.addItems((OUTPUT_SETTING, "PNG", "TGA"))
        self.format.setCurrentText(self._source.texture_format)
        form.addRow("Image format", self.format)

        self.colour_depth = QComboBox()
        self.colour_depth.addItems((OUTPUT_SETTING, "8", "16"))
        self.colour_depth.setCurrentText(self._source.colour_bit_depth)
        form.addRow("Colour bit depth", self.colour_depth)

        self.data_depth = QComboBox()
        self.data_depth.addItems((OUTPUT_SETTING, "8", "16"))
        self.data_depth.setCurrentText(self._source.data_bit_depth)
        form.addRow("Scalar-map bit depth", self.data_depth)

        self.height_format = QComboBox()
        self.height_format.addItems((OUTPUT_SETTING, "PNG 16-bit", "Raw R16"))
        self.height_format.setCurrentText(self._source.height_format)
        form.addRow("Height format", self.height_format)
        outer.addLayout(form)

        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.validation.setObjectName("muted")
        outer.addWidget(self.validation)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not self.name.text().strip():
            self.validation.setText("Give the export target a name.")
            return
        folder = self.subfolder.text().strip().replace("\\", "/")
        if folder.startswith("/") or any(part == ".." for part in folder.split("/")):
            self.validation.setText("The target subfolder must be relative and cannot contain ‘..’.")
            return
        try:
            fields = {field for _literal, field, _format, _conversion in Formatter().parse(folder) if field}
        except ValueError as exc:
            self.validation.setText(f"Invalid subfolder template: {exc}")
            return
        unsupported = sorted(fields - {"graph", "version", "profile", "target", "output", "set"})
        if unsupported:
            self.validation.setText("Unsupported subfolder token(s): " + ", ".join(unsupported))
            return
        self.accept()

    def result_target(self) -> ExportTarget:
        return ExportTarget(
            target_id=self._source.target_id,
            name=self.name.text().strip() or self._source.name,
            template_name=self.template.currentText(),
            enabled=self._source.enabled,
            subfolder=self.subfolder.text().strip(),
            resolution=self.resolution.currentText(),
            normal_convention=self.normal.currentText(),
            texture_format=self.format.currentText(),
            colour_bit_depth=self.colour_depth.currentText(),
            data_bit_depth=self.data_depth.currentText(),
            height_format=self.height_format.currentText(),
            custom_template=(
                self._installed_templates[self.template.currentText()].to_dict()
                if self.template.currentText() in self._installed_templates
                else (self._source.custom_template if self.template.currentText() == self._source.template_name else None)
            ),
        )
