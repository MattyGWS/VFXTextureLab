from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QDialog

from vfx_texture_lab.graph import GraphScene
from vfx_texture_lab.graph.view import GraphView
from vfx_texture_lab.nodes import build_registry
from vfx_texture_lab.ui.library import NodeLibrary
from vfx_texture_lab.ui.node_preferences import NodePreferences
from vfx_texture_lab.ui.search import NodeSearchDialog


def first_result(dialog: NodeSearchDialog):
    for row in range(dialog.list_widget.count()):
        item = dialog.list_widget.item(row)
        if item.data(Qt.ItemDataRole.UserRole):
            return item
    raise AssertionError("node search returned no selectable result")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    registry = build_registry()
    preferences = NodePreferences()

    # The transient graph search accepts a node on one mouse click.
    dialog = NodeSearchDialog(registry, preferences)
    dialog.show()
    dialog.search.setText("brightness")
    app.processEvents()
    item = first_result(dialog)
    item_rect = dialog.list_widget.visualItemRect(item)
    QTest.mouseClick(
        dialog.list_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        item_rect.center(),
    )
    app.processEvents()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_type_id == item.data(Qt.ItemDataRole.UserRole)

    # Once arrow-key navigation moves focus into the result list, Return must
    # accept the newly highlighted result rather than becoming a dead key.
    keyboard_dialog = NodeSearchDialog(registry, preferences)
    keyboard_dialog.show()
    keyboard_dialog.search.setText("noise")
    app.processEvents()
    keyboard_dialog.list_widget.setFocus()
    starting_row = keyboard_dialog.list_widget.currentRow()
    QTest.keyClick(keyboard_dialog.list_widget, Qt.Key.Key_Down)
    app.processEvents()
    assert keyboard_dialog.list_widget.currentRow() != starting_row
    selected_item = keyboard_dialog.list_widget.currentItem()
    selected_type_id = selected_item.data(Qt.ItemDataRole.UserRole)
    QTest.keyClick(keyboard_dialog.list_widget, Qt.Key.Key_Return)
    app.processEvents()
    assert keyboard_dialog.result() == QDialog.DialogCode.Accepted
    assert keyboard_dialog.selected_type_id == selected_type_id


    # With the search field focused, the top result remains the Enter default,
    # but the first Down press must advance to the second selectable result.
    first_down_dialog = NodeSearchDialog(registry, preferences)
    first_down_dialog.show()
    first_down_dialog.search.setText("noise")
    first_down_dialog.search.setFocus()
    app.processEvents()
    top_row = first_down_dialog.list_widget.currentRow()
    QTest.keyClick(first_down_dialog.search, Qt.Key.Key_Down)
    app.processEvents()
    assert first_down_dialog.list_widget.currentRow() != top_row
    selected_item = first_down_dialog.list_widget.currentItem()
    selected_type_id = selected_item.data(Qt.ItemDataRole.UserRole)
    QTest.keyClick(first_down_dialog.list_widget, Qt.Key.Key_Return)
    app.processEvents()
    assert first_down_dialog.result() == QDialog.DialogCode.Accepted
    assert first_down_dialog.selected_type_id == selected_type_id


    # Loose-wire search is visibly contextual and must not show an empty
    # BUILT-IN NODES section when textual matches are all incompatible.
    compatibility_scene = GraphScene(registry)
    blur_node = compatibility_scene.create_node("filter.blur", QPointF(0, 0))
    blur_output = blur_node.output_ports[blur_node.definition.output_names[0]]
    compatible_dialog = NodeSearchDialog(
        registry,
        preferences,
        definition_filter=lambda definition: compatibility_scene.definition_accepts_loose_port(
            definition, blur_output
        ),
        context_title="Connect from Gaussian Blur",
        context_hint="Greyscale output Image · only compatible nodes are shown.",
        no_results_text='No compatible nodes match “{query}”.\nPress Esc, then Space to search all nodes.',
    )
    compatible_dialog.search.setText("clouds")
    app.processEvents()
    visible_rows = [
        compatible_dialog.list_widget.item(row).text()
        for row in range(compatible_dialog.list_widget.count())
    ]
    assert compatible_dialog.context_title_label.text() == "Connect from Gaussian Blur"
    assert "BUILT-IN NODES" not in visible_rows
    assert any("No compatible nodes match" in text for text in visible_rows)
    assert not any(
        compatible_dialog.list_widget.item(row).flags() & Qt.ItemFlag.ItemIsSelectable
        for row in range(compatible_dialog.list_widget.count())
    )

    compatible_dialog.search.setText("levels")
    app.processEvents()
    assert any(
        compatible_dialog.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == "filter.levels"
        for row in range(compatible_dialog.list_widget.count())
    )

    # A tiny accidental socket movement should neither begin a wire nor open
    # compatible search; a deliberate loose-wire drag still does both.
    threshold_view = GraphView(compatibility_scene, preferences)
    threshold_view._pending_port_press_pos = QPoint(100, 100)
    assert not threshold_view._should_begin_port_drag(QPoint(108, 105))
    assert threshold_view._should_begin_port_drag(QPoint(116, 100))
    assert not threshold_view._should_open_loose_connection_search(QPoint(130, 100))
    assert threshold_view._should_open_loose_connection_search(QPoint(150, 100))

    # Space opens graph search at the mouse cursor while the canvas has focus.
    scene = GraphScene(registry)
    view = GraphView(scene, preferences)
    view.resize(640, 420)
    view.show()
    view.setFocus()
    app.processEvents()
    cursor_pos = view.viewport().rect().center()
    QCursor.setPos(view.viewport().mapToGlobal(cursor_pos))
    calls: list[tuple[QPointF, object]] = []
    view._show_add_search = lambda scene_pos, global_pos: calls.append((scene_pos, global_pos))  # type: ignore[method-assign]
    QTest.keyClick(view, Qt.Key.Key_Space)
    app.processEvents()
    assert len(calls) == 1
    assert (calls[0][0] - view.mapToScene(cursor_pos)).manhattanLength() < 1.0

    # The permanent Node Library deliberately keeps its existing double-click
    # activation model; a single click only selects an entry there.
    library = NodeLibrary(registry, preferences)
    library.resize(360, 480)
    library.show()
    library.search.setText("brightness")
    app.processEvents()
    category = library.tree.topLevelItem(0)
    library_item = category.child(0)
    activation_spy = QSignalSpy(library.nodeActivated)
    library_rect = library.tree.visualItemRect(library_item)
    QTest.mouseClick(
        library.tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        library_rect.center(),
    )
    app.processEvents()
    assert activation_spy.count() == 0
    QTest.mouseDClick(
        library.tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        library_rect.center(),
    )
    app.processEvents()
    assert activation_spy.count() == 1

    print(
        "node search test passed: popup single-click activation, correct first-Down navigation, "
        "contextual compatibility filtering and empty-state guidance, guarded loose-wire activation, "
        "Space-at-cursor graph search, keyboard Return, and Node Library double-click preservation"
    )


if __name__ == "__main__":
    main()
