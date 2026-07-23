from __future__ import annotations

from dataclasses import dataclass, field
import json

from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..graph.mime import GRAPH_RESOURCE_MIME_TYPE, OPEN_GRAPH_MIME_TYPE


@dataclass(frozen=True, slots=True)
class ExplorerFolderInfo:
    uid: str
    name: str
    parent_uid: str = ""


@dataclass(frozen=True, slots=True)
class ExplorerResourceInfo:
    uid: str
    name: str
    kind: str
    folder_uid: str = ""
    status: str = "missing"
    status_text: str = "Missing source"
    path: str = ""
    embedded: bool = False
    uses: int = 0


@dataclass(frozen=True, slots=True)
class ExplorerGraphInfo:
    uid: str
    name: str
    path: str = ""
    dirty: bool = False
    active: bool = False
    embedded: bool = False
    warning: str = ""
    folders: tuple[ExplorerFolderInfo, ...] = field(default_factory=tuple)
    resources: tuple[ExplorerResourceInfo, ...] = field(default_factory=tuple)


class _GraphTree(QTreeWidget):
    graphActivated = Signal(str)
    graphSelected = Signal(str)
    resourceSelected = Signal(str, str)
    itemContextRequested = Signal(str, str, str, object)

    ROLE_UID = Qt.ItemDataRole.UserRole
    ROLE_KIND = Qt.ItemDataRole.UserRole + 1
    ROLE_GRAPH_UID = Qt.ItemDataRole.UserRole + 2
    ROLE_PATH = Qt.ItemDataRole.UserRole + 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(16)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.itemDoubleClicked.connect(self._activate_item)
        self.itemClicked.connect(self._select_item)

    def _item_identity(self, item: QTreeWidgetItem) -> tuple[str, str, str]:
        kind = str(item.data(0, self.ROLE_KIND) or "")
        uid = str(item.data(0, self.ROLE_UID) or "")
        graph_value = item.data(0, self.ROLE_GRAPH_UID)
        graph_uid = str(graph_value or (uid if kind == "graph" else ""))
        return kind, graph_uid, uid

    def _activate_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        kind, graph_uid, uid = self._item_identity(item)
        if kind == "graph" and uid:
            self.graphActivated.emit(uid)
        elif kind == "resource" and graph_uid and uid:
            self.resourceSelected.emit(graph_uid, uid)

    def _select_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        kind, _graph_uid, uid = self._item_identity(item)
        if kind == "graph" and uid:
            self.graphSelected.emit(uid)
        # Resource activation is deliberately double-click/context-menu only,
        # so browsing the hierarchy does not unexpectedly move graph focus.

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self._activate_item(item, 0)
                event.accept()
                return
        super().keyPressEvent(event)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        kind, graph_uid, uid = self._item_identity(item)
        if not uid:
            return
        mime = QMimeData()
        if kind == "graph":
            mime.setData(OPEN_GRAPH_MIME_TYPE, QByteArray(uid.encode("utf-8")))
            mime.setText(item.text(0).removesuffix(" *"))
        elif kind == "resource" and graph_uid:
            payload = json.dumps(
                {"graph_uid": graph_uid, "resource_uid": uid},
                separators=(",", ":"),
            ).encode("utf-8")
            mime.setData(GRAPH_RESOURCE_MIME_TYPE, QByteArray(payload))
            mime.setText(item.text(0))
        else:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        kind, graph_uid, uid = self._item_identity(item)
        if kind and graph_uid and uid:
            self.itemContextRequested.emit(kind, graph_uid, uid, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)


