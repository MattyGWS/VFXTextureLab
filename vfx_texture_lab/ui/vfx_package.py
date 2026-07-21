from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..vfx_package import VFXPackageInfo


class VFXPackageExportOptionsDialog(QDialog):
    """Small export preflight for package resource choices."""

    def __init__(self, *, include_image_sources: bool = True, include_export_templates: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VFX Package Options")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QLabel("Image resources", self)
        heading.setStyleSheet("font-weight: 700;")
        layout.addWidget(heading)

        self.include_image_sources = QCheckBox(
            "Include source image files in the package", self
        )
        self.include_image_sources.setChecked(bool(include_image_sources))
        layout.addWidget(self.include_image_sources)

        explanation = QLabel(
            "Recommended. Imported images are copied into resources/images so recipients can "
            "inspect, edit or relink the original source files after extraction. The graph also "
            "keeps embedded fallback copies so Open Temporarily remains reliable without first "
            "extracting the archive.",
            self,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        layout.addWidget(explanation)

        compact = QLabel(
            "Turn this off only when you want the smallest package and do not need separate image source files.",
            self,
        )
        compact.setWordWrap(True)
        compact.setObjectName("muted")
        layout.addWidget(compact)

        template_heading = QLabel("Export templates", self)
        template_heading.setStyleSheet("font-weight: 700;")
        layout.addWidget(template_heading)
        self.include_export_templates = QCheckBox(
            "Include graph-local export templates as shareable .vfxexport files", self
        )
        self.include_export_templates.setChecked(bool(include_export_templates))
        layout.addWidget(self.include_export_templates)
        template_note = QLabel(
            "Recommended. Custom templates used by Texture Set Outputs and export profile targets remain embedded in the graph, "
            "and are also included as separately installable template files for recipients.",
            self,
        )
        template_note.setWordWrap(True)
        template_note.setObjectName("muted")
        layout.addWidget(template_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def include_image_source_files(self) -> bool:
        return self.include_image_sources.isChecked()

    @property
    def include_export_template_files(self) -> bool:
        return self.include_export_templates.isChecked()


class VFXPackageDialog(QDialog):
    """Package detail/preflight dialog used before opening or installing."""

    OPEN_TEMPORARILY = "open"
    EXTRACT_EDITABLE = "extract"
    INSTALL_LIBRARY = "install"

    def __init__(
        self,
        info: VFXPackageInfo,
        *,
        thumbnail_bytes: bytes | None = None,
        installed_versions: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.info = info
        self.choice = ""
        self.setWindowTitle(f"VFX Package — {info.name}")
        self.setMinimumSize(620, 500)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        heading_row = QHBoxLayout()
        thumbnail = QLabel(self)
        thumbnail.setFixedSize(150, 150)
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail.setObjectName("assetThumbnail")
        pixmap = QPixmap()
        if thumbnail_bytes:
            pixmap.loadFromData(thumbnail_bytes, "PNG")
        if pixmap.isNull():
            thumbnail.setText("No thumbnail")
        else:
            thumbnail.setPixmap(
                pixmap.scaled(
                    thumbnail.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        heading_row.addWidget(thumbnail, 0, Qt.AlignmentFlag.AlignTop)

        metadata = QVBoxLayout()
        title = QLabel(info.name, self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        metadata.addWidget(title)
        state = QLabel("Validated VFX Texture Lab package", self)
        state.setObjectName("successText")
        metadata.addWidget(state)
        metadata.addSpacing(4)
        metadata.addWidget(QLabel(f"Version: {info.asset_version}", self))
        metadata.addWidget(QLabel(f"Author: {info.author or 'Unknown'}", self))
        metadata.addWidget(QLabel(f"Category: {info.category or 'Graph Assets'}", self))
        tags = QLabel("Tags: " + (", ".join(info.tags) if info.tags else "None"), self)
        tags.setWordWrap(True)
        metadata.addWidget(tags)
        metadata.addStretch(1)
        heading_row.addLayout(metadata, 1)
        outer.addLayout(heading_row)

        if info.description:
            description = QLabel(info.description, self)
            description.setWordWrap(True)
            description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            outer.addWidget(description)

        if installed_versions:
            installed = QLabel(
                "Already installed: " + ", ".join(installed_versions), self
            )
            installed.setWordWrap(True)
            installed.setObjectName("warningText")
            outer.addWidget(installed)

        details_frame = QFrame(self)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(9, 9, 9, 9)
        details_layout.setSpacing(4)
        details_layout.addWidget(QLabel(f"Asset ID: {info.asset_id}", details_frame))
        details_layout.addWidget(QLabel(f"Created with: {info.created_with or 'Unknown'}", details_frame))
        details_layout.addWidget(QLabel(f"Package format: version {info.manifest.get('version', 1)}", details_frame))
        details_layout.addWidget(QLabel(f"Entry graph: {info.entry_graph}", details_frame))
        details_layout.addWidget(
            QLabel(
                f"Contents: {len(info.files)} file{'s' if len(info.files) != 1 else ''} · {info.total_size / 1024.0:.1f} KiB",
                details_frame,
            )
        )
        if info.custom_nodes:
            details_layout.addWidget(
                QLabel(
                    "Bundled custom nodes: " + ", ".join(
                        f"{entry.get('name') or entry.get('package_id')} {entry.get('version') or ''}".strip()
                        for entry in info.custom_nodes
                    ),
                    details_frame,
                )
            )
        if info.image_sources:
            details_layout.addWidget(
                QLabel(
                    f"Included image source files: {len(info.image_sources)}",
                    details_frame,
                )
            )
        if info.export_templates:
            details_layout.addWidget(
                QLabel(
                    "Included export templates: " + ", ".join(
                        f"{entry.get('name') or 'Template'} {entry.get('version') or ''}".strip()
                        for entry in info.export_templates
                    ),
                    details_frame,
                )
            )
        source = QLabel(str(info.source_path), details_frame)
        source.setWordWrap(True)
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(source)
        outer.addWidget(details_frame)

        file_scroll = QScrollArea(self)
        file_scroll.setWidgetResizable(True)
        file_scroll.setMaximumHeight(120)
        file_host = QWidget(file_scroll)
        file_layout = QVBoxLayout(file_host)
        file_layout.setContentsMargins(6, 6, 6, 6)
        file_layout.setSpacing(2)
        visible_files = info.files[:80]
        for entry in visible_files:
            label = QLabel(f"{entry.kind.title()} · {entry.path} · {entry.size / 1024.0:.1f} KiB", file_host)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            file_layout.addWidget(label)
        if len(info.files) > len(visible_files):
            more = QLabel(f"…and {len(info.files) - len(visible_files)} more file(s)", file_host)
            more.setObjectName("muted")
            file_layout.addWidget(more)
        file_layout.addStretch(1)
        file_scroll.setWidget(file_host)
        outer.addWidget(file_scroll)

        explanation = QLabel(
            "Open Temporarily loads the package as an unsaved graph and never modifies the archive. "
            "Extract creates a normal editable project folder. Install copies the validated package into the managed Graph Asset library.",
            self,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        outer.addWidget(explanation)

        buttons = QDialogButtonBox(self)
        open_button = QPushButton("Open Temporarily", buttons)
        extract_button = QPushButton("Extract as Editable Project…", buttons)
        install_button = QPushButton("Install to Asset Library", buttons)
        close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(open_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(extract_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(install_button, QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(lambda: self._finish(self.OPEN_TEMPORARILY))
        extract_button.clicked.connect(lambda: self._finish(self.EXTRACT_EDITABLE))
        install_button.clicked.connect(lambda: self._finish(self.INSTALL_LIBRARY))
        close_button.clicked.connect(self.reject)
        outer.addWidget(buttons)

    def _finish(self, choice: str) -> None:
        self.choice = str(choice)
        self.accept()
