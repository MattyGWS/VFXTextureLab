from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..graph.mime import GRAPH_ASSET_MIME_TYPE, NODE_MIME_TYPE, USER_NODE_MIME_TYPE
from ..graph_asset_thumbnails import thumbnail_pixmap
from ..nodes.registry import NodeRegistry
from ..user_nodes import load_user_node_files, user_node_directory
from ..graph_asset_library import (
    add_graph_asset_directory,
    default_graph_asset_directory,
    graph_asset_directories,
    inspect_graph_asset_file,
    load_graph_asset_files,
    remove_graph_asset_directory,
)
from .node_preferences import NodePreferences

ROLE_VALUE = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_INTERFACE = Qt.ItemDataRole.UserRole + 2


class NodeLibraryTree(QTreeWidget):
    """Tree that exports built-in and reusable user nodes through Qt drag/drop."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions) -> None:
        del supported_actions
        item = self.currentItem()
        if item is None:
            return
        value = item.data(0, ROLE_VALUE)
        kind = item.data(0, ROLE_KIND)
        if not value or kind not in ("builtin", "user", "asset"):
            return

        mime = QMimeData()
        mime_type = {
            "builtin": NODE_MIME_TYPE,
            "user": USER_NODE_MIME_TYPE,
            "asset": GRAPH_ASSET_MIME_TYPE,
        }[str(kind)]
        mime.setData(mime_type, QByteArray(str(value).encode("utf-8")))
        mime.setText(str(value))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class GraphAssetDetails(QWidget):
    """Compact, evaluation-free metadata preview for a selected library asset."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMaximumHeight(215)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(3)

        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("separator")
        layout.addWidget(divider)

        top = QWidget(self)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        self.thumbnail = QLabel(top)
        self.thumbnail.setFixedSize(88, 88)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setObjectName("assetThumbnail")
        self.thumbnail.setText("No thumbnail")
        top_layout.addWidget(self.thumbnail)

        headline = QWidget(top)
        headline_layout = QVBoxLayout(headline)
        headline_layout.setContentsMargins(0, 0, 0, 0)
        headline_layout.setSpacing(2)
        self.name = QLabel(headline)
        self.name.setObjectName("sectionTitle")
        self.name.setWordWrap(True)
        headline_layout.addWidget(self.name)
        self.status = QLabel(headline)
        self.status.setWordWrap(True)
        headline_layout.addWidget(self.status)
        self.metadata = QLabel(headline)
        self.metadata.setWordWrap(True)
        self.metadata.setObjectName("muted")
        headline_layout.addWidget(self.metadata)
        headline_layout.addStretch(1)
        top_layout.addWidget(headline, 1)
        layout.addWidget(top)

        self.description = QLabel(self)
        self.description.setWordWrap(True)
        self.description.setMaximumHeight(38)
        self.description.setObjectName("muted")
        layout.addWidget(self.description)

        self.outputs = QLabel(self)
        self.outputs.setWordWrap(True)
        self.outputs.setMaximumHeight(36)
        self.outputs.setObjectName("muted")
        layout.addWidget(self.outputs)

        self.source = QLabel(self)
        self.source.setObjectName("muted")
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source)
        self.hide()

    def set_asset(self, path: Path, interface: dict) -> None:
        pixmap = thumbnail_pixmap(interface.get("thumbnail_png"), 88)
        if pixmap.isNull():
            self.thumbnail.setPixmap(pixmap)
            self.thumbnail.setText("No thumbnail")
        else:
            self.thumbnail.setText("")
            self.thumbnail.setPixmap(pixmap)

        self.name.setText(str(interface.get("name") or path.stem))
        valid = bool(interface.get("valid", True))
        problems = [str(value) for value in interface.get("problems", ()) if str(value)]
        if valid and problems:
            self.status.setText("Ready with warnings")
            self.status.setToolTip("\n".join(problems))
            self.status.setObjectName("warningText")
        elif valid:
            self.status.setText("Ready · Valid asset")
            self.status.setToolTip("")
            self.status.setObjectName("muted")
        else:
            self.status.setText("Needs attention")
            self.status.setToolTip("\n".join(problems))
            self.status.setObjectName("warningText")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

        self.description.setText(str(interface.get("description") or "No description."))
        self.description.setToolTip(str(interface.get("description") or ""))
        author = str(interface.get("author") or "Unknown author")
        version = str(interface.get("asset_version") or "1.0.0")
        self.metadata.setText(f"{author} · v{version}")
        tags = ", ".join(str(value) for value in interface.get("tags", ()) if str(value))
        output_names = [str(entry.get("name", "Output")) for entry in interface.get("outputs", ())]
        summary = "Outputs: " + (", ".join(output_names) if output_names else "None")
        if tags:
            summary += f"\nTags: {tags}"
        self.outputs.setText(summary)
        self.source.setText(f"Source: {path.name}")
        self.source.setToolTip(str(path))
        self.show()


