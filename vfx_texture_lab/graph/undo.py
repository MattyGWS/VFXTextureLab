from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtGui import QUndoCommand


class GraphSnapshotCommand(QUndoCommand):
    """Undo command backed by complete graph snapshots.

    Texture graphs are small compared with the images they produce, so storing the
    lightweight JSON-compatible graph model gives us dependable undo coverage for
    compound edits such as grouping, paste, connection replacement and collapse.
    """

    MERGE_ID = 0x56584658  # "VXFX"

    def __init__(
        self,
        scene,
        before: dict[str, Any],
        after: dict[str, Any],
        text: str,
        *,
        merge_key: str | None = None,
        already_applied: bool = True,
    ) -> None:
        super().__init__(text)
        self.scene = scene
        self.before = deepcopy(before)
        self.after = deepcopy(after)
        self.merge_key = merge_key
        self._skip_first_redo = already_applied

    def id(self) -> int:
        return self.MERGE_ID if self.merge_key else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, GraphSnapshotCommand):
            return False
        if self.scene is not other.scene or not self.merge_key:
            return False
        if self.merge_key != other.merge_key:
            return False
        self.after = deepcopy(other.after)
        self.setText(other.text())
        return True

    def undo(self) -> None:
        self.scene.restore_snapshot(self.before)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.scene.restore_snapshot(self.after)
