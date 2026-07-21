from __future__ import annotations

from typing import Callable

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ..graph_asset_library import load_graph_asset_files
from ..nodes.base import NodeDefinition
from ..nodes.registry import NodeRegistry
from .node_preferences import NodePreferences


class NodeSearchDialog(QDialog):
    def __init__(
        self,
        registry: NodeRegistry,
        preferences: NodePreferences,
        parent=None,
        *,
        definition_filter: Callable[[NodeDefinition], bool] | None = None,
        title: str = "Add Node",
        placeholder: str = "Search nodes…",
        context_title: str = "",
        context_hint: str = "",
        no_results_text: str = "",
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.preferences = preferences
        self.definition_filter = definition_filter
        self.context_title = str(context_title).strip()
        self.context_hint = str(context_hint).strip()
        self.no_results_text = str(no_results_text).strip()
        self.selected_type_id: str | None = None
        self.selected_asset_path: str | None = None
        self.browse_graph_asset = False

        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.resize(390, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(7)

        self.context_title_label = QLabel(self.context_title)
        title_font = self.context_title_label.font()
        title_font.setBold(True)
        self.context_title_label.setFont(title_font)
        self.context_title_label.setVisible(bool(self.context_title))

        self.context_hint_label = QLabel(self.context_hint)
        self.context_hint_label.setWordWrap(True)
        hint_palette = self.context_hint_label.palette()
        hint_palette.setColor(self.context_hint_label.foregroundRole(), hint_palette.mid().color())
        self.context_hint_label.setPalette(hint_palette)
        self.context_hint_label.setVisible(bool(self.context_hint))

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.installEventFilter(self)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setWordWrap(True)

        layout.addWidget(self.context_title_label)
        layout.addWidget(self.context_hint_label)
        layout.addWidget(self.search)
        layout.addWidget(self.list_widget, 1)

        self.search.textChanged.connect(self._populate)
        self.search.returnPressed.connect(self._accept_current)
        # The transient graph search is intentionally faster than the persistent
        # Node Library: one mouse click inserts the chosen result, while native
        # item activation keeps Return/Enter working after keyboard navigation.
        self.list_widget.itemClicked.connect(self._accept_item)
        self.list_widget.itemActivated.connect(self._accept_item)
        self.list_widget.currentItemChanged.connect(lambda *_: None)
        self._populate("")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.search.setFocus()
        self.search.selectAll()

    def _next_selectable_row(self, start: int, direction: int) -> int:
        row = int(start) + int(direction)
        while 0 <= row < self.list_widget.count():
            item = self.list_widget.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                return row
            row += int(direction)
        return int(start)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                direction = 1 if event.key() == Qt.Key.Key_Down else -1
                current = self.list_widget.currentRow()
                target = self._next_selectable_row(current, direction)
                if target != current:
                    self.list_widget.setCurrentRow(target)
                self.list_widget.setFocus()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Down and self.search.hasFocus():
            current = self.list_widget.currentRow()
            target = self._next_selectable_row(current, 1)
            if target != current:
                self.list_widget.setCurrentRow(target)
            self.list_widget.setFocus()
            return
        super().keyPressEvent(event)

    def _header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.gray)
        self.list_widget.addItem(item)

    def _definition_allowed(self, definition: NodeDefinition) -> bool:
        if definition.hidden:
            return False
        return self.definition_filter is None or bool(self.definition_filter(definition))

    def _definition_from_id(self, type_id: str) -> NodeDefinition | None:
        try:
            definition = self.registry.get(type_id)
        except KeyError:
            return None
        return definition if self._definition_allowed(definition) else None

    def _filtered_definitions(self, definitions) -> list[NodeDefinition]:
        return [definition for definition in definitions if self._definition_allowed(definition)]

    def _add_definition(self, definition: NodeDefinition, prefix: str = "") -> None:
        item = QListWidgetItem(f"{prefix}{definition.name}    ·    {definition.category}")
        item.setData(Qt.ItemDataRole.UserRole, definition.type_id)
        item.setToolTip(definition.description)
        self.list_widget.addItem(item)

    def _empty_state(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(Qt.GlobalColor.gray)
        self.list_widget.addItem(item)

    def _add_asset(self, path: Path, interface: dict) -> None:
        name = str(interface.get("name", path.stem))
        category = str(interface.get("category", "Graph Assets") or "Graph Assets")
        item = QListWidgetItem(f"◇  {name}    ·    {category}")
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setData(Qt.ItemDataRole.UserRole + 1, "asset")
        outputs = ", ".join(str(entry.get("name", "Output")) for entry in interface.get("outputs", ()))
        item.setToolTip(f"{interface.get('description', '')}\n\nOutputs: {outputs}\nSource: {path}")
        self.list_widget.addItem(item)

    def _add_asset_browse_action(self) -> None:
        item = QListWidgetItem("＋  Add Graph Asset…")
        item.setData(Qt.ItemDataRole.UserRole, "__browse_graph_asset__")
        item.setData(Qt.ItemDataRole.UserRole + 1, "asset_browse")
        item.setToolTip("Choose any .vfxgraph file and insert it as a linked Graph Instance.")
        self.list_widget.addItem(item)

    def _populate(self, text: str) -> None:
        self.list_widget.clear()
        query = text.strip()
        query_terms = query.casefold().split()
        if query:
            matching_nodes = self._filtered_definitions(self.registry.search(query))
            if matching_nodes:
                self._header("BUILT-IN NODES")
                for definition in matching_nodes:
                    self._add_definition(definition)
        else:
            added: set[str] = set()
            favourites = [
                definition
                for type_id in self.preferences.favourites()
                if (definition := self._definition_from_id(type_id)) is not None
            ]
            if favourites:
                self._header("FAVOURITES")
                for definition in favourites:
                    self._add_definition(definition, "★  ")
                    added.add(definition.type_id)
            recents = [
                definition
                for type_id in self.preferences.recents()
                if type_id not in added
                and (definition := self._definition_from_id(type_id)) is not None
            ]
            if recents:
                self._header("RECENT")
                for definition in recents:
                    self._add_definition(definition, "↻  ")
                    added.add(definition.type_id)
            all_nodes = [
                definition for definition in self._filtered_definitions(self.registry.all())
                if definition.type_id not in added
            ]
            if all_nodes:
                self._header("ALL NODES")
                for definition in all_nodes:
                    self._add_definition(definition)

        # Graph assets are useful in ordinary add-node search, but intentionally
        # omitted from loose-wire connection search to keep that popup focused.
        if self.definition_filter is None:
            assets = []
            for path, interface in load_graph_asset_files(self.registry):
                haystack = " ".join((
                    str(interface.get("name", path.stem)),
                    str(interface.get("description", "")),
                    str(interface.get("category", "")),
                    " ".join(str(value) for value in interface.get("tags", ())),
                    str(interface.get("author", "")),
                    str(interface.get("asset_version", "")),
                    " ".join(str(entry.get("name", "")) for entry in interface.get("outputs", ())),
                    path.name,
                )).casefold()
                if query_terms and not all(term in haystack for term in query_terms):
                    continue
                assets.append((path, interface))
            if assets:
                self._header("GRAPH ASSETS")
                for path, interface in assets:
                    self._add_asset(path, interface)
            self._header("IMPORT")
            self._add_asset_browse_action()

        selectable_rows = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                selectable_rows.append(row)

        if not selectable_rows and self.definition_filter is not None:
            if self.no_results_text:
                message = self.no_results_text.format(query=query or "all nodes")
            elif query:
                message = f'No compatible nodes match “{query}”.'
            else:
                message = "No compatible nodes are available for this connection."
            self._empty_state(message)
            return

        if selectable_rows:
            self.list_widget.setCurrentRow(selectable_rows[0])

    def _accept_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        value = item.data(Qt.ItemDataRole.UserRole)
        if not value:
            return
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        if kind == "asset":
            self.selected_asset_path = str(value)
        elif kind == "asset_browse":
            self.browse_graph_asset = True
        else:
            self.selected_type_id = str(value)
        self.accept()

    def _accept_current(self) -> None:
        self._accept_item(self.list_widget.currentItem())