class GraphExplorer(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    saveRequested = Signal(str)
    saveAsRequested = Signal(str)
    saveCopyRequested = Signal(str)
    saveAllRequested = Signal()
    activateRequested = Signal(str)
    selectedRequested = Signal(str)
    closeRequested = Signal(str)
    closeOthersRequested = Signal(str)
    duplicateRequested = Signal(str)
    revealRequested = Signal(str)
    reloadRequested = Signal(str)
    addToLibraryRequested = Signal(str)

    addFolderRequested = Signal(str, str)
    renameFolderRequested = Signal(str, str)
    removeFolderRequested = Signal(str, str)
    resourceSelectedRequested = Signal(str, str)
    resourceRelinkRequested = Signal(str, str)
    resourceEmbedRequested = Signal(str, str)
    resourceRestoreRequested = Signal(str, str)
    resourceRevealRequested = Signal(str, str)
    resourceRenameRequested = Signal(str, str)
    resourceMoveRequested = Signal(str, str, str)
    resourceRemoveRequested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._infos: dict[str, ExplorerGraphInfo] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        outer.setSpacing(4)

        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(3)
        self.new_button = self._tool_button("+", "New graph")
        self.open_button = self._tool_button("Open", "Open graph")
        self.save_button = self._tool_button("Save", "Save selected graph")
        self.save_all_button = self._tool_button("Save All", "Save all modified graphs")
        self.folder_button = self._tool_button("Folder +", "Add a virtual resource folder to the selected graph")
        tools.addWidget(self.new_button)
        tools.addWidget(self.open_button)
        tools.addWidget(self.save_button)
        tools.addWidget(self.save_all_button)
        tools.addWidget(self.folder_button)
        tools.addStretch(1)
        outer.addLayout(tools)

        self.tree = _GraphTree(self)
        self.tree.setToolTip(
            "Graphs are parents of their imported image and mesh resources. Double-click a graph to edit it, "
            "or a resource to select a node that uses it. Drag a graph onto the active canvas to create a nested Graph Instance; "
            "drag an image or mesh resource onto a canvas to create its matching input node. Cross-graph drops copy the resource first."
        )
        outer.addWidget(self.tree, 1)

        self.new_button.clicked.connect(self.newRequested.emit)
        self.open_button.clicked.connect(self.openRequested.emit)
        self.save_button.clicked.connect(self._save_current)
        self.save_all_button.clicked.connect(self.saveAllRequested.emit)
        self.folder_button.clicked.connect(self._add_folder_current)
        self.tree.graphActivated.connect(self.activateRequested.emit)
        self.tree.graphSelected.connect(self.selectedRequested.emit)
        self.tree.resourceSelected.connect(self.resourceSelectedRequested.emit)
        self.tree.itemContextRequested.connect(self._show_context_menu)

    @staticmethod
    def _tool_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        return button

    def _current_graph_and_folder(self) -> tuple[str, str]:
        item = self.tree.currentItem()
        if item is None:
            return "", ""
        kind = str(item.data(0, self.tree.ROLE_KIND) or "")
        graph_uid = str(item.data(0, self.tree.ROLE_GRAPH_UID) or "")
        uid = str(item.data(0, self.tree.ROLE_UID) or "")
        if kind == "graph":
            return uid, ""
        if kind == "folder":
            return graph_uid, uid
        if kind == "resource":
            info = self._infos.get(graph_uid)
            resource = next((entry for entry in (info.resources if info else ()) if entry.uid == uid), None)
            return graph_uid, resource.folder_uid if resource is not None else ""
        return "", ""

    def _add_folder_current(self) -> None:
        graph_uid, parent_uid = self._current_graph_and_folder()
        if graph_uid:
            self.addFolderRequested.emit(graph_uid, parent_uid)

    def _save_current(self) -> None:
        graph_uid, _folder_uid = self._current_graph_and_folder()
        if graph_uid:
            self.saveRequested.emit(graph_uid)

    def _folder_labels(self, info: ExplorerGraphInfo) -> list[tuple[str, str]]:
        folders = {entry.uid: entry for entry in info.folders}

        def label(folder: ExplorerFolderInfo) -> str:
            parts = [folder.name]
            parent = folders.get(folder.parent_uid)
            seen = {folder.uid}
            while parent is not None and parent.uid not in seen:
                seen.add(parent.uid)
                parts.append(parent.name)
                parent = folders.get(parent.parent_uid)
            return " / ".join(reversed(parts))

        return sorted(((folder.uid, label(folder)) for folder in info.folders), key=lambda item: item[1].casefold())

    def _show_context_menu(self, kind: str, graph_uid: str, uid: str, global_pos: QPoint) -> None:
        info = self._infos.get(graph_uid)
        if info is None:
            return
        if kind == "graph":
            self._show_graph_context_menu(graph_uid, global_pos)
            return
        if kind == "folder":
            menu = QMenu(self)
            add = menu.addAction("New Subfolder…")
            rename = menu.addAction("Rename Folder…")
            remove = menu.addAction("Remove Folder")
            chosen = menu.exec(global_pos)
            if chosen is add:
                self.addFolderRequested.emit(graph_uid, uid)
            elif chosen is rename:
                self.renameFolderRequested.emit(graph_uid, uid)
            elif chosen is remove:
                self.removeFolderRequested.emit(graph_uid, uid)
            return
        if kind != "resource":
            return
        resource = next((entry for entry in info.resources if entry.uid == uid), None)
        if resource is None:
            return
        menu = QMenu(self)
        menu.addSection(resource.status_text)
        select = menu.addAction(f"Select Using Node{'s' if resource.uses != 1 else ''} ({resource.uses})")
        select.setEnabled(resource.uses > 0)
        relink = menu.addAction("Relink / Replace Source…")
        embed = menu.addAction("Make Local / Embed in Graph")
        embed.setEnabled(bool(resource.path or resource.embedded))
        restore = menu.addAction("Restore Embedded Copy As…")
        restore.setEnabled(resource.embedded)
        reveal = menu.addAction("Reveal Source in File Manager")
        reveal.setEnabled(bool(resource.path))
        menu.addSeparator()
        rename = menu.addAction("Rename Resource…")
        move_menu = menu.addMenu("Move to Folder")
        root_action = move_menu.addAction("Graph Root")
        root_action.setData("")
        root_action.setCheckable(True)
        root_action.setChecked(not resource.folder_uid)
        move_actions = [root_action]
        for folder_uid, label in self._folder_labels(info):
            action = move_menu.addAction(label)
            action.setData(folder_uid)
            action.setCheckable(True)
            action.setChecked(folder_uid == resource.folder_uid)
            move_actions.append(action)
        remove = menu.addAction("Remove Unused Resource")
        remove.setEnabled(resource.uses == 0)
        chosen = menu.exec(global_pos)
        if chosen is select:
            self.resourceSelectedRequested.emit(graph_uid, uid)
        elif chosen is relink:
            self.resourceRelinkRequested.emit(graph_uid, uid)
        elif chosen is embed:
            self.resourceEmbedRequested.emit(graph_uid, uid)
        elif chosen is restore:
            self.resourceRestoreRequested.emit(graph_uid, uid)
        elif chosen is reveal:
            self.resourceRevealRequested.emit(graph_uid, uid)
        elif chosen is rename:
            self.resourceRenameRequested.emit(graph_uid, uid)
        elif chosen is remove:
            self.resourceRemoveRequested.emit(graph_uid, uid)
        elif chosen in move_actions:
            self.resourceMoveRequested.emit(graph_uid, uid, str(chosen.data() or ""))

    def _show_graph_context_menu(self, uid: str, global_pos: QPoint) -> None:
        item = self._items.get(uid)
        if item is None:
            return
        path = str(item.data(0, self.tree.ROLE_PATH) or "")
        menu = QMenu(self)
        activate = menu.addAction("Open / Activate")
        save = menu.addAction("Save")
        save_as = menu.addAction("Save As…")
        save_copy = menu.addAction("Save a Copy…")
        menu.addSeparator()
        new_folder = menu.addAction("New Resource Folder…")
        duplicate = menu.addAction("Duplicate Graph")
        reload_action = menu.addAction("Reload from Disk")
        reload_action.setEnabled(bool(path))
        reveal = menu.addAction("Reveal in File Manager")
        reveal.setEnabled(bool(path))
        add_library = menu.addAction("Add Parent Folder to Graph Assets")
        add_library.setEnabled(bool(path))
        menu.addSeparator()
        close = menu.addAction("Close")
        close_others = menu.addAction("Close Others")
        close_others.setEnabled(len(self._items) > 1)
        chosen = menu.exec(global_pos)
        if chosen is activate:
            self.activateRequested.emit(uid)
        elif chosen is save:
            self.saveRequested.emit(uid)
        elif chosen is save_as:
            self.saveAsRequested.emit(uid)
        elif chosen is save_copy:
            self.saveCopyRequested.emit(uid)
        elif chosen is new_folder:
            self.addFolderRequested.emit(uid, "")
        elif chosen is duplicate:
            self.duplicateRequested.emit(uid)
        elif chosen is reload_action:
            self.reloadRequested.emit(uid)
        elif chosen is reveal:
            self.revealRequested.emit(uid)
        elif chosen is add_library:
            self.addToLibraryRequested.emit(uid)
        elif chosen is close:
            self.closeRequested.emit(uid)
        elif chosen is close_others:
            self.closeOthersRequested.emit(uid)

    @staticmethod
    def _expanded_uids(root: QTreeWidgetItem) -> set[str]:
        expanded: set[str] = set()
        stack = [root]
        while stack:
            item = stack.pop()
            if item.isExpanded():
                uid = str(item.data(0, _GraphTree.ROLE_UID) or "")
                if uid:
                    expanded.add(uid)
            stack.extend(item.child(index) for index in range(item.childCount()))
        return expanded

    def _build_children(self, root: QTreeWidgetItem, info: ExplorerGraphInfo, expanded: set[str]) -> None:
        root.takeChildren()
        folder_items: dict[str, QTreeWidgetItem] = {}
        pending = list(info.folders)
        while pending:
            progressed = False
            for folder in list(pending):
                if folder.parent_uid and folder.parent_uid not in folder_items:
                    continue
                parent = folder_items.get(folder.parent_uid, root)
                item = QTreeWidgetItem(parent)
                item.setText(0, f"📁 {folder.name}")
                item.setData(0, self.tree.ROLE_UID, folder.uid)
                item.setData(0, self.tree.ROLE_KIND, "folder")
                item.setData(0, self.tree.ROLE_GRAPH_UID, info.uid)
                item.setToolTip(0, "Virtual graph folder. It organises imported resources without moving files on disk.")
                item.setExpanded(folder.uid in expanded)
                folder_items[folder.uid] = item
                pending.remove(folder)
                progressed = True
            if not progressed:
                # Malformed parent cycles are repaired visually at the graph root.
                for folder in pending:
                    item = QTreeWidgetItem(root)
                    item.setText(0, f"📁 {folder.name}")
                    item.setData(0, self.tree.ROLE_UID, folder.uid)
                    item.setData(0, self.tree.ROLE_KIND, "folder")
                    item.setData(0, self.tree.ROLE_GRAPH_UID, info.uid)
                    folder_items[folder.uid] = item
                break

        status_suffix = {
            "missing": "  ⚠ missing",
            "embedded": "  • embedded",
            "linked+embedded": "  • linked + embedded",
            "linked": "",
        }
        for resource in sorted(info.resources, key=lambda entry: (entry.folder_uid, entry.name.casefold())):
            parent = folder_items.get(resource.folder_uid, root)
            item = QTreeWidgetItem(parent)
            icon = "◇" if resource.kind == "mesh" else "▧"
            item.setText(0, f"{icon} {resource.name}{status_suffix.get(resource.status, '')}")
            item.setData(0, self.tree.ROLE_UID, resource.uid)
            item.setData(0, self.tree.ROLE_KIND, "resource")
            item.setData(0, self.tree.ROLE_GRAPH_UID, info.uid)
            item.setData(0, self.tree.ROLE_PATH, resource.path)
            kind_name = "Mesh" if resource.kind == "mesh" else "Image"
            item.setToolTip(
                0,
                f"{kind_name} resource · {resource.status_text}\n"
                f"Used by {resource.uses} node{'s' if resource.uses != 1 else ''}"
                + (f"\n{resource.path}" if resource.path else ""),
            )

    def update_graph(self, info: ExplorerGraphInfo) -> None:
        self._infos[info.uid] = info
        item = self._items.get(info.uid)
        if item is None:
            item = QTreeWidgetItem(self.tree)
            item.setData(0, self.tree.ROLE_UID, info.uid)
            item.setData(0, self.tree.ROLE_KIND, "graph")
            item.setData(0, self.tree.ROLE_GRAPH_UID, info.uid)
            item.setExpanded(True)
            self._items[info.uid] = item
        expanded = self._expanded_uids(item)
        label = info.name + (" *" if info.dirty else "")
        item.setText(0, label)
        item.setData(0, self.tree.ROLE_PATH, info.path)
        tooltip_parts = [info.path if info.path else "Unsaved graph"]
        if info.resources:
            images = sum(1 for entry in info.resources if entry.kind == "image")
            meshes = sum(1 for entry in info.resources if entry.kind == "mesh")
            tooltip_parts.append(f"Resources: {images} image(s), {meshes} mesh(es)")
        if info.warning:
            tooltip_parts.append(info.warning)
        item.setToolTip(0, "\n".join(tooltip_parts))
        font = item.font(0)
        font.setBold(info.active)
        item.setFont(0, font)
        self._build_children(item, info, expanded)
        if info.active:
            self.tree.setCurrentItem(item)

    def remove_graph(self, uid: str) -> None:
        self._infos.pop(str(uid), None)
        item = self._items.pop(str(uid), None)
        if item is None:
            return
        index = self.tree.indexOfTopLevelItem(item)
        if index >= 0:
            self.tree.takeTopLevelItem(index)

    def set_active(self, uid: str) -> None:
        for key, item in self._items.items():
            font = item.font(0)
            font.setBold(key == uid)
            item.setFont(0, font)
        item = self._items.get(uid)
        if item is not None:
            current = self.tree.currentItem()
            current_graph = str(current.data(0, self.tree.ROLE_GRAPH_UID) or "") if current is not None else ""
            if current_graph != uid:
                self.tree.setCurrentItem(item)
