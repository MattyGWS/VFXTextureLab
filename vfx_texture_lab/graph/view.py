from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRectF, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QGraphicsPathItem, QGraphicsView, QMenu, QMessageBox

from ..theme import theme_colour
from ..ui.node_preferences import NodePreferences
from ..ui.search import NodeSearchDialog
from .items import ConnectionItem, GroupFrameItem, NodeItem, PortItem, RerouteItem
from .mime import GRAPH_ASSET_MIME_TYPE, NODE_MIME_TYPE, OPEN_GRAPH_MIME_TYPE, SELECTION_MIME_TYPE, USER_NODE_MIME_TYPE
from .scene import GraphScene


class GraphView(QGraphicsView):
    simulationResetRequested = Signal(str)
    exportOutputsRequested = Signal(object)
    graphAssetOpenRequested = Signal(str)
    openGraphInstanceRequested = Signal(str, object)
    viewportChanged = Signal()
    backgroundClicked = Signal()
    inspectorItemClicked = Signal(object)
    IMAGE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
    AUTO_PAN_MARGIN = 42
    AUTO_PAN_MAX_STEP = 28
    PORT_SNAP_RADIUS_PX = 32.0
    PORT_SNAP_AMBIGUITY_PX = 5.0
    PORT_DRAG_START_MIN_PX = 14.0
    LOOSE_CONNECTION_SEARCH_MIN_DISTANCE_PX = 48.0
    NODE_GRID_SIZE = 24.0

    def __init__(self, scene: GraphScene, preferences: NodePreferences, parent=None) -> None:
        super().__init__(scene, parent)
        self.graph_scene = scene
        self.preferences = preferences
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setBackgroundBrush(QColor(theme_colour("graph_background", "#15171b")))
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

        self._connection_start_port: PortItem | None = None
        self._pending_port_press: PortItem | None = None
        self._pending_port_press_pos = QPoint()
        self._temporary_connection: QGraphicsPathItem | None = None
        self._invalid_hover_port: PortItem | None = None
        self._snap_hover_port: PortItem | None = None
        self._connection_cursor_view_pos = QPoint()
        self._auto_pan_timer = QTimer(self)
        self._auto_pan_timer.setInterval(16)
        self._auto_pan_timer.timeout.connect(self._auto_pan_tick)

        self._panning = False
        self._pan_start = QPoint()
        self._last_mouse_scene_pos = QPointF()
        self._moving_items = False
        self._movement_nodes: list[NodeItem] = []
        self._movement_anchor_node: NodeItem | None = None
        self._moving_insert_candidate: ConnectionItem | None = None
        self._drag_insert_candidate: ConnectionItem | None = None
        self._open_graph_drop_validator = None

        self._wire_cut_key_down = False
        self._cutting_wires = False
        self._wire_cut_path = QPainterPath()
        self._wire_cut_item: QGraphicsPathItem | None = None
        self._wire_cut_candidates: list[ConnectionItem] = []

        self._scene_margin = 1800.0
        self._scene_bounds_callback = lambda: QTimer.singleShot(0, self._refresh_scene_bounds)
        self.graph_scene.graphChanged.connect(self._scene_bounds_callback)
        self.horizontalScrollBar().valueChanged.connect(lambda _value: self.viewportChanged.emit())
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.viewportChanged.emit())
        QTimer.singleShot(0, self._refresh_scene_bounds)

    def set_graph_scene(self, scene: GraphScene) -> None:
        if scene is self.graph_scene:
            return
        try:
            self.graph_scene.graphChanged.disconnect(self._scene_bounds_callback)
        except (TypeError, RuntimeError):
            pass
        self._end_temporary_connection()
        self._pending_port_press = None
        self.graph_scene = scene
        self.setScene(scene)
        self.graph_scene.graphChanged.connect(self._scene_bounds_callback)
        QTimer.singleShot(0, self._refresh_scene_bounds)

    def set_open_graph_drop_validator(self, validator) -> None:
        """Install a lightweight callback used to reject recursive Explorer drops.

        The callback receives an open graph session UID and returns either a bool
        or ``(allowed, reason)``. Keeping it on the view avoids coupling the graph
        scene to MainWindow's multi-document session manager.
        """
        self._open_graph_drop_validator = validator

    def _open_graph_drop_allowed(self, session_uid: str) -> tuple[bool, str]:
        validator = self._open_graph_drop_validator
        if validator is None:
            return True, ""
        try:
            result = validator(str(session_uid))
        except Exception as exc:
            return False, str(exc)
        if isinstance(result, tuple):
            allowed = bool(result[0]) if result else False
            reason = str(result[1]) if len(result) > 1 else ""
            return allowed, reason
        return bool(result), ""

    def refresh_theme(self) -> None:
        self.setBackgroundBrush(QColor(theme_colour("graph_background", "#15171b")))
        self.viewport().update()
        self.graph_scene.update()

    # ------------------------------------------------------------------
    # Scene bounds and navigation
    # ------------------------------------------------------------------
    def _soft_bounds(self) -> QRectF:
        content = self.graph_scene.content_bounds()
        viewport_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        margin_x = max(self._scene_margin, viewport_scene.width() * 1.5)
        margin_y = max(self._scene_margin, viewport_scene.height() * 1.5)
        return content.adjusted(-margin_x, -margin_y, margin_x, margin_y)

    def _refresh_scene_bounds(self) -> None:
        bounds = self._soft_bounds()
        self.graph_scene.setSceneRect(bounds)
        self._clamp_view_center(bounds)

    def _clamp_view_center(self, bounds: QRectF | None = None) -> None:
        bounds = bounds or self._soft_bounds()
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        centre = visible.center()
        half_w = visible.width() * 0.5
        half_h = visible.height() * 0.5
        minimum_x = bounds.left() + half_w
        maximum_x = bounds.right() - half_w
        minimum_y = bounds.top() + half_h
        maximum_y = bounds.bottom() - half_h
        if minimum_x > maximum_x:
            minimum_x = maximum_x = bounds.center().x()
        if minimum_y > maximum_y:
            minimum_y = maximum_y = bounds.center().y()
        clamped = QPointF(
            min(max(centre.x(), minimum_x), maximum_x),
            min(max(centre.y(), minimum_y), maximum_y),
        )
        if (clamped - centre).manhattanLength() > 0.5:
            self.centerOn(clamped)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scene_bounds()
        self.viewportChanged.emit()

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        current = self.transform().m11()
        next_scale = current * factor
        if 0.18 <= next_scale <= 3.5:
            self.scale(factor, factor)
            self.viewportChanged.emit()
        event.accept()

    # ------------------------------------------------------------------
    # Node creation and search
    # ------------------------------------------------------------------
    def add_node_at_centre(self, type_id: str) -> None:
        centre = self.mapToScene(self.viewport().rect().center())
        self._create_node(type_id, centre)

    def add_user_node_at_centre(self, path: str) -> None:
        centre = self.mapToScene(self.viewport().rect().center())
        self._create_user_node(path, centre)

    def add_graph_asset_at_centre(self, path: str) -> None:
        centre = self.mapToScene(self.viewport().rect().center())
        self._create_graph_asset(path, centre)

    def add_empty_group_at_cursor(self) -> GroupFrameItem:
        group = self.graph_scene.add_empty_group(self._cursor_scene_position())
        self.graph_scene.clearSelection()
        group.setSelected(True)
        return group

    def add_reroute_at_cursor(self) -> RerouteItem | None:
        scene_position = self._cursor_scene_position()
        selected = [item for item in self.graph_scene.selectedItems() if isinstance(item, ConnectionItem)]
        connection = selected[0] if len(selected) == 1 else self.graph_scene.connection_near(
            scene_position, 16.0 / max(self.transform().m11(), 0.1)
        )
        if connection is None:
            return None
        return self.graph_scene.insert_reroute_on_connection(connection, scene_position)

    def _create_node(self, type_id: str, scene_position: QPointF) -> NodeItem:
        self.graph_scene.clearSelection()
        node = self.graph_scene.create_node(type_id, scene_position)
        node.setSelected(True)
        self.preferences.add_recent(type_id)
        return node

    def _create_user_node(self, path: str, scene_position: QPointF) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.graph_scene.instantiate_group_asset(data, scene_position)

    def _create_graph_asset(self, path: str, scene_position: QPointF) -> NodeItem | None:
        try:
            self.graph_scene.clearSelection()
            node = self.graph_scene.create_graph_instance(path, scene_position)
            node.setSelected(True)
            self._refresh_scene_bounds()
            return node
        except Exception as exc:
            QMessageBox.warning(self, "Could not add graph asset", str(exc))
            return None

    def _choose_graph_asset(self, scene_position: QPointF) -> None:
        filename, _selected = QFileDialog.getOpenFileName(
            self, "Add Graph Asset", str(Path.home()), "VFX Texture Lab Graph (*.vfxgraph)"
        )
        if filename:
            self._create_graph_asset(filename, scene_position)

    def _show_add_search(self, scene_position: QPointF, global_position: QPoint) -> None:
        dialog = NodeSearchDialog(self.graph_scene.registry, self.preferences, self)
        dialog.move(global_position)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_type_id:
            self._create_node(dialog.selected_type_id, scene_position)
        elif dialog.selected_asset_path:
            self._create_graph_asset(dialog.selected_asset_path, scene_position)
        elif dialog.browse_graph_asset:
            self._choose_graph_asset(scene_position)

    def _show_connection_search(
        self,
        start_port: PortItem,
        scene_position: QPointF,
        global_position: QPoint,
    ) -> None:
        owner = start_port.owner
        definition = getattr(owner, "definition", None)
        owner_name = str(getattr(definition, "name", "") or getattr(owner, "title", "") or "Connection")
        kind_label = self.graph_scene._kind_label(start_port.kind)
        port_label = str(start_port.display_name or start_port.name)
        if start_port.is_output:
            context_title = f"Connect from {owner_name}"
            context_hint = (
                f'{kind_label} output “{port_label}” · only nodes with a compatible input are shown. '
                "Press Esc, then Space to search all nodes."
            )
            no_results_text = (
                'No compatible nodes match “{query}”.\n'
                f"This popup only shows nodes that can accept the {kind_label} connection. "
                "Press Esc, then Space to search all nodes."
            )
        else:
            context_title = f"Connect to {owner_name}"
            context_hint = (
                f'{kind_label} input “{port_label}” · only nodes with a compatible output are shown. '
                "Press Esc, then Space to search all nodes."
            )
            no_results_text = (
                'No compatible nodes match “{query}”.\n'
                f"This popup only shows nodes that can provide a {kind_label} connection. "
                "Press Esc, then Space to search all nodes."
            )
        dialog = NodeSearchDialog(
            self.graph_scene.registry,
            self.preferences,
            self,
            definition_filter=lambda definition: self.graph_scene.definition_accepts_loose_port(
                definition, start_port
            ),
            title="Connect Node",
            placeholder="Search compatible nodes…",
            context_title=context_title,
            context_hint=context_hint,
            no_results_text=no_results_text,
        )
        dialog.move(global_position)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_type_id:
            return
        node = self.graph_scene.create_node_connected(
            dialog.selected_type_id, scene_position, start_port
        )
        if node is not None:
            self.preferences.add_recent(dialog.selected_type_id)
            self._refresh_scene_bounds()

    def _resolved_authored_path(self, path_text: str) -> Path | None:
        text = str(path_text or "").strip()
        if not text:
            return None
        try:
            path = Path(text).expanduser()
            if not path.is_absolute():
                window = self.window()
                owner = getattr(window, "current_path", None)
                if owner is None:
                    return None
                path = Path(owner).parent / path
            return path.resolve()
        except Exception:
            return None

    def contextMenuEvent(self, event) -> None:
        scene_position = self.mapToScene(event.pos())
        item = self.itemAt(event.pos())
        if isinstance(item, ConnectionItem):
            menu = QMenu(self)
            add_reroute = menu.addAction("Add Reroute")
            delete_wire = menu.addAction("Delete Wire")
            chosen = menu.exec(event.globalPos())
            if chosen is add_reroute:
                self.graph_scene.insert_reroute_on_connection(item, scene_position)
            elif chosen is delete_wire:
                self.graph_scene.remove_connection(item)
            event.accept()
            return
        node_item = item if isinstance(item, NodeItem) else getattr(item, "owner", None)
        if isinstance(node_item, NodeItem) and node_item.supports_thumbnail() and not node_item.is_docked:
            local = node_item.mapFromScene(scene_position)
            if node_item.thumbnail_button_rect().contains(local):
                menu = QMenu(self)
                toggle = menu.addAction("Hide Thumbnail" if node_item.thumbnail_enabled else "Show Thumbnail")
                output_actions = {}
                outputs = node_item.thumbnail_output_names()
                if len(outputs) > 1:
                    output_menu = menu.addMenu("Thumbnail Output")
                    current = node_item.resolved_thumbnail_output()
                    for output_name in outputs:
                        port = node_item.output_ports.get(output_name)
                        label = port.display_name if port is not None else output_name
                        action = output_menu.addAction(label)
                        action.setCheckable(True)
                        action.setChecked(output_name == current)
                        output_actions[action] = output_name
                chosen = menu.exec(event.globalPos())
                if chosen is toggle:
                    self.graph_scene.toggle_node_thumbnail(node_item)
                elif chosen in output_actions:
                    self.graph_scene.set_node_thumbnail_output(node_item, output_actions[chosen])
                    if not node_item.thumbnail_enabled:
                        self.graph_scene.toggle_node_thumbnail(node_item)
                event.accept()
                return
        if isinstance(node_item, NodeItem) and node_item.definition.type_id == "input.image":
            menu = QMenu(self)
            source_text = str(node_item.parameters.get("path", "") or "").strip()
            resolved_source = self._resolved_authored_path(source_text)
            packaged_source_text = str(
                node_item.parameters.get("_packaged_source_path", "") or ""
            ).strip()
            resolved_packaged_source = self._resolved_authored_path(packaged_source_text)
            embedded_data = str(node_item.parameters.get("_embedded_data", "") or "").strip()
            status = "Embedded copy available" if embedded_data else ("External source" if source_text else "Missing source")
            menu.addSection(status)
            use_packaged_source = menu.addAction("Use Included Package Source")
            use_packaged_source.setEnabled(
                bool(
                    resolved_packaged_source is not None
                    and resolved_packaged_source.is_file()
                )
            )
            relink = menu.addAction("Relink Image…")
            matching_count = len(self.graph_scene.matching_image_inputs(node_item))
            relink_all = menu.addAction(f"Relink All Matching Images… ({matching_count})")
            relink_all.setEnabled(matching_count > 1)
            make_local = menu.addAction("Make Local / Embed Image")
            make_local.setEnabled(bool(embedded_data or (resolved_source is not None and resolved_source.is_file())))
            restore = menu.addAction("Restore Embedded Copy As…")
            restore.setEnabled(bool(embedded_data))
            menu.addSeparator()
            reveal = menu.addAction("Reveal Image in File Manager")
            reveal.setEnabled(bool(resolved_source is not None and resolved_source.exists()))
            chosen = menu.exec(event.globalPos())
            try:
                if chosen is use_packaged_source and resolved_packaged_source is not None:
                    self.graph_scene.relink_image_inputs(
                        node_item, resolved_packaged_source, matching=False
                    )
                elif chosen in (relink, relink_all):
                    filename, _selected = QFileDialog.getOpenFileName(
                        self, "Relink Image", source_text or str(Path.home()),
                        "Images (*.png *.tga *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)",
                    )
                    if filename:
                        count = self.graph_scene.relink_image_inputs(
                            node_item, filename, matching=chosen is relink_all
                        )
                        if count > 1:
                            QMessageBox.information(self, "Images relinked", f"Relinked {count} matching Image Input nodes.")
                elif chosen is make_local:
                    if not self.graph_scene.embed_image_input(node_item, source_path=resolved_source):
                        raise ValueError("The image source and embedded recovery copy are both unavailable.")
                elif chosen is restore:
                    suggested = str(node_item.parameters.get("_embedded_name", "") or "restored-image.png")
                    filename, _selected = QFileDialog.getSaveFileName(
                        self, "Restore Embedded Image", str(Path.home() / suggested),
                        "Images (*.png *.tga *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)",
                    )
                    if filename:
                        self.graph_scene.restore_embedded_image(node_item, filename, relink=True)
                elif chosen is reveal and resolved_source is not None:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved_source.parent)))
            except Exception as exc:
                QMessageBox.warning(self, "Image recovery failed", str(exc))
            event.accept()
            return

        if isinstance(node_item, NodeItem) and node_item.definition.type_id == "graph.instance":
            menu = QMenu(self)
            mode = str(node_item.parameters.get("_asset_mode", "Linked"))
            source_text = str(node_item.parameters.get("_asset_path", "")).strip()
            resolved_source = self._resolved_authored_path(source_text)
            session_uid = str(node_item.parameters.get("_asset_session_uid", "")).strip()
            embedded_graph = node_item.parameters.get("_asset_embedded_graph")
            cached_graph = node_item.parameters.get("_asset_cached_graph")
            editable_graph = embedded_graph if isinstance(embedded_graph, dict) else cached_graph
            status = str(node_item.parameters.get("_asset_status", mode) or mode)
            menu.addSection(status)
            open_source = menu.addAction(
                "Open Embedded Graph" if not (source_text or session_uid) else "Open Source Graph"
            )
            open_source.setEnabled(bool(source_text or session_uid or isinstance(editable_graph, dict)))
            reload_source = menu.addAction("Reload from Disk")
            reload_source.setEnabled(mode == "Linked" and bool(source_text))
            embed = menu.addAction(
                "Use Cached Revision / Make Local" if isinstance(cached_graph, dict) else "Make Local / Embed"
            )
            embed.setEnabled(mode != "Embedded" and isinstance(cached_graph, dict))
            restore_cached = menu.addAction("Restore Cached Revision As…")
            restore_cached.setEnabled(isinstance(cached_graph, dict))
            menu.addSeparator()
            relink = menu.addAction("Relink…")
            matching_count = len(self.graph_scene.matching_graph_instances(node_item))
            relink_all = menu.addAction(f"Relink All Matching Instances… ({matching_count})")
            relink_all.setEnabled(matching_count > 1)
            reveal = menu.addAction("Reveal Source in File Manager")
            reveal.setEnabled(bool(resolved_source is not None and resolved_source.exists()))
            chosen = menu.exec(event.globalPos())
            try:
                if chosen is open_source:
                    if session_uid:
                        self.graphAssetOpenRequested.emit(f"session:{session_uid}")
                    elif resolved_source is not None and resolved_source.is_file():
                        self.graphAssetOpenRequested.emit(str(resolved_source))
                    elif isinstance(editable_graph, dict):
                        self.graphAssetOpenRequested.emit(f"embedded:{node_item.uid}")
                elif chosen is reload_source:
                    self.graph_scene.reload_graph_instance(
                        node_item, path=resolved_source or source_text
                    )
                elif chosen is embed:
                    if not self.graph_scene.embed_graph_instance(node_item):
                        raise ValueError("No cached graph revision is available to embed.")
                elif chosen is restore_cached:
                    interface = node_item.parameters.get("_asset_interface", {})
                    name = str(interface.get("name", "Recovered Graph") if isinstance(interface, dict) else "Recovered Graph")
                    filename, _selected = QFileDialog.getSaveFileName(
                        self, "Restore Cached Graph Revision", str(Path.home() / f"{name}.vfxgraph"),
                        "VFX Texture Lab Graph (*.vfxgraph)",
                    )
                    if filename:
                        self.graph_scene.restore_cached_graph_instance(
                            node_item, filename, relink=True,
                            owner_graph_path=getattr(self.window(), "current_path", None),
                        )
                elif chosen in (relink, relink_all):
                    filename, _selected = QFileDialog.getOpenFileName(
                        self, "Relink Graph Asset", source_text or str(Path.home()),
                        "VFX Texture Lab Graph (*.vfxgraph)"
                    )
                    if filename:
                        count = (
                            self.graph_scene.relink_matching_graph_instances(node_item, filename)
                            if chosen is relink_all
                            else int(self.graph_scene.relink_graph_instance(node_item, filename))
                        )
                        if count > 1:
                            QMessageBox.information(self, "Graph assets relinked", f"Relinked {count} matching Graph Instance nodes.")
                elif chosen is reveal and resolved_source is not None:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved_source.parent)))
            except Exception as exc:
                QMessageBox.warning(self, "Graph asset operation failed", str(exc))
            event.accept()
            return
        if isinstance(node_item, NodeItem) and node_item.definition.type_id in {"output.image", "output.texture_set"}:
            menu = QMenu(self)
            export_this = menu.addAction("Export This Output…")
            selected_outputs = [
                node.uid for node in self.graph_scene.selected_nodes()
                if node.definition.type_id in {"output.image", "output.texture_set"}
            ]
            export_selected = None
            if len(selected_outputs) > 1:
                export_selected = menu.addAction(f"Export Selected Outputs… ({len(selected_outputs)})")
            chosen = menu.exec(event.globalPos())
            if chosen is export_this:
                self.exportOutputsRequested.emit([node_item.uid])
            elif export_selected is not None and chosen is export_selected:
                self.exportOutputsRequested.emit(selected_outputs)
            event.accept()
            return
        if isinstance(node_item, NodeItem) and node_item.definition.is_stateful:
            menu = QMenu(self)
            reset_simulation = menu.addAction("Reset Simulation")
            chosen = menu.exec(event.globalPos())
            if chosen is reset_simulation:
                self.simulationResetRequested.emit(node_item.uid)
            event.accept()
            return
        self._show_add_search(scene_position, event.globalPos())
        event.accept()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------
    def _port_drag_distance_px(self, viewport_pos: QPoint) -> float:
        delta = viewport_pos - self._pending_port_press_pos
        return (float(delta.x()) ** 2 + float(delta.y()) ** 2) ** 0.5

    def _should_begin_port_drag(self, viewport_pos: QPoint) -> bool:
        threshold = max(float(QApplication.startDragDistance()), self.PORT_DRAG_START_MIN_PX)
        return self._port_drag_distance_px(viewport_pos) >= threshold

    def _should_open_loose_connection_search(self, viewport_pos: QPoint) -> bool:
        return self._port_drag_distance_px(viewport_pos) >= self.LOOSE_CONNECTION_SEARCH_MIN_DISTANCE_PX

    def mousePressEvent(self, event) -> None:
        viewport_pos = event.position().toPoint()
        self._last_mouse_scene_pos = self.mapToScene(viewport_pos)
        self._connection_cursor_view_pos = viewport_pos

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._wire_cut_key_down
            and not isinstance(self.itemAt(viewport_pos), PortItem)
        ):
            self._begin_wire_cut(self._last_mouse_scene_pos)
            event.accept()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = viewport_pos
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        item = self.itemAt(viewport_pos)
        background_click = event.button() == Qt.MouseButton.LeftButton and item is None
        if event.button() == Qt.MouseButton.LeftButton and isinstance(item, PortItem):
            # A socket press remains a click until the pointer crosses Qt's
            # normal drag threshold. This keeps double-click-to-preview distinct
            # from connection dragging and avoids opening loose-wire search on a
            # simple click.
            self._pending_port_press = item
            self._pending_port_press_pos = QPoint(viewport_pos)
            event.accept()
            return

        # Let compact on-node header controls consume the click without opening
        # a movement transaction around them.
        if isinstance(item, NodeItem) and not isinstance(item, RerouteItem):
            local = item.mapFromScene(self._last_mouse_scene_pos)
            on_thumbnail = (
                not item.is_docked and item.supports_thumbnail()
                and item.thumbnail_button_rect().contains(local)
            )
            on_bypass = (
                not item.is_docked and item._is_bypassable()
                and item.bypass_button_rect().contains(local)
            )
            if on_thumbnail or on_bypass:
                super().mousePressEvent(event)
                return

        if event.button() == Qt.MouseButton.LeftButton and isinstance(item, (NodeItem, GroupFrameItem)):
            resizing = isinstance(item, GroupFrameItem) and item._in_resize_handle(
                item.mapFromScene(self._last_mouse_scene_pos)
            )
            if not resizing:
                if isinstance(item, GroupFrameItem):
                    for node in self.graph_scene.selected_nodes():
                        if node.uid in item.members:
                            node.setSelected(False)
                elif item.group_uid:
                    owner_group = self.graph_scene.groups.get(item.group_uid)
                    if owner_group is not None and owner_group.isSelected():
                        owner_group.setSelected(False)
                self._moving_items = True
                self._movement_nodes = self.graph_scene.selected_nodes()
                if isinstance(item, NodeItem) and item not in self._movement_nodes:
                    self._movement_nodes = [item]
                self._movement_anchor_node = item if isinstance(item, NodeItem) else None
                self.graph_scene.begin_user_action("Move Selection")
        super().mousePressEvent(event)
        if background_click:
            self.backgroundClicked.emit()
        elif event.button() == Qt.MouseButton.LeftButton and isinstance(item, (NodeItem, GroupFrameItem)):
            selected = [
                candidate for candidate in self.graph_scene.selectedItems()
                if isinstance(candidate, (NodeItem, GroupFrameItem))
            ]
            if len(selected) == 1:
                self.inspectorItemClicked.emit(selected[0])

    def mouseDoubleClickEvent(self, event) -> None:
        viewport_pos = event.position().toPoint()
        item = self.itemAt(viewport_pos)
        if event.button() == Qt.MouseButton.LeftButton and isinstance(item, PortItem) and item.is_output:
            self._pending_port_press = None
            if self._connection_start_port is not None:
                self._end_temporary_connection()
            owner = item.owner
            if isinstance(owner, NodeItem):
                self.graph_scene.set_active_output(owner, item.name, force=True)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        viewport_pos = event.position().toPoint()
        self._connection_cursor_view_pos = viewport_pos
        self._last_mouse_scene_pos = self.mapToScene(viewport_pos)
        if self._panning:
            current = viewport_pos
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._clamp_view_center()
            event.accept()
            return
        if self._cutting_wires:
            self._extend_wire_cut(self._last_mouse_scene_pos)
            event.accept()
            return
        if self._pending_port_press is not None and self._connection_start_port is None:
            if self._should_begin_port_drag(viewport_pos):
                item = self._pending_port_press
                self._pending_port_press = None
                self._connection_start_port = item
                self._temporary_connection = QGraphicsPathItem()
                self._temporary_connection.setZValue(-1)
                self._temporary_connection.setPen(self._connection_pen(item.kind, invalid=False))
                self.graph_scene.addItem(self._temporary_connection)
                self._update_temporary_connection(self._last_mouse_scene_pos)
                self._auto_pan_timer.start()
            event.accept()
            return
        if self._connection_start_port is not None:
            self._update_temporary_connection(self._last_mouse_scene_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self._moving_items:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._snap_moving_nodes_to_grid()
            self._update_moving_insert_candidate()
            self._refresh_scene_bounds()

    def mouseReleaseEvent(self, event) -> None:
        viewport_pos = event.position().toPoint()
        self._last_mouse_scene_pos = self.mapToScene(viewport_pos)
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._cutting_wires:
            self._finish_wire_cut()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pending_port_press is not None:
            self._pending_port_press = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._connection_start_port is not None:
            start_port = self._connection_start_port
            exact_item = self.itemAt(viewport_pos)
            target_port = self._snap_hover_port if self._snap_hover_port is not None else (
                exact_item if isinstance(exact_item, PortItem) else None
            )
            connected = False
            if isinstance(target_port, PortItem):
                connected = self.graph_scene.add_connection(start_port, target_port) is not None
            global_position = self.viewport().mapToGlobal(viewport_pos)
            scene_position = self._last_mouse_scene_pos
            had_port_target = isinstance(target_port, PortItem) or isinstance(exact_item, PortItem)
            open_loose_search = self._should_open_loose_connection_search(viewport_pos)
            self._end_temporary_connection()
            if not connected and not had_port_target and open_loose_search:
                self._show_connection_search(start_port, scene_position, global_position)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._moving_items:
            if (
                self._moving_insert_candidate is not None
                and len(self._movement_nodes) == 1
            ):
                self.graph_scene.insert_existing_node_on_connection(
                    self._movement_nodes[0],
                    self._moving_insert_candidate,
                    record_undo=False,
                )
            self._clear_moving_insert_candidate()
            self.graph_scene.finalize_node_movement(self._movement_nodes)
            self.graph_scene.end_user_action()
            self._moving_items = False
            self._movement_nodes = []
            self._movement_anchor_node = None
            self._refresh_scene_bounds()

    def _snap_moving_nodes_to_grid(self) -> None:
        """Snap the dragged node's top-left corner while preserving selection layout."""
        anchor = self._movement_anchor_node
        if anchor is None or anchor not in self._movement_nodes:
            return
        grid = self.NODE_GRID_SIZE
        current = anchor.pos()
        snapped = QPointF(round(current.x() / grid) * grid, round(current.y() / grid) * grid)
        delta = snapped - current
        if abs(delta.x()) < 0.01 and abs(delta.y()) < 0.01:
            return
        for node in self._movement_nodes:
            node.setPos(node.pos() + delta)

    # ------------------------------------------------------------------
    # Keyboard and clipboard
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and not event.isAutoRepeat():
            self.graph_scene.clearSelection()
            self.backgroundClicked.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            viewport_position = self.viewport().mapFromGlobal(QCursor.pos())
            if self.viewport().rect().contains(viewport_position):
                self._show_add_search(
                    self.mapToScene(viewport_position),
                    self.viewport().mapToGlobal(viewport_position),
                )
                event.accept()
                return
        if event.key() == Qt.Key.Key_X and not event.isAutoRepeat():
            self._wire_cut_key_down = True
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_B and not event.isAutoRepeat():
            nodes = self.graph_scene.selected_nodes()
            if len(nodes) == 1 and self.graph_scene.node_is_bypassable(nodes[0]):
                self.graph_scene.toggle_node_bypass(nodes[0])
                event.accept()
                return
        if event.key() == Qt.Key.Key_D and not event.isAutoRepeat():
            if self.graph_scene.toggle_selected_node_dock():
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selected()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_at_cursor()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.graph_scene.delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F:
            selected = self.graph_scene.selectedItems()
            if selected:
                bounds = selected[0].sceneBoundingRect()
                for item in selected[1:]:
                    bounds = bounds.united(item.sceneBoundingRect())
                self.fitInView(
                    bounds.adjusted(-100, -100, 100, 100),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_X and not event.isAutoRepeat():
            self._wire_cut_key_down = False
            if not self._cutting_wires:
                self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def copy_selected(self) -> bool:
        payload = self.graph_scene.selection_to_dict()
        if payload is None:
            return False
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        mime = QMimeData()
        mime.setData(SELECTION_MIME_TYPE, QByteArray(encoded))
        mime.setText(json.dumps(payload, indent=2))
        QApplication.clipboard().setMimeData(mime)
        return True

    def paste_at_cursor(self) -> list:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if not mime.hasFormat(SELECTION_MIME_TYPE):
            return []
        try:
            payload = json.loads(bytes(mime.data(SELECTION_MIME_TYPE)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return []
        return self.graph_scene.paste_selection(payload, self._cursor_scene_position())

    def _cursor_scene_position(self) -> QPointF:
        viewport_position = self.viewport().mapFromGlobal(QCursor.pos())
        if self.viewport().rect().contains(viewport_position):
            return self.mapToScene(viewport_position)
        if not self._last_mouse_scene_pos.isNull():
            return self._last_mouse_scene_pos
        return self.mapToScene(self.viewport().rect().center())

    # ------------------------------------------------------------------
    # Wire cutting
    # ------------------------------------------------------------------
    def _begin_wire_cut(self, scene_position: QPointF) -> None:
        self._cutting_wires = True
        self._wire_cut_path = QPainterPath(scene_position)
        self._wire_cut_item = QGraphicsPathItem()
        self._wire_cut_item.setZValue(30)
        self._wire_cut_item.setPen(
            QPen(
                QColor("#ff5b6d"),
                2.2,
                Qt.PenStyle.DashLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        self.graph_scene.addItem(self._wire_cut_item)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def _extend_wire_cut(self, scene_position: QPointF) -> None:
        self._wire_cut_path.lineTo(scene_position)
        if self._wire_cut_item is not None:
            self._wire_cut_item.setPath(self._wire_cut_path)
        candidates = self.graph_scene.connections_intersecting_path(
            self._wire_cut_path,
            12.0 / max(self.transform().m11(), 0.1),
        )
        old = set(self._wire_cut_candidates)
        new = set(candidates)
        for connection in old - new:
            connection.set_cut_candidate(False)
        for connection in new - old:
            connection.set_cut_candidate(True)
        self._wire_cut_candidates = candidates

    def _finish_wire_cut(self) -> None:
        candidates = list(self._wire_cut_candidates)
        for connection in candidates:
            connection.set_cut_candidate(False)
        self._wire_cut_candidates = []
        if self._wire_cut_item is not None and self._wire_cut_item.scene() is self.graph_scene:
            self.graph_scene.removeItem(self._wire_cut_item)
        self._wire_cut_item = None
        self._wire_cut_path = QPainterPath()
        self._cutting_wires = False
        if not self._wire_cut_key_down:
            self.viewport().unsetCursor()
        self.graph_scene.cut_connections(candidates)

    # ------------------------------------------------------------------
    # Automatic panning during connection drag
    # ------------------------------------------------------------------
    @staticmethod
    def _edge_step(value: int, minimum: int, maximum: int, margin: int) -> int:
        if value < minimum + margin:
            strength = (minimum + margin - value) / max(margin, 1)
            return -max(2, int(GraphView.AUTO_PAN_MAX_STEP * min(strength, 1.0)))
        if value > maximum - margin:
            strength = (value - (maximum - margin)) / max(margin, 1)
            return max(2, int(GraphView.AUTO_PAN_MAX_STEP * min(strength, 1.0)))
        return 0

    def _auto_pan_tick(self) -> None:
        if self._connection_start_port is None:
            self._auto_pan_timer.stop()
            return
        rect = self.viewport().rect()
        pos = self._connection_cursor_view_pos
        dx = self._edge_step(pos.x(), rect.left(), rect.right(), self.AUTO_PAN_MARGIN)
        dy = self._edge_step(pos.y(), rect.top(), rect.bottom(), self.AUTO_PAN_MARGIN)
        if not dx and not dy:
            return
        if dx:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
        if dy:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)
        self._last_mouse_scene_pos = self.mapToScene(pos)
        self._update_temporary_connection(self._last_mouse_scene_pos)

    # ------------------------------------------------------------------
    # Drag/drop and direct wire insertion
    # ------------------------------------------------------------------
    def _first_dropped_image(self, mime) -> str | None:
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in self.IMAGE_SUFFIXES:
                return str(path)
        return None

    @staticmethod
    def _dropped_open_graph_uid(mime) -> str | None:
        if not mime.hasFormat(OPEN_GRAPH_MIME_TYPE):
            return None
        try:
            value = bytes(mime.data(OPEN_GRAPH_MIME_TYPE)).decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        return value or None

    def _first_dropped_graph(self, mime) -> str | None:
        if mime.hasFormat(GRAPH_ASSET_MIME_TYPE):
            try:
                return bytes(mime.data(GRAPH_ASSET_MIME_TYPE)).decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".vfxgraph":
                return str(Path(url.toLocalFile()))
        return None

    @staticmethod
    def _mime_node_type(mime) -> str | None:
        if not mime.hasFormat(NODE_MIME_TYPE):
            return None
        try:
            return bytes(mime.data(NODE_MIME_TYPE)).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _set_drag_insert_candidate(self, connection: ConnectionItem | None) -> None:
        if connection is self._drag_insert_candidate:
            return
        if self._drag_insert_candidate is not None:
            self._drag_insert_candidate.set_insert_candidate(False)
        self._drag_insert_candidate = connection
        if connection is not None:
            connection.set_insert_candidate(True)

    def _drop_insert_candidate(self, type_id: str, scene_position: QPointF) -> ConnectionItem | None:
        definition = self.graph_scene.registry.get_optional(type_id)
        if definition is None:
            return None
        tolerance = 16.0 / max(self.transform().m11(), 0.1)
        connection = self.graph_scene.connection_near(scene_position, tolerance)
        if connection is None or not self.graph_scene.definition_can_insert_on_connection(
            definition, connection
        ):
            return None
        return connection

    def dragEnterEvent(self, event) -> None:
        open_graph_uid = self._dropped_open_graph_uid(event.mimeData())
        if open_graph_uid:
            allowed, _reason = self._open_graph_drop_allowed(open_graph_uid)
            if not allowed:
                event.ignore()
                return
        if (
            event.mimeData().hasFormat(NODE_MIME_TYPE)
            or event.mimeData().hasFormat(USER_NODE_MIME_TYPE)
            or open_graph_uid
            or self._first_dropped_graph(event.mimeData())
            or self._first_dropped_image(event.mimeData())
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        open_graph_uid = self._dropped_open_graph_uid(mime)
        if open_graph_uid:
            allowed, _reason = self._open_graph_drop_allowed(open_graph_uid)
            if not allowed:
                self._set_drag_insert_candidate(None)
                event.ignore()
                return
        if (
            mime.hasFormat(NODE_MIME_TYPE)
            or mime.hasFormat(USER_NODE_MIME_TYPE)
            or open_graph_uid
            or self._first_dropped_graph(mime)
            or self._first_dropped_image(mime)
        ):
            type_id = self._mime_node_type(mime)
            if type_id and self.graph_scene.registry.contains(type_id):
                scene_position = self.mapToScene(event.position().toPoint())
                self._set_drag_insert_candidate(
                    self._drop_insert_candidate(type_id, scene_position)
                )
            else:
                self._set_drag_insert_candidate(None)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        self._set_drag_insert_candidate(None)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_insert_candidate(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        scene_position = self.mapToScene(event.position().toPoint())
        self._last_mouse_scene_pos = scene_position
        open_graph_uid = self._dropped_open_graph_uid(event.mimeData())
        if open_graph_uid:
            self._set_drag_insert_candidate(None)
            allowed, reason = self._open_graph_drop_allowed(open_graph_uid)
            if not allowed:
                if reason:
                    self.setToolTip(reason)
                    QTimer.singleShot(2500, lambda: self.setToolTip(""))
                event.ignore()
                return
            self.openGraphInstanceRequested.emit(open_graph_uid, scene_position)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        graph_path = self._first_dropped_graph(event.mimeData())
        if graph_path:
            self._set_drag_insert_candidate(None)
            if self._create_graph_asset(graph_path, scene_position) is None:
                event.ignore()
                return
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        image_path = self._first_dropped_image(event.mimeData())
        if image_path:
            self._set_drag_insert_candidate(None)
            self.graph_scene.clearSelection()
            node = self.graph_scene.create_node(
                "input.image", scene_position, parameters={"path": image_path}
            )
            node.setSelected(True)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._refresh_scene_bounds()
            return
        if event.mimeData().hasFormat(USER_NODE_MIME_TYPE):
            self._set_drag_insert_candidate(None)
            try:
                path = bytes(event.mimeData().data(USER_NODE_MIME_TYPE)).decode("utf-8")
            except UnicodeDecodeError:
                event.ignore()
                return
            self._create_user_node(path, scene_position)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        if event.mimeData().hasFormat(NODE_MIME_TYPE):
            try:
                type_id = bytes(event.mimeData().data(NODE_MIME_TYPE)).decode("utf-8")
                self.graph_scene.registry.get(type_id)
            except (UnicodeDecodeError, KeyError):
                self._set_drag_insert_candidate(None)
                event.ignore()
                return
            connection = self._drag_insert_candidate or self._drop_insert_candidate(
                type_id, scene_position
            )
            self._set_drag_insert_candidate(None)
            if connection is not None:
                node = self.graph_scene.insert_node_on_connection(
                    type_id, scene_position, connection
                )
                if node is not None:
                    self.preferences.add_recent(type_id)
            else:
                self._create_node(type_id, scene_position)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._refresh_scene_bounds()
            return
        self._set_drag_insert_candidate(None)
        super().dropEvent(event)

    def _update_moving_insert_candidate(self) -> None:
        candidate: ConnectionItem | None = None
        if len(self._movement_nodes) == 1:
            node = self._movement_nodes[0]
            tolerance = 16.0 / max(self.transform().m11(), 0.1)
            near = self.graph_scene.connection_near(
                node.sceneBoundingRect().center(),
                tolerance,
                exclude_nodes={node.uid},
            )
            if near is not None and self.graph_scene.can_insert_existing_node(node, near):
                candidate = near
        if candidate is self._moving_insert_candidate:
            return
        self._clear_moving_insert_candidate()
        self._moving_insert_candidate = candidate
        if candidate is not None:
            candidate.set_insert_candidate(True)

    def _clear_moving_insert_candidate(self) -> None:
        if self._moving_insert_candidate is not None:
            self._moving_insert_candidate.set_insert_candidate(False)
        self._moving_insert_candidate = None

    # ------------------------------------------------------------------
    # Background and connection preview
    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect) -> None:
        painter.fillRect(rect, QColor(theme_colour("graph_background", "#15171b")))
        minor = 24
        major = minor * 5

        left = int(rect.left()) - (int(rect.left()) % minor)
        top = int(rect.top()) - (int(rect.top()) % minor)
        minor_lines = []
        major_lines = []
        from PySide6.QtCore import QLineF

        x = left
        while x < rect.right():
            target = major_lines if x % major == 0 else minor_lines
            target.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += minor
        y = top
        while y < rect.bottom():
            target = major_lines if y % major == 0 else minor_lines
            target.append(QLineF(rect.left(), y, rect.right(), y))
            y += minor

        painter.setPen(QPen(QColor(theme_colour("grid_minor", "#1c1f24")), 1.0))
        painter.drawLines(minor_lines)
        painter.setPen(QPen(QColor(theme_colour("grid_major", "#24282e")), 1.0))
        painter.drawLines(major_lines)

    @staticmethod
    def _connection_pen(kind: str, *, invalid: bool) -> QPen:
        if invalid:
            return QPen(
                QColor("#ef5565"),
                3.0,
                Qt.PenStyle.DashLine,
                Qt.PenCapStyle.RoundCap,
            )
        colours = {
            "grayscale": "#858b94",
            "color": "#c99a42",
            "vector": "#4384c7",
            "material": "#9d60d6",
            "geometry": "#b9563d",
            "scalar": "#45a96c",
            "vector2": "#3e9f82",
            "vector3": "#388f75",
            "image_any": "#747987",
        }
        return QPen(
            QColor(colours.get(kind, "#747987")),
            3.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )

    def _clear_invalid_hover(self) -> None:
        if self._invalid_hover_port is not None:
            self._invalid_hover_port.set_invalid(False)
            self._invalid_hover_port = None

    def _clear_snap_hover(self) -> None:
        if self._snap_hover_port is not None:
            self._snap_hover_port.set_snap_target(False)
            self._snap_hover_port = None

    def _nearest_compatible_port(self, viewport_pos: QPoint) -> PortItem | None:
        start = self._connection_start_port
        if start is None:
            return None
        candidates: list[tuple[float, PortItem]] = []
        radius_sq = self.PORT_SNAP_RADIUS_PX * self.PORT_SNAP_RADIUS_PX
        for item in self.graph_scene.items():
            if not isinstance(item, PortItem) or item is start or not item.isVisible():
                continue
            if item.is_output == start.is_output:
                continue
            centre = self.mapFromScene(item.centre_scene_pos())
            dx = float(centre.x() - viewport_pos.x())
            dy = float(centre.y() - viewport_pos.y())
            distance_sq = dx * dx + dy * dy
            if distance_sq > radius_sq:
                continue
            valid, _reason = self.graph_scene.can_connect(start, item)
            if valid:
                candidates.append((distance_sq, item))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry[0])
        best_distance_sq, best = candidates[0]
        if len(candidates) > 1:
            second_distance_sq = candidates[1][0]
            best_distance = best_distance_sq ** 0.5
            second_distance = second_distance_sq ** 0.5
            # At the exact midpoint between tightly packed sockets, do not
            # choose arbitrarily. Moving a few pixels toward either socket makes
            # the intended target unambiguous and restores the snap.
            if best_distance > 9.0 and second_distance - best_distance < self.PORT_SNAP_AMBIGUITY_PX:
                return None
        return best

    def _update_temporary_connection(self, end: QPointF) -> None:
        if self._connection_start_port is None or self._temporary_connection is None:
            return
        self._clear_invalid_hover()
        self._clear_snap_hover()
        viewport_pos = self.mapFromScene(end)
        item = self.itemAt(viewport_pos)
        invalid = False
        target: PortItem | None = None
        if isinstance(item, PortItem) and item is not self._connection_start_port:
            valid, reason = self.graph_scene.can_connect(self._connection_start_port, item)
            invalid = not valid
            item.set_invalid(invalid)
            if invalid:
                self._invalid_hover_port = item
                self.viewport().setToolTip(reason)
            else:
                target = item
        elif not isinstance(item, PortItem):
            target = self._nearest_compatible_port(viewport_pos)

        if target is not None:
            self._snap_hover_port = target
            target.set_snap_target(True)
            end = target.centre_scene_pos()
            self.viewport().setToolTip(f"Release to connect to {target.display_name}")
        elif not invalid:
            self.viewport().setToolTip("")

        self._temporary_connection.setPen(
            self._connection_pen(self._connection_start_port.kind, invalid=invalid)
        )
        start = self._connection_start_port.centre_scene_pos()
        distance = max(abs(end.x() - start.x()) * 0.5, 65.0)
        direction = 1.0 if self._connection_start_port.is_output else -1.0
        path = QPainterPath(start)
        path.cubicTo(
            start.x() + distance * direction,
            start.y(),
            end.x() - distance * direction,
            end.y(),
            end.x(),
            end.y(),
        )
        self._temporary_connection.setPath(path)

    def _end_temporary_connection(self) -> None:
        self._auto_pan_timer.stop()
        self._clear_invalid_hover()
        self._clear_snap_hover()
        self.viewport().setToolTip("")
        if (
            self._temporary_connection is not None
            and self._temporary_connection.scene() is self.graph_scene
        ):
            self.graph_scene.removeItem(self._temporary_connection)
        self._temporary_connection = None
        self._connection_start_port = None
