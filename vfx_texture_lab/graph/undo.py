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


class NodeParameterCommand(QUndoCommand):
    """Small undo command for one node parameter.

    Manual-action results can contain multi-megabyte compressed meshes. Taking
    two complete graph snapshots for every slider tick copied and compared those
    payloads on the UI thread. This command stores only the authored value while
    leaving the persistent result in place.
    """

    MERGE_ID = 0x56584659  # "VXFY"

    def __init__(
        self,
        scene,
        node_uid: str,
        parameter_name: str,
        before: Any,
        after: Any,
        text: str,
        *,
        merge_key: str | None = None,
        already_applied: bool = False,
    ) -> None:
        super().__init__(text)
        self.scene = scene
        self.node_uid = str(node_uid)
        self.parameter_name = str(parameter_name)
        self.before = deepcopy(before)
        self.after = deepcopy(after)
        self.merge_key = merge_key
        self._skip_first_redo = bool(already_applied)

    def id(self) -> int:
        return self.MERGE_ID if self.merge_key else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, NodeParameterCommand):
            return False
        if self.scene is not other.scene or not self.merge_key:
            return False
        if (
            self.merge_key != other.merge_key
            or self.node_uid != other.node_uid
            or self.parameter_name != other.parameter_name
        ):
            return False
        self.after = deepcopy(other.after)
        self.setText(other.text())
        return True

    def undo(self) -> None:
        self.scene.apply_lightweight_node_parameter(
            self.node_uid, self.parameter_name, deepcopy(self.before)
        )

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.scene.apply_lightweight_node_parameter(
            self.node_uid, self.parameter_name, deepcopy(self.after)
        )
