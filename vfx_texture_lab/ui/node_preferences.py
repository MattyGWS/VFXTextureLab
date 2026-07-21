from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal


class NodePreferences(QObject):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.settings = QSettings()

    def favourites(self) -> list[str]:
        value = self.settings.value("nodes/favourites", [], list)
        return [str(item) for item in value]

    def recents(self) -> list[str]:
        value = self.settings.value("nodes/recents", [], list)
        return [str(item) for item in value]

    def toggle_favourite(self, type_id: str) -> None:
        items = self.favourites()
        if type_id in items:
            items.remove(type_id)
        else:
            items.insert(0, type_id)
        self.settings.setValue("nodes/favourites", items)
        self.changed.emit()

    def add_recent(self, type_id: str) -> None:
        items = self.recents()
        if type_id in items:
            items.remove(type_id)
        items.insert(0, type_id)
        items = items[:8]
        self.settings.setValue("nodes/recents", items)
        self.changed.emit()
