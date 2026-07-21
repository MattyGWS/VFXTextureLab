from __future__ import annotations

from dataclasses import dataclass

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

from ..graph.mime import OPEN_GRAPH_MIME_TYPE


@dataclass(frozen=True, slots=True)
class ExplorerGraphInfo:
    uid: str
    name: str
    path: str = ""
    dirty: bool = False
    active: bool = False
    embedded: bool = False
    warning: str = ""


class _GraphTree(QTreeWidget):
    graphActivated = Signal(str)
    graphSelected = Signal(str)
    graphCloseRequested = Signal(str)
    graphContextRequested = Signal(str, object)

    ROLE_UID = Qt.ItemDataRole.UserRole

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(8)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.itemDoubleClicked.connect(self._activate_item)
        self.itemClicked.connect(self._select_item)

    def _activate_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        uid = str(item.data(0, self.ROLE_UID) or "")
        if uid:
            self.graphActivated.emit(uid)

    def _select_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        uid = str(item.data(0, self.ROLE_UID) or "")
        if uid:
            self.graphSelected.emit(uid)

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
        uid = str(item.data(0, self.ROLE_UID) or "")
        if not uid:
            return
        mime = QMimeData()
        mime.setData(OPEN_GRAPH_MIME_TYPE, QByteArray(uid.encode("utf-8")))
        mime.setText(item.text(0).removesuffix(" *"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        uid = str(item.data(0, self.ROLE_UID) or "")
        if uid:
            self.graphContextRequested.emit(uid, event.globalPos())
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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: dict[str, QTreeWidgetItem] = {}

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
        tools.addWidget(self.new_button)
        tools.addWidget(self.open_button)
        tools.addWidget(self.save_button)
        tools.addWidget(self.save_all_button)
        tools.addStretch(1)
        outer.addLayout(tools)

        self.tree = _GraphTree(self)
        self.tree.setToolTip(
            "Double-click to edit a graph. Drag a graph onto the active canvas to create a nested Graph Instance."
        )
        outer.addWidget(self.tree, 1)

        self.new_button.clicked.connect(self.newRequested.emit)
        self.open_button.clicked.connect(self.openRequested.emit)
        self.save_button.clicked.connect(self._save_current)
        self.save_all_button.clicked.connect(self.saveAllRequested.emit)
        self.tree.graphActivated.connect(self.activateRequested.emit)
        self.tree.graphSelected.connect(self.selectedRequested.emit)
        self.tree.graphContextRequested.connect(self._show_context_menu)

    @staticmethod
    def _tool_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        return button

    def _save_current(self) -> None:
        item = self.tree.currentItem()
        uid = str(item.data(0, self.tree.ROLE_UID) or "") if item is not None else ""
        if uid:
            self.saveRequested.emit(uid)

    def _show_context_menu(self, uid: str, global_pos: QPoint) -> None:
        item = self._items.get(uid)
        if item is None:
            return
        path = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
        menu = QMenu(self)
        activate = menu.addAction("Open / Activate")
        save = menu.addAction("Save")
        save_as = menu.addAction("Save As…")
        save_copy = menu.addAction("Save a Copy…")
        menu.addSeparator()
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

    def update_graph(self, info: ExplorerGraphInfo) -> None:
        item = self._items.get(info.uid)
        if item is None:
            item = QTreeWidgetItem(self.tree)
            item.setData(0, self.tree.ROLE_UID, info.uid)
            self._items[info.uid] = item
        label = info.name + (" *" if info.dirty else "")
        item.setText(0, label)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, info.path)
        tooltip_parts = []
        if info.path:
            tooltip_parts.append(info.path)
        else:
            tooltip_parts.append("Unsaved graph")
        if info.warning:
            tooltip_parts.append(info.warning)
        item.setToolTip(0, "\n".join(tooltip_parts))
        font = item.font(0)
        font.setBold(info.active)
        item.setFont(0, font)
        if info.active:
            self.tree.setCurrentItem(item)

    def remove_graph(self, uid: str) -> None:
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
            self.tree.setCurrentItem(item)