class NodeLibrary(QWidget):
    nodeActivated = Signal(str)
    userNodeActivated = Signal(str)
    graphAssetActivated = Signal(str)
    graphAssetOpenRequested = Signal(str)
    graphAssetThumbnailRequested = Signal(str)
    reloadCustomNodesRequested = Signal()

    def __init__(self, registry: NodeRegistry, preferences: NodePreferences, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.preferences = preferences
        self.settings = QSettings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter library…")
        self.tree = NodeLibraryTree()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.details = GraphAssetDetails(self)

        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        self.add_asset_folder_button = QPushButton("Add Asset Folder…")
        self.open_asset_folder_button = QPushButton("Open Assets")
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setToolTip("Refresh built-in nodes, user nodes and graph assets")
        self.refresh_button.setFixedWidth(30)
        buttons.addWidget(self.add_asset_folder_button)
        buttons.addWidget(self.open_asset_folder_button)
        buttons.addWidget(self.refresh_button)
        layout.addLayout(buttons)

        self.search.textChanged.connect(self.rebuild)
        self.tree.itemDoubleClicked.connect(self._activated)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.preferences.changed.connect(self.rebuild)
        self.add_asset_folder_button.clicked.connect(self._add_asset_folder)
        self.open_asset_folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(default_graph_asset_directory())))
        )
        self.refresh_button.clicked.connect(self.rebuild)
        self.rebuild()

    def _category_item(self, cache: dict[str, QTreeWidgetItem], path: str) -> QTreeWidgetItem:
        normalised = "/".join(part.strip() for part in path.split("/") if part.strip()) or "Other"
        parent: QTreeWidgetItem | None = None
        accumulated: list[str] = []
        for part in normalised.split("/"):
            accumulated.append(part)
            key = "/".join(accumulated)
            item = cache.get(key)
            if item is None:
                item = QTreeWidgetItem([part])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                if parent is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                cache[key] = item
            parent = item
        assert parent is not None
        return parent

    @staticmethod
    def _asset_search_text(path: Path, interface: dict) -> str:
        outputs = " ".join(str(entry.get("name", "")) for entry in interface.get("outputs", ()))
        return " ".join((
            str(interface.get("name", path.stem)),
            str(interface.get("description", "")),
            str(interface.get("category", "")),
            " ".join(str(value) for value in interface.get("tags", ())),
            str(interface.get("author", "")),
            str(interface.get("asset_version", "")),
            outputs,
            path.name,
        )).casefold()

    def rebuild(self) -> None:
        text = self.search.text().strip().casefold()
        terms = text.split()
        favourites = set(self.preferences.favourites())
        definitions = self.registry.search(text)

        self.tree.clear()
        self.details.hide()
        categories: dict[str, QTreeWidgetItem] = {}

        def add_builtin(parent: QTreeWidgetItem, definition, *, mark_favourite: bool = True) -> None:
            prefix = "★  " if mark_favourite and definition.type_id in favourites else ""
            item = QTreeWidgetItem([prefix + definition.name])
            item.setData(0, ROLE_VALUE, definition.type_id)
            item.setData(0, ROLE_KIND, "builtin")
            package = definition.package
            tooltip = definition.description
            if package is not None:
                tooltip += (
                    f"\n\nPackage: {package.package_id} {package.version}"
                    f"\nSource: {package.library_name}"
                    f"\nFolder: {package.root}"
                )
            item.setToolTip(0, tooltip)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            parent.addChild(item)

        if not text and favourites:
            ordered_favourites = self.preferences.favourites()
            by_type = {definition.type_id: definition for definition in definitions}
            favourite_definitions = [by_type[type_id] for type_id in ordered_favourites if type_id in by_type]
            if favourite_definitions:
                favourite_category = self._category_item(categories, "★ Favourites")
                for definition in favourite_definitions:
                    add_builtin(favourite_category, definition, mark_favourite=False)

        for definition in definitions:
            category_item = self._category_item(categories, definition.category)
            add_builtin(category_item, definition)

        for path, data in load_user_node_files():
            name = str(data.get("name", path.stem))
            description = str(data.get("description", "Reusable user group"))
            category = str(data.get("category", "User")).strip() or "User"
            if not category.lower().startswith("user"):
                category = f"User/{category}"
            haystack = f"{name} {description} {category} {path.name}".casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            category_item = self._category_item(categories, category)
            item = QTreeWidgetItem([name])
            item.setData(0, ROLE_VALUE, str(path))
            item.setData(0, ROLE_KIND, "user")
            item.setToolTip(0, description or str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            category_item.addChild(item)

        for path, interface in load_graph_asset_files(self.registry, self.settings, include_invalid=True):
            if terms and not all(term in self._asset_search_text(path, interface) for term in terms):
                continue
            valid = bool(interface.get("valid", True))
            if valid:
                category = str(interface.get("category", "Graph Assets")).strip() or "Graph Assets"
                if not category.casefold().startswith("graph assets"):
                    category = f"Graph Assets/{category}"
            else:
                category = "Graph Assets/Problems"
            category_item = self._category_item(categories, category)
            name = str(interface.get("name", path.stem))
            warning = bool(interface.get("has_warnings"))
            prefix = "△  " if valid and warning else ("" if valid else "⚠  ")
            item = QTreeWidgetItem([prefix + name])
            item.setData(0, ROLE_VALUE, str(path))
            item.setData(0, ROLE_KIND, "asset" if valid else "asset_problem")
            item.setData(0, ROLE_INTERFACE, interface)
            output_names = ", ".join(str(entry.get("name", "Output")) for entry in interface.get("outputs", ()))
            tooltip = str(interface.get("description", "Reusable graph asset"))
            if valid:
                tooltip += f"\n\nOutputs: {output_names}\nSource: {path}"
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            else:
                problems = "\n".join(f"• {value}" for value in interface.get("problems", ()))
                tooltip += f"\n\nProblems:\n{problems}\n\nSource: {path}"
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            item.setToolTip(0, tooltip)
            category_item.addChild(item)

        for item in categories.values():
            item.setExpanded(True)

    def _selection_changed(self) -> None:
        item = self.tree.currentItem()
        if item is None or item.data(0, ROLE_KIND) not in {"asset", "asset_problem"}:
            self.details.hide()
            return
        value = item.data(0, ROLE_VALUE)
        interface = item.data(0, ROLE_INTERFACE)
        if not value or not isinstance(interface, dict):
            self.details.hide()
            return
        self.details.set_asset(Path(str(value)), interface)

    def _activated(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        value = item.data(0, ROLE_VALUE)
        kind = item.data(0, ROLE_KIND)
        if not value:
            return
        if kind == "builtin":
            self.nodeActivated.emit(str(value))
        elif kind == "user":
            self.userNodeActivated.emit(str(value))
        elif kind == "asset":
            self.graphAssetActivated.emit(str(value))
        elif kind == "asset_problem":
            self._show_validation(Path(str(value)))

    def _show_validation(self, path: Path) -> None:
        _path, interface = inspect_graph_asset_file(path, self.registry)
        if interface.get("valid"):
            outputs = ", ".join(str(entry.get("name", "Output")) for entry in interface.get("outputs", ()))
            problems = [str(value) for value in interface.get("problems", ()) if str(value)]
            if problems:
                warning_text = "\n".join(f"• {value}" for value in problems)
                QMessageBox.warning(
                    self,
                    "Graph asset is usable with warnings",
                    f"{interface.get('name', path.stem)} can be inserted as a Graph Instance.\n\nPublished outputs: {outputs}\n\nWarnings:\n{warning_text}",
                )
            else:
                QMessageBox.information(
                    self,
                    "Graph asset is valid",
                    f"{interface.get('name', path.stem)} is ready to use.\n\nPublished outputs: {outputs}",
                )
        else:
            problems = "\n".join(f"• {value}" for value in interface.get("problems", ()))
            QMessageBox.warning(
                self,
                "Graph asset needs attention",
                f"{interface.get('name', path.stem)} cannot currently be inserted as a Graph Instance.\n\n{problems}",
            )
        self.rebuild()

    def _context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        value = item.data(0, ROLE_VALUE)
        kind = item.data(0, ROLE_KIND)
        if not value:
            return
        menu = QMenu(self)
        if kind == "builtin":
            type_id = str(value)
            if type_id in self.preferences.favourites():
                favourite_action = menu.addAction("Remove from favourites")
            else:
                favourite_action = menu.addAction("Add to favourites")
            definition = self.registry.get_optional(type_id)
            open_folder = open_shader = reload_action = None
            if definition is not None and definition.package is not None:
                menu.addSeparator()
                open_folder = menu.addAction("Open package folder")
                open_shader = menu.addAction("Open WGSL shader")
                reload_action = menu.addAction("Reload custom nodes")
            selected = menu.exec(self.tree.viewport().mapToGlobal(position))
            if selected is favourite_action:
                self.preferences.toggle_favourite(type_id)
            elif definition is not None and definition.package is not None:
                if selected is open_folder:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(definition.package.root))
                elif selected is open_shader:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(definition.package.shader_path))
                elif selected is reload_action:
                    self.reloadCustomNodesRequested.emit()
            return

        if kind == "user":
            reveal = menu.addAction("Open user node folder")
            selected = menu.exec(self.tree.viewport().mapToGlobal(position))
            if selected is reveal:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_node_directory())))
            return

        if kind in {"asset", "asset_problem"}:
            path = Path(str(value))
            open_source = menu.addAction("Open Source Graph")
            validate = menu.addAction("Validate Asset")
            edit_thumbnail = menu.addAction("Edit Thumbnail in Inspector…")
            menu.addSeparator()
            reveal = menu.addAction("Reveal Source")
            remove_folder = None
            try:
                source_folder = next(
                    (folder for folder in graph_asset_directories(self.settings) if path.is_relative_to(folder)),
                    None,
                )
            except Exception:
                source_folder = None
            if source_folder is not None and source_folder != default_graph_asset_directory():
                remove_folder = menu.addAction("Remove This Asset Folder")
            selected = menu.exec(self.tree.viewport().mapToGlobal(position))
            if selected is open_source:
                self.graphAssetOpenRequested.emit(str(path))
            elif selected is validate:
                self._show_validation(path)
            elif selected is edit_thumbnail:
                self.graphAssetThumbnailRequested.emit(str(path))
            elif selected is reveal:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            elif remove_folder is not None and selected is remove_folder and source_folder is not None:
                remove_graph_asset_directory(source_folder, self.settings)
                self.rebuild()

    def _add_asset_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Add Graph Asset Folder", str(default_graph_asset_directory())
        )
        if selected and add_graph_asset_directory(selected, self.settings):
            self.rebuild()
