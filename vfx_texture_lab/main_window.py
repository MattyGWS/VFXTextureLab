from __future__ import annotations

import base64
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import json
import re
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np

from PySide6.QtCore import QEvent, QPointF, QSettings, QStandardPaths, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QToolBar,
    QTabWidget,
)

from . import __version__
from .custom_nodes import CustomNodePackageManager
from .document import DocumentSettings, GraphAssetMetadata
from .graph_resources import GraphResourceLibrary, migrate_project_resources
from .engine import AsyncEvaluationController, GraphEvaluator, GraphSnapshot
from .engine.evaluator import _prepare_cpu_preview_rgba8
from .engine.cache import MemoryLRU
from .flipbook import extract_native_flipbook_cell
from .nodes.base import EvalContext, is_image_kind, normalise_port_kind
from .material_graph import MATERIAL_PRODUCER_TYPES
from .geometry import export_obj
from .geometry_graph import GeometryEvaluationSession, material_geometry_reference
from .geometry_evaluation import GeometryEvaluationController
from .graph_asset_thumbnails import encode_thumbnail_image
from .graph_asset_library import default_graph_asset_directory
from .graph_assets import (
    GRAPH_INSTANCE_TYPE, graph_instance_definition, instance_parameters_for_asset,
    parse_graph_asset_interface,
)
from .preview_cache import (
    CachedGeometryMesh, CachedMaterialResult, CachedPreviewResult, CachedThumbnail,
    PresentationCacheTrace,
)
from .portable_graph import (
    SelfContainedGraphError, build_self_contained_graph, recovery_summary,
    validate_self_contained_graph,
)
from .vfx_package import (
    PACKAGE_EXTENSION, VFXPackageError, create_vfxpackage, extract_vfxpackage,
    inspect_vfxpackage, install_vfxpackage as install_package_archive, installed_packages,
    read_package_entry_graph, read_package_thumbnail, read_packaged_export_templates,
    write_packaged_custom_node_archives,
)
from .graph import GraphScene, GraphView
from .graph.items import GroupFrameItem, NodeItem
from .nodes import build_registry
from .ui import (
    CanvasPanel,
    CustomNodeDiagnosticsDialog,
    CustomNodeLibrariesDialog,
    EvaluationInspector,
    ExportTemplateLibraryDialog,
    ExplorerFolderInfo,
    ExplorerGraphInfo,
    ExplorerResourceInfo,
    GraphExplorer,
    NodeLibrary,
    NodePreferences,
    ParametersPanel,
    PreviewPanel,
    VFXPackageDialog,
    VFXPackageExportOptionsDialog,
    TimelinePanel,
)
from .ui.document_settings import DocumentSettingsDialog
from .ui.export_dialog import ExportDialog, ExportOutputChoice, ExportRequest
from .ui.export_template_dialog import ExportTemplateDialog
from .export_templates import CUSTOM_TEMPLATE_NAME, effective_export_template
from .export_template_library import (
    ExportTemplateLibraryError, export_template_directory, install_template_object,
    install_vfxexport, read_vfxexport, write_vfxexport, VFXEXPORT_EXTENSION,
)
from .export_profiles import ExportProfileLibrary, ExportProfileSet
from .exporting import export_image, pack_template_channels
from .export_plan import (
    build_export_artifacts,
    build_multi_target_artifacts,
    disambiguated_export_filenames,
    export_filename_conflicts,
    resolve_destination,
)
from .animation_export import effective_grid, sample_positions_from_node
from .user_nodes import slugify_node_name, user_node_directory
from .three_d import MaterialEvaluationController, MaterialEvaluationResult, MeshData, ThreeDPreviewPanel
from .theme import (
    BUILTIN_THEMES,
    active_theme,
    build_stylesheet,
    load_custom_themes,
    resolve_theme,
    set_active_theme,
    theme_to_json,
)


@dataclass(slots=True)
class GraphDocumentSession:
    uid: str
    scene: GraphScene
    document: DocumentSettings
    current_path: Path | None = None
    document_dirty: bool = False
    recovered_dirty: bool = False
    current_frame: int = 0
    viewport_state: dict | None = None
    view_transform: QTransform | None = None
    view_center: QPointF | None = None
    display_name: str = "Untitled.vfxgraph"
    graph_asset: GraphAssetMetadata = field(default_factory=GraphAssetMetadata)
    export_profiles: ExportProfileLibrary = field(default_factory=ExportProfileLibrary.default)
    graph_resources: GraphResourceLibrary = field(default_factory=GraphResourceLibrary)

    @property
    def dirty(self) -> bool:
        try:
            undo_dirty = not self.scene.undo_stack.isClean()
        except RuntimeError:
            # Qt can emit QUndoStack.cleanChanged while the application is
            # tearing down its QObject tree. The Python session record may
            # briefly outlive the deleted C++ stack during that shutdown.
            undo_dirty = False
        return bool(undo_dirty or self.document_dirty or self.recovered_dirty)

    @property
    def name(self) -> str:
        return self.current_path.name if self.current_path is not None else self.display_name


class MainWindow(QMainWindow):
    WORKSPACE_STATE_VERSION = 2
    WORKSPACE_SETTINGS_GROUP = "workspace/v1"
    MATERIAL_NODE_TYPE = "material.pbr"
    MATERIAL_NODE_TYPES = MATERIAL_PRODUCER_TYPES
    TEXTURE_SET_NODE_TYPE = "output.texture_set"
    IMAGE_OUTPUT_NODE_TYPE = "output.image"
    FLIPBOOK_NODE_TYPE = "output.flipbook"

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings()
        self._graph_asset_windows: list[MainWindow] = []
        self._graph_sessions: OrderedDict[str, GraphDocumentSession] = OrderedDict()
        self._active_graph_session_uid: str | None = None
        self._switching_graph_session = False
        self._propagating_live_graphs = False
        self._live_graph_update_timers: dict[str, QTimer] = {}
        self._untitled_graph_counter = 1
        self._restoring_workspace = True
        self._workspace_save_timer = QTimer(self)
        self._workspace_save_timer.setSingleShot(True)
        # Dock state is saved after the drag has fully settled. Saving a
        # QMainWindow state while Qt is reparenting a floating dock can race its
        # internal dock animation on some Linux/Qt builds.
        self._workspace_save_timer.setInterval(500)
        self._workspace_save_timer.timeout.connect(self._save_workspace_layout)
        self._workspace_docks: tuple[QDockWidget, ...] = ()
        self.document = DocumentSettings()
        self.graph_asset = GraphAssetMetadata(created_with=__version__)
        self.export_profiles = ExportProfileLibrary.default()
        self.graph_resources = GraphResourceLibrary()
        self.package_manager = CustomNodePackageManager(self.settings, self)
        self.registry = build_registry()
        self.preferences = NodePreferences(self)
        self.scene = GraphScene(self.registry, self)
        self.scene.default_tiling = self.document.default_tiling
        self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
        self.scene.canvas_default_size = (self.document.width, self.document.height)
        backend_preference = str(self.settings.value("render/backend", "auto"))
        gpu_budget_mb = int(self.settings.value("render/gpu_budget_mb", 512))
        self.evaluator = GraphEvaluator(
            self.scene,
            backend_preference=backend_preference,
            gpu_budget_mb=gpu_budget_mb,
            cpu_budget_mb=max(gpu_budget_mb // 2, 128),
        )
        self._reload_custom_nodes(initial=True)
        self.eval_controller = AsyncEvaluationController(self.evaluator, self)
        self.geometry_controller = GeometryEvaluationController(self)
        # Optional node thumbnails use a dedicated lowest-priority controller.
        # With no expanded thumbnails this controller never submits work.
        self.thumbnail_controller = AsyncEvaluationController(self.evaluator, self)
        # Playback uses a separate sequential worker so it can prepare exact
        # frames ahead without interfering with ordinary edit-preview scheduling.
        self.playback_controller = AsyncEvaluationController(self.evaluator, self)
        self.graph_view = GraphView(self.scene, self.preferences, self)
        self.preview_panel = PreviewPanel(self)
        self.canvas_panel = CanvasPanel(self.scene, self)
        self.parameters_panel = ParametersPanel(
            self.scene,
            self,
            evaluator=self.evaluator,
            document_provider=lambda: self.document,
            animation_context_provider=self._animation_context,
        )
        self.library_panel = NodeLibrary(self.registry, self.preferences, self)
        self.graph_explorer = GraphExplorer(self)
        self.timeline_panel = TimelinePanel(self)
        self.evaluation_inspector = EvaluationInspector(self)
        self.timeline_panel.set_document(self.document)
        self.timeline_panel.set_playback_mode(str(self.settings.value("timeline/playback_mode", "Real-time")))
        self.timeline_panel.set_profiler_enabled(
            str(self.settings.value("timeline/profiler_enabled", "false")).lower() in {"1", "true", "yes"}
        )
        self.material_controller = MaterialEvaluationController(self.evaluator, self)
        self.preview_3d_panel = ThreeDPreviewPanel(
            self.evaluator.gpu_backend, self, settings=self.settings
        )
        # Node-resource caches avoid recomputing graph operations.  These two
        # presentation caches sit one layer above them so changing focus can
        # also reuse view-ready RGBA8 pixels, resolved material channels and
        # renderer-resident mipmapped texture sets.
        self._preview_result_cache: MemoryLRU[CachedPreviewResult] = MemoryLRU(96 * 1024 * 1024)
        self._thumbnail_cache: MemoryLRU[CachedThumbnail] = MemoryLRU(32 * 1024 * 1024)
        self._material_result_cache: MemoryLRU[CachedMaterialResult] = MemoryLRU(
            max(gpu_budget_mb // 2, 128) * 1024 * 1024
        )
        self._geometry_result_cache: MemoryLRU[CachedGeometryMesh] = MemoryLRU(
            max(gpu_budget_mb // 2, 256) * 1024 * 1024
        )
        self._geometry_preview_in_flight = False
        self._pending_geometry_node_uid: str | None = None
        self._pending_geometry_request: dict | None = None
        self._geometry_node_activity: dict[str, str] = {}
        self._geometry_preview_debounce_ms = 160
        self._material_preview_metadata: OrderedDict[str, MaterialEvaluationResult] = OrderedDict()
        self._material_preview_metadata_limit = 64
        self.preview_3d_panel.set_material_cache_budget_mb(gpu_budget_mb)

        self.current_frame = 0
        self._playing = False
        self._playback_buffer: OrderedDict[int, object] = OrderedDict()
        self._playback_buffer_limit = 4
        self._playback_prefetch_depth = 3
        self._playback_render_in_flight = False
        self._playback_render_frame: int | None = None
        self._playback_waiting_target: int | None = None
        self._playback_snapshot: GraphSnapshot | None = None
        self._playback_node_uid: str | None = None
        self._playback_preview_uid: str | None = None
        self._playback_preview_output: str | None = None
        self._playback_preview_name: str | None = None
        self._playback_source_size = self.document.preview_size()
        self._playback_display_size = (1, 1)
        self._playback_clock_started = 0.0
        self._playback_clock_start_frame = 0
        self._playback_last_clock_step = 0
        self._playback_dropped_frames = 0
        self._playback_presented_frames = 0
        self._playback_present_times: deque[float] = deque(maxlen=180)
        self._playback_last_result = None
        self._playback_static_result = None
        self._playback_static_uploaded = False
        # Imported static atlases use the cheap cached-cell playback path.
        # Decoders fed by Flipbook Generator (or any time-varying sheet) must
        # instead use the ordinary frame-ahead evaluator so each decoded frame
        # is actually prepared and presented during playback.
        self._playback_cached_flipbook_decode = False
        self.current_path: Path | None = None
        self.dirty = False
        self._loading = False
        self._document_dirty = False
        self._recovered_dirty = False
        self._pending_preview_name: str | None = None
        self._pending_preview_size = self.document.preview_size()
        self._pending_display_size = self.preview_panel.recommended_render_size(*self._pending_preview_size)
        self._pending_preview_kind = "frame"
        self._pending_preview_details: str | None = None
        self._pending_preview_cache_key: str | None = None
        self._pending_preview_source_uid: str | None = None
        self._pending_preview_source_output: str | None = None
        self._pending_flipbook_frame_count = 0
        self._preview_in_flight = False
        self._preview_pending = False
        self._preview_last_dispatch = 0.0
        self._preview_interval_ms = 33
        self._interactive_preview_interval_ms = 16
        self._playback_preview_pending = False
        self._material_preview_in_flight = False
        self._material_preview_pending = False
        self._material_preview_last_dispatch = 0.0
        self._material_preview_interval_ms = 66
        self._material_playback_last_presented_frame = -1
        self._material_playback_pending_result = None
        self._material_playback_present_interval_ms = 33
        self._material_playback_last_2d_frame = -1
        self._material_playback_2d_presented_frames = 0
        self._material_playback_last_3d_present = 0.0
        self._material_playback_live_max = 256
        self._material_playback_latency_ema_ms = 0.0
        self._material_playback_fast_frames = 0
        self._material_playback_slow_frames = 0
        self._material_playback_epoch = 0
        self._material_playback_request_serial = 0
        self._pending_material_playback_epoch = 0
        self._pending_material_playback_serial = -1
        self._material_playback_last_2d_serial = -1
        self._material_playback_last_3d_serial = -1
        self._material_playback_focus_uid: str | None = None
        self._material_request_is_playback = False
        # Automatic material refreshes deliberately wait for a short idle gap.
        # Direct 2D editing always owns the evaluator first.
        self._material_preview_idle_delay_ms = 300
        self._pending_material_uid: str | None = None
        self._pending_material_request_key: str | None = None
        self._last_material_result_key: str | None = None
        self._material_node_activity: dict[str, str] = {}
        self._legacy_3d_viewport_nodes: set[str] = set()
        self._interactive_parameter_edit_depth = 0
        self._interactive_parameter_node_uid: str | None = None
        self._preview_gizmo_action_uid: str | None = None
        self._pending_preview_render_mode = "preview"
        self._preview_node_activity: dict[str, str] = {}
        self._thumbnail_in_flight = False
        self._thumbnail_current: tuple[str, str, str, str] | None = None
        self._thumbnail_idle_delay_ms = 550
        self._thumbnail_animation_interval_ms = 200
        self._thumbnail_last_animation_schedule = 0.0
        self._evaluation_job_id = 0
        self._evaluation_job_kind = ""
        self._evaluation_job_started = 0.0
        # Imported flipbook sheets use a dedicated preview path: evaluate the
        # static atlas once, then select cells locally on every playback tick.
        # This avoids full graph evaluation/readback and prevents frame drops.
        self._flipbook_decode_sheet: np.ndarray | None = None
        self._flipbook_decode_node_uid: str | None = None
        self._flipbook_decode_source_uid: str | None = None
        self._flipbook_decode_backend = "Cached atlas"
        self._flipbook_decode_load_ms = 0.0
        self._flipbook_decode_data_kind = "color"
        self._flipbook_decode_precision = "16-bit"
        self._flipbook_decode_snapshot: GraphSnapshot | None = None
        self._pending_decode_node_uid: str | None = None
        self._pending_decode_source_uid: str | None = None
        self._embedded_asset_cache: dict[str, tuple[int, int, str]] = {}
        self._app_data_root = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        )
        self._app_data_root.mkdir(parents=True, exist_ok=True)
        autosave_root = self._app_data_root / "autosave"
        autosave_root.mkdir(parents=True, exist_ok=True)
        self._autosave_path = autosave_root / "recovery.vfxgraph.autosave"
        self._startup_graph_path = self._app_data_root / "startup" / "default.vfxgraph"
        self._theme_directory = self._app_data_root / "themes"
        self._theme_directory.mkdir(parents=True, exist_ok=True)
        self._theme_action_group: QActionGroup | None = None
        self.theme_menu = None

        self.setWindowTitle("VFX Texture Lab")
        self.resize(1520, 920)
        self.setMinimumSize(1050, 650)
        self.setDockNestingEnabled(True)
        # AnimatedDocks uses QPropertyAnimation while widgets are reparented.
        # Qt 6 on some Fedora/Wayland/X11 combinations can crash inside that
        # native reparent path when a floating dock is dragged. Docking remains
        # fully functional without the cosmetic animation.
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.setAnimated(False)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.setDocumentMode(True)
        self.setCentralWidget(self.graph_view)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._restore_workspace_layout()
        self._connect_workspace_signals()
        self._connect_signals()

        # Interactive previews use a leading-edge, latest-value-wins scheduler.
        # The first edit renders immediately; sustained edits are capped to a
        # sensible cadence and never create overlapping or obsolete work.
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.preview_timer.timeout.connect(self._dispatch_pending_preview)

        # Expensive geometry edits are evaluated off the UI thread. A short
        # latest-value debounce prevents slider drags from launching a native
        # simplification for every intermediate percentage.
        self.geometry_preview_timer = QTimer(self)
        self.geometry_preview_timer.setSingleShot(True)
        self.geometry_preview_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.geometry_preview_timer.timeout.connect(self._dispatch_pending_geometry_preview)

        # The material preview is intentionally capped lower than the 2D view
        # so it remains responsive without stealing all resources from direct
        # parameter feedback.
        self.material_preview_timer = QTimer(self)
        self.material_preview_timer.setSingleShot(True)
        self.material_preview_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.material_preview_timer.timeout.connect(self._dispatch_pending_3d_preview)

        # Completed material frames are coalesced and presented at a stable
        # viewport cadence. Evaluation can continue in the worker while the UI
        # waits to present only the newest completed frame.
        self.material_present_timer = QTimer(self)
        self.material_present_timer.setSingleShot(True)
        self.material_present_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.material_present_timer.timeout.connect(self._present_pending_material_playback)

        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self._dispatch_thumbnail_work)

        self.playback_timer = QTimer(self)
        self.playback_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.playback_timer.timeout.connect(self._playback_tick)
        self._update_playback_interval()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(5000)
        self.autosave_timer.timeout.connect(self._write_autosave)
        self.periodic_autosave_timer = QTimer(self)
        self.periodic_autosave_timer.setInterval(60000)
        self.periodic_autosave_timer.timeout.connect(self._write_autosave)
        self.periodic_autosave_timer.start()

        self.graph_asset_watch_timer = QTimer(self)
        self.graph_asset_watch_timer.setInterval(1200)
        self.graph_asset_watch_timer.timeout.connect(self._poll_linked_graph_assets)
        self.graph_asset_watch_timer.start()

        self._create_starter_graph()
        self._register_current_graph_session()
        QTimer.singleShot(0, self._restore_previous_graph_sessions)
        QTimer.singleShot(0, self._offer_recovery)
        self.statusBar().showMessage(
            "Right-click or drag from the library to add nodes. Double-click a node for its default preview, or double-click an output socket for that exact output."
        )

    def _build_docks(self) -> None:
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.graph_explorer_dock = QDockWidget("Graph Explorer", self)
        self.graph_explorer_dock.setObjectName("graphExplorerDock")
        self.graph_explorer_dock.setFeatures(features)
        self.graph_explorer_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.graph_explorer_dock.setWidget(self.graph_explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.graph_explorer_dock)

        self.library_dock = QDockWidget("Node Library", self)
        self.library_dock.setObjectName("nodeLibraryDock")
        self.library_dock.setFeatures(features)
        self.library_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.library_dock.setWidget(self.library_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
        self.splitDockWidget(self.graph_explorer_dock, self.library_dock, Qt.Orientation.Vertical)

        self.parameters_dock = QDockWidget("Inspector", self)
        self.parameters_dock.setObjectName("parametersDock")
        self.parameters_dock.setFeatures(features)
        self.parameters_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.parameters_dock.setWidget(self.parameters_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameters_dock)

        self.preview_dock = QDockWidget("2D Output", self)
        self.preview_dock.setObjectName("previewDock")
        self.preview_dock.setFeatures(features)
        self.preview_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.preview_dock.setWidget(self.preview_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_dock)
        self.splitDockWidget(self.parameters_dock, self.preview_dock, Qt.Orientation.Horizontal)

        self.preview_3d_dock = QDockWidget("3D Preview", self)
        self.preview_3d_dock.setObjectName("preview3DDock")
        self.preview_3d_dock.setFeatures(features)
        self.preview_3d_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.preview_3d_dock.setWidget(self.preview_3d_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_3d_dock)
        self.tabifyDockWidget(self.preview_dock, self.preview_3d_dock)

        self.canvas_dock = QDockWidget("Canvas Editor", self)
        self.canvas_dock.setObjectName("canvasEditorDock")
        self.canvas_dock.setFeatures(features)
        self.canvas_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.canvas_dock.setWidget(self.canvas_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.canvas_dock)
        self.tabifyDockWidget(self.preview_dock, self.canvas_dock)
        self.preview_dock.raise_()

        self.resizeDocks([self.graph_explorer_dock, self.library_dock], [220, 520], Qt.Orientation.Vertical)
        self.resizeDocks([self.library_dock], [255], Qt.Orientation.Horizontal)
        self.resizeDocks([self.parameters_dock, self.preview_dock], [330, 470], Qt.Orientation.Horizontal)
        self.timeline_dock = QDockWidget("Timeline", self)
        self.timeline_dock.setObjectName("timelineDock")
        self.timeline_dock.setFeatures(features)
        self.timeline_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.timeline_dock.setWidget(self.timeline_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)

        self.evaluation_dock = QDockWidget("Evaluation Inspector", self)
        self.evaluation_dock.setObjectName("evaluationInspectorDock")
        self.evaluation_dock.setFeatures(features)
        self.evaluation_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.evaluation_dock.setWidget(self.evaluation_inspector)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.evaluation_dock)
        self.splitDockWidget(self.timeline_dock, self.evaluation_dock, Qt.Orientation.Horizontal)
        self.resizeDocks([self.timeline_dock, self.evaluation_dock], [700, 700], Qt.Orientation.Horizontal)
        self.resizeDocks([self.timeline_dock, self.evaluation_dock], [180, 180], Qt.Orientation.Vertical)

        self.resizeDocks([self.parameters_dock, self.preview_dock], [330, 470], Qt.Orientation.Horizontal)

        self._workspace_docks = (
            self.graph_explorer_dock,
            self.library_dock,
            self.preview_dock,
            self.canvas_dock,
            self.preview_3d_dock,
            self.parameters_dock,
            self.timeline_dock,
            self.evaluation_dock,
        )
        for dock in self._workspace_docks:
            dock.setToolTip(
                "Drag the title bar onto another panel to create tabs, or drag it away from the main window to float it."
            )

    def _connect_workspace_signals(self) -> None:
        for dock in self._workspace_docks:
            dock.dockLocationChanged.connect(self._schedule_workspace_save)
            dock.topLevelChanged.connect(self._schedule_workspace_save)
            dock.visibilityChanged.connect(self._schedule_workspace_save)
            dock.installEventFilter(self)
        if hasattr(self, "tabifiedDockWidgetActivated"):
            self.tabifiedDockWidgetActivated.connect(self._schedule_workspace_save)
        self._restoring_workspace = False

    def _schedule_workspace_save(self, *_ignored) -> None:
        if self._restoring_workspace or not self._workspace_docks:
            return
        self._workspace_save_timer.start()

    def _save_workspace_layout(self) -> None:
        if self._restoring_workspace or not self._workspace_docks:
            return
        # Never serialise the dock tree while the user still has a mouse button
        # held. A pause during a drag used to let the debounce timer fire in the
        # middle of Qt's native QWidget reparent operation.
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._workspace_save_timer.start()
            return
        group = self.WORKSPACE_SETTINGS_GROUP
        self.settings.setValue(f"{group}/geometry", self.saveGeometry())
        self.settings.setValue(f"{group}/state", self.saveState(self.WORKSPACE_STATE_VERSION))
        for dock in self._workspace_docks:
            key = dock.objectName()
            self.settings.setValue(f"{group}/docks/{key}/floating", dock.isFloating())
            if dock.isFloating():
                self.settings.setValue(f"{group}/docks/{key}/geometry", dock.saveGeometry())
            else:
                self.settings.remove(f"{group}/docks/{key}/geometry")
        # Sync after every settled workspace change so an application crash does
        # not discard the user's most recent arrangement.
        self.settings.sync()

    def _restore_workspace_layout(self) -> None:
        group = self.WORKSPACE_SETTINGS_GROUP
        geometry = self.settings.value(f"{group}/geometry")
        state = self.settings.value(f"{group}/state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state, self.WORKSPACE_STATE_VERSION)
        inspector_key = f"{group}/docks/{self.evaluation_dock.objectName()}/floating"
        if state and not self.settings.contains(inspector_key):
            self.evaluation_dock.show()
            self.evaluation_dock.setFloating(False)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.evaluation_dock)
            self.splitDockWidget(self.timeline_dock, self.evaluation_dock, Qt.Orientation.Horizontal)
        for dock in self._workspace_docks:
            dock_geometry = self.settings.value(f"{group}/docks/{dock.objectName()}/geometry")
            if dock.isFloating() and dock_geometry:
                dock.restoreGeometry(dock_geometry)
        # 0.19.0's reset routine removed Canvas Editor from the dock tree but
        # could leave its View action checked. Repair that invalid saved state
        # without overriding a canvas dock the user intentionally hid.
        canvas_area = self.dockWidgetArea(self.canvas_dock)
        if (
            canvas_area == Qt.DockWidgetArea.NoDockWidgetArea
            and not self.canvas_dock.isFloating()
            and self.canvas_dock.toggleViewAction().isChecked()
        ):
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.canvas_dock)
            self.tabifyDockWidget(self.preview_dock, self.canvas_dock)
            self.canvas_dock.show()
        self._recover_offscreen_windows()

    def _recover_offscreen_windows(self) -> None:
        screens = [screen.availableGeometry() for screen in QGuiApplication.screens()]
        if not screens:
            return
        if not any(area.intersects(self.frameGeometry()) for area in screens):
            primary = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(min(self.width(), primary.width()), min(self.height(), primary.height()))
            self.move(primary.x() + 40, primary.y() + 40)
        primary = QGuiApplication.primaryScreen().availableGeometry()
        for index, dock in enumerate(self._workspace_docks):
            if not dock.isFloating():
                continue
            geometry = dock.frameGeometry()
            if geometry.isValid() and any(area.intersects(geometry) for area in screens):
                continue
            width = min(max(dock.width(), 360), primary.width())
            height = min(max(dock.height(), 260), primary.height())
            dock.resize(width, height)
            offset = 50 + index * 28
            dock.move(primary.x() + offset, primary.y() + offset)

    def _tab_output_docks(self) -> None:
        self._restoring_workspace = True
        try:
            for dock in (self.preview_dock, self.preview_3d_dock, self.canvas_dock):
                dock.show()
                if dock.isFloating():
                    dock.setFloating(False)
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            self.tabifyDockWidget(self.preview_dock, self.preview_3d_dock)
            self.tabifyDockWidget(self.preview_dock, self.canvas_dock)
            self.preview_dock.raise_()
        finally:
            self._restoring_workspace = False
        self._save_workspace_layout()
        self.statusBar().showMessage(
            "2D Preview, 3D Preview and Canvas Editor are now tabbed. Drag any tab away to separate or float it.",
            5000,
        )

    def _apply_default_workspace_layout(self) -> None:
        """Restore the readable authoring layout used for first launch.

        Parameters remains permanently visible in a tall column. The 2D
        preview, 3D preview and Canvas Editor share the neighbouring tab group.

        Do not remove every dock from the main window here.  In particular the
        3D dock owns a rendercanvas widget; removing and immediately reparenting
        that native-backed widget can crash Qt/Wayland inside the dock reset.
        Moving the existing docks in place lets QMainWindow update its dock tree
        without destroying the embedded preview surface.
        """
        self._workspace_save_timer.stop()
        updates_were_enabled = self.updatesEnabled()
        canvas_updates_were_enabled = self.preview_3d_panel.canvas.updatesEnabled()
        self.setUpdatesEnabled(False)
        self.preview_3d_panel.canvas.setUpdatesEnabled(False)
        previous_signal_states = {dock: dock.blockSignals(True) for dock in self._workspace_docks}
        try:
            # Dock floating panels before positioning them.  Non-floating docks
            # are moved directly by addDockWidget/splitDockWidget/tabifyDockWidget.
            for dock in self._workspace_docks:
                if dock.isFloating():
                    dock.setFloating(False)

            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.graph_explorer_dock)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
            self.splitDockWidget(self.graph_explorer_dock, self.library_dock, Qt.Orientation.Vertical)

            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameters_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_dock)
            self.splitDockWidget(self.parameters_dock, self.preview_dock, Qt.Orientation.Horizontal)

            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_3d_dock)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.canvas_dock)
            self.tabifyDockWidget(self.preview_dock, self.preview_3d_dock)
            self.tabifyDockWidget(self.preview_dock, self.canvas_dock)

            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.evaluation_dock)
            self.splitDockWidget(self.timeline_dock, self.evaluation_dock, Qt.Orientation.Horizontal)

            for dock in self._workspace_docks:
                dock.show()
            self.preview_dock.raise_()

            self.resizeDocks([self.graph_explorer_dock, self.library_dock], [220, 520], Qt.Orientation.Vertical)
            self.resizeDocks([self.library_dock], [255], Qt.Orientation.Horizontal)
            self.resizeDocks([self.parameters_dock, self.preview_dock], [330, 470], Qt.Orientation.Horizontal)
            self.resizeDocks([self.timeline_dock, self.evaluation_dock], [180, 180], Qt.Orientation.Vertical)
            self.resizeDocks([self.timeline_dock, self.evaluation_dock], [700, 700], Qt.Orientation.Horizontal)
        finally:
            for dock, previous in previous_signal_states.items():
                dock.blockSignals(previous)
            self.preview_3d_panel.canvas.setUpdatesEnabled(canvas_updates_were_enabled)
            self.setUpdatesEnabled(updates_were_enabled)

        # Repaint only after Qt has completed the dock-tree transaction.
        QTimer.singleShot(0, self.update)
        if self.preview_3d_panel.canvas.renderer.available:
            QTimer.singleShot(50, self.preview_3d_panel.canvas.renderer.request_draw)

    def _perform_workspace_reset(self) -> None:
        self._restoring_workspace = True
        try:
            self._apply_default_workspace_layout()
        finally:
            self._restoring_workspace = False
        self._save_workspace_layout()
        self.statusBar().showMessage("Workspace layout reset", 3500)

    def _reset_workspace_layout(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset workspace layout?",
            "Restore the original panel arrangement? Your graph will not be affected.",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Reset,
        )
        if answer != QMessageBox.StandardButton.Reset:
            return
        # Let the modal confirmation dialog finish tearing itself down before
        # changing dock parents. Reparenting a render surface from inside the
        # dialog's return path can enter Qt's native window code re-entrantly.
        QTimer.singleShot(0, self._perform_workspace_reset)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._workspace_docks and event.type() in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        }:
            self._schedule_workspace_save()
        return super().eventFilter(watched, event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_workspace_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_workspace_save()

    def _canvas_editor_has_focus(self) -> bool:
        focus = QApplication.focusWidget()
        return bool(
            focus is not None
            and (focus is self.canvas_panel or self.canvas_panel.isAncestorOf(focus))
            and self.canvas_dock.isVisible()
        )

    def _route_undo(self) -> None:
        if self._canvas_editor_has_focus() and self.canvas_panel.can_undo_canvas():
            self.canvas_panel.undo_canvas()
            return
        self.scene.undo_stack.undo()

    def _route_redo(self) -> None:
        if self._canvas_editor_has_focus() and self.canvas_panel.can_redo_canvas():
            self.canvas_panel.redo_canvas()
            return
        self.scene.undo_stack.redo()

    def _build_actions(self) -> None:
        self.new_action = QAction("New", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)

        self.open_action = QAction("Open…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_project)

        self.save_action = QAction("Save", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)

        self.save_as_action = QAction("Save As…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_project_as)

        self.save_all_action = QAction("Save All", self)
        self.save_all_action.setShortcut(QKeySequence("Ctrl+Alt+S"))
        self.save_all_action.triggered.connect(self.save_all_projects)

        self.close_graph_action = QAction("Close Graph", self)
        self.close_graph_action.setShortcut(QKeySequence("Ctrl+W"))
        self.close_graph_action.triggered.connect(self.close_active_graph)

        self.restore_graph_session_action = QAction("Restore Open Graphs on Startup", self)
        self.restore_graph_session_action.setCheckable(True)
        self.restore_graph_session_action.setChecked(
            str(self.settings.value("session/restore_open_graphs", "false")).lower()
            in {"1", "true", "yes"}
        )
        self.restore_graph_session_action.toggled.connect(
            lambda checked: self.settings.setValue("session/restore_open_graphs", bool(checked))
        )

        self.export_action = QAction("Export Outputs…", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self.export_active_image)

        self.export_self_contained_action = QAction("Export Self-Contained Graph…", self)
        self.export_self_contained_action.setStatusTip(
            "Write a portable .vfxgraph with all nested graphs and images embedded"
        )
        self.export_self_contained_action.triggered.connect(self.export_self_contained_graph)

        self.export_vfxpackage_action = QAction("Export VFX Package…", self)
        self.export_vfxpackage_action.setStatusTip(
            "Create a validated .vfxpackage archive for sharing or library installation"
        )
        self.export_vfxpackage_action.triggered.connect(self.export_vfxpackage)

        self.open_vfxpackage_action = QAction("Open VFX Package…", self)
        self.open_vfxpackage_action.triggered.connect(self.open_vfxpackage)

        self.install_vfxpackage_action = QAction("Install VFX Package…", self)
        self.install_vfxpackage_action.triggered.connect(self.install_vfxpackage)

        self.import_export_template_action = QAction("Install Export Template…", self)
        self.import_export_template_action.triggered.connect(self._install_export_template_file)
        self.manage_export_templates_action = QAction("User Export Templates…", self)
        self.manage_export_templates_action.triggered.connect(
            lambda: ExportTemplateLibraryDialog(self).exec()
        )
        self.open_export_template_folder_action = QAction("Open User Export Template Folder", self)
        self.open_export_template_folder_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_template_directory())))
        )

        self.document_settings_action = QAction("Document Settings…", self)
        self.document_settings_action.setShortcut(QKeySequence("Ctrl+Alt+D"))
        self.document_settings_action.triggered.connect(self.edit_document_settings)

        self.recover_action = QAction("Recover Autosave…", self)
        self.recover_action.triggered.connect(self._recover_autosave_manually)
        self.recover_action.setEnabled(self._autosave_path.exists())

        self.exit_action = QAction("Exit", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self._route_undo)
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        self.redo_action.triggered.connect(self._route_redo)

        self.copy_action = QAction("Copy", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_action.triggered.connect(self.graph_view.copy_selected)
        self.graph_view.addAction(self.copy_action)

        self.paste_action = QAction("Paste", self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.paste_action.triggered.connect(self.graph_view.paste_at_cursor)
        self.graph_view.addAction(self.paste_action)

        self.delete_action = QAction("Delete Selected", self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        # Keep the graph deletion shortcut local to the graph canvas.  Visual
        # parameter editors (curves, gradients, and future point editors) own
        # Delete/Backspace while they have keyboard focus, so selecting a
        # control point can never accidentally remove the whole graph node.
        self.delete_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_action.triggered.connect(lambda: self.scene.delete_selected())
        self.graph_view.addAction(self.delete_action)

        self.group_action = QAction("Group Selected", self)
        self.group_action.setShortcut(QKeySequence("Ctrl+G"))
        self.group_action.triggered.connect(lambda: self.scene.group_selected_nodes())

        self.empty_group_action = QAction("Add Empty Group", self)
        self.empty_group_action.triggered.connect(self.graph_view.add_empty_group_at_cursor)

        self.ungroup_action = QAction("Ungroup", self)
        self.ungroup_action.triggered.connect(lambda: self.scene.ungroup_selected())

        self.collapse_group_action = QAction("Collapse / Expand Group", self)
        self.collapse_group_action.triggered.connect(lambda: self.scene.toggle_selected_group())

        self.save_group_action = QAction("Save Group to User Library…", self)
        self.save_group_action.triggered.connect(self._save_selected_group)

        self.open_user_library_action = QAction("Open Reusable Group Folder", self)
        self.open_user_library_action.triggered.connect(self._open_user_library)

        self.custom_libraries_action = QAction("Custom Node & Graph Asset Libraries…", self)
        self.custom_libraries_action.triggered.connect(self._show_custom_node_libraries)

        self.install_custom_node_action = QAction("Install Custom Node Package…", self)
        self.install_custom_node_action.triggered.connect(self._install_custom_node_package)

        self.reload_custom_nodes_action = QAction("Reload Custom Nodes", self)
        self.reload_custom_nodes_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.reload_custom_nodes_action.triggered.connect(self._reload_custom_nodes)

        self.custom_node_diagnostics_action = QAction("Custom Node Diagnostics…", self)
        self.custom_node_diagnostics_action.triggered.connect(self._show_custom_node_diagnostics)

        self.open_managed_nodes_action = QAction("Open Managed Custom Node Folder", self)
        self.open_managed_nodes_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.package_manager.managed_directory)))
        )

        self.frame_action = QAction("Frame Selected", self)
        self.frame_action.setShortcut(QKeySequence("F"))
        self.frame_action.triggered.connect(self._frame_selected)

        self.reroute_action = QAction("Add Reroute to Wire", self)
        self.reroute_action.setShortcut(QKeySequence("R"))
        self.reroute_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.graph_view.addAction(self.reroute_action)
        self.reroute_action.setStatusTip("Insert a typed reroute dot on the selected or hovered wire")
        self.reroute_action.triggered.connect(self.graph_view.add_reroute_at_cursor)

        self.bypass_action = QAction("Toggle Node Bypass", self)
        self.bypass_action.setShortcut(QKeySequence("B"))
        self.bypass_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.graph_view.addAction(self.bypass_action)
        self.bypass_action.setStatusTip("Temporarily pass a compatible single-input node through unchanged")
        self.bypass_action.triggered.connect(self._toggle_selected_bypass)

        self.align_left_action = QAction("Align Left", self)
        self.align_left_action.triggered.connect(lambda: self.scene.arrange_selected("left"))
        self.align_hcentre_action = QAction("Align Horizontal Centres", self)
        self.align_hcentre_action.triggered.connect(lambda: self.scene.arrange_selected("hcenter"))
        self.align_right_action = QAction("Align Right", self)
        self.align_right_action.triggered.connect(lambda: self.scene.arrange_selected("right"))
        self.align_top_action = QAction("Align Top", self)
        self.align_top_action.triggered.connect(lambda: self.scene.arrange_selected("top"))
        self.align_vcentre_action = QAction("Align Vertical Centres", self)
        self.align_vcentre_action.triggered.connect(lambda: self.scene.arrange_selected("vcenter"))
        self.align_bottom_action = QAction("Align Bottom", self)
        self.align_bottom_action.triggered.connect(lambda: self.scene.arrange_selected("bottom"))
        self.distribute_horizontal_action = QAction("Distribute Horizontally", self)
        self.distribute_horizontal_action.triggered.connect(lambda: self.scene.distribute_selected("horizontal"))
        self.distribute_vertical_action = QAction("Distribute Vertically", self)
        self.distribute_vertical_action.triggered.connect(lambda: self.scene.distribute_selected("vertical"))

        self.clear_cache_action = QAction("Clear Render Cache", self)
        self.clear_cache_action.triggered.connect(self._clear_render_cache)

        self.cache_budget_action = QAction("Set Render Cache Budget…", self)
        self.cache_budget_action.triggered.connect(self._set_cache_budget)

        self.gpu_diagnostics_action = QAction("GPU / Renderer Diagnostics", self)
        self.gpu_diagnostics_action.triggered.connect(self._show_gpu_diagnostics)

        self.tab_outputs_action = QAction("Tab 2D, 3D and Canvas Outputs", self)
        self.tab_outputs_action.setStatusTip("Combine the 2D preview, 3D preview and Canvas Editor into one tabbed dock group")
        self.tab_outputs_action.triggered.connect(self._tab_output_docks)

        self.reset_workspace_action = QAction("Reset Workspace Layout", self)
        self.reset_workspace_action.setStatusTip("Restore the original panel arrangement")
        self.reset_workspace_action.triggered.connect(self._reset_workspace_layout)

        self.save_startup_graph_action = QAction("Save Current Graph as Startup", self)
        self.save_startup_graph_action.setStatusTip(
            "Use the current graph and document settings whenever a new project is created"
        )
        self.save_startup_graph_action.triggered.connect(self._save_current_as_startup_graph)

        self.restore_builtin_startup_action = QAction("Restore Built-in Startup Graph", self)
        self.restore_builtin_startup_action.setStatusTip(
            "Stop using the custom startup graph and return to the bundled lightweight graph"
        )
        self.restore_builtin_startup_action.triggered.connect(self._restore_builtin_startup_graph)
        self.restore_builtin_startup_action.setEnabled(self._startup_graph_path.exists())

        self.open_startup_folder_action = QAction("Open Startup Graph Folder", self)
        self.open_startup_folder_action.triggered.connect(self._open_startup_graph_folder)

        self.import_theme_action = QAction("Import Theme…", self)
        self.import_theme_action.triggered.connect(self._import_theme)
        self.export_theme_action = QAction("Export Current Theme as JSON…", self)
        self.export_theme_action.triggered.connect(self._export_current_theme)
        self.reload_themes_action = QAction("Reload User Themes", self)
        self.reload_themes_action.triggered.connect(self._rebuild_theme_menu)
        self.open_theme_folder_action = QAction("Open User Theme Folder", self)
        self.open_theme_folder_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._theme_directory)))
        )

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addActions((self.new_action, self.open_action))
        file_menu.addAction(self.open_vfxpackage_action)
        file_menu.addAction(self.recover_action)
        file_menu.addSeparator()
        file_menu.addActions((self.save_action, self.save_as_action, self.save_all_action))
        file_menu.addAction(self.close_graph_action)
        file_menu.addAction(self.document_settings_action)
        defaults_menu = file_menu.addMenu("Defaults")
        defaults_menu.addAction(self.save_startup_graph_action)
        defaults_menu.addAction(self.restore_builtin_startup_action)
        defaults_menu.addSeparator()
        defaults_menu.addAction(self.restore_graph_session_action)
        defaults_menu.addSeparator()
        defaults_menu.addAction(self.open_startup_folder_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.export_self_contained_action)
        file_menu.addAction(self.export_vfxpackage_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addActions((self.undo_action, self.redo_action))
        edit_menu.addSeparator()
        edit_menu.addActions((self.copy_action, self.paste_action, self.delete_action))
        edit_menu.addSeparator()
        edit_menu.addActions((self.group_action, self.empty_group_action, self.ungroup_action))
        edit_menu.addAction(self.collapse_group_action)
        edit_menu.addAction(self.save_group_action)
        edit_menu.addSeparator()
        edit_menu.addActions((self.reroute_action, self.bypass_action))
        arrange_menu = edit_menu.addMenu("Arrange")
        arrange_menu.addActions((self.align_left_action, self.align_hcentre_action, self.align_right_action))
        arrange_menu.addSeparator()
        arrange_menu.addActions((self.align_top_action, self.align_vcentre_action, self.align_bottom_action))
        arrange_menu.addSeparator()
        arrange_menu.addActions((self.distribute_horizontal_action, self.distribute_vertical_action))
        edit_menu.addSeparator()
        edit_menu.addAction(self.frame_action)

        view_menu = self.menuBar().addMenu("View")
        for dock in self._workspace_docks:
            action = dock.toggleViewAction()
            action.setText(dock.windowTitle())
            view_menu.addAction(action)
        view_menu.addSeparator()
        self.theme_menu = view_menu.addMenu("Theme")
        self._rebuild_theme_menu()
        view_menu.addSeparator()
        view_menu.addAction(self.tab_outputs_action)
        view_menu.addAction(self.reset_workspace_action)

        render_menu = self.menuBar().addMenu("Render")
        render_menu.addAction(self.clear_cache_action)
        render_menu.addAction(self.cache_budget_action)
        render_menu.addSeparator()
        render_menu.addAction(self.gpu_diagnostics_action)

        library_menu = self.menuBar().addMenu("Library")
        library_menu.addAction(self.custom_libraries_action)
        library_menu.addAction(self.install_vfxpackage_action)
        library_menu.addAction(self.import_export_template_action)
        library_menu.addAction(self.manage_export_templates_action)
        library_menu.addAction(self.install_custom_node_action)
        library_menu.addAction(self.reload_custom_nodes_action)
        library_menu.addAction(self.custom_node_diagnostics_action)
        library_menu.addSeparator()
        library_menu.addAction(self.open_managed_nodes_action)
        library_menu.addAction(self.open_user_library_action)
        library_menu.addAction(self.open_export_template_folder_action)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(self.gpu_diagnostics_action)
        help_menu.addAction(self.custom_node_diagnostics_action)
        help_menu.addSeparator()
        about_action = help_menu.addAction("About VFX Texture Lab")
        about_action.triggered.connect(self._show_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.document_settings_action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Preview max:"))
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(("128", "256", "512", "1024", "2048", "4096"))
        self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
        self.resolution_combo.currentTextChanged.connect(self._resolution_changed)
        toolbar.addWidget(self.resolution_combo)
        self.document_summary = QLabel()
        self.document_summary.setObjectName("muted")
        toolbar.addWidget(self.document_summary)
        self._refresh_document_summary()
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Renderer:"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Auto", "auto")
        self.backend_combo.addItem("GPU", "gpu")
        self.backend_combo.addItem("CPU", "cpu")
        backend_index = self.backend_combo.findData(self.evaluator.backend_preference)
        self.backend_combo.setCurrentIndex(max(backend_index, 0))
        self.backend_combo.setToolTip("Auto uses WGSL/WebGPU for migrated nodes and the CPU reference backend for the rest")
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        toolbar.addWidget(self.backend_combo)
        self.backend_status = QLabel()
        self.backend_status.setObjectName("muted")
        self._refresh_backend_status()
        toolbar.addWidget(self.backend_status)
        toolbar.addSeparator()
        hint = QLabel("Connections snap to nearby compatible sockets    ·    Shift+drag nodes = grid snap    ·    Double-click wire = reroute    ·    Hold X + drag = cut wires    ·    B = bypass")
        hint.setObjectName("muted")
        toolbar.addWidget(hint)

    def _available_themes(self) -> dict[str, dict]:
        themes = {theme_id: dict(theme) for theme_id, theme in BUILTIN_THEMES.items()}
        themes.update(load_custom_themes(self._theme_directory))
        return themes

    def _rebuild_theme_menu(self, *_ignored) -> None:
        if self.theme_menu is None:
            return
        self.theme_menu.clear()
        self._theme_action_group = QActionGroup(self.theme_menu)
        self._theme_action_group.setExclusive(True)
        selected_id = str(self.settings.value("appearance/theme", active_theme().get("id", "midnight")))
        themes = self._available_themes()
        if selected_id not in themes:
            selected_id = str(active_theme().get("id", "midnight"))
        builtins = [(theme_id, themes[theme_id]) for theme_id in BUILTIN_THEMES if theme_id in themes]
        custom = [
            (theme_id, theme)
            for theme_id, theme in themes.items()
            if theme_id not in BUILTIN_THEMES
        ]
        for index, entries in enumerate((builtins, sorted(custom, key=lambda item: item[1]["name"].lower()))):
            if index and entries:
                self.theme_menu.addSeparator()
            for theme_id, theme in entries:
                action = QAction(str(theme["name"]), self.theme_menu)
                action.setCheckable(True)
                action.setData(theme_id)
                action.setChecked(theme_id == selected_id)
                action.triggered.connect(
                    lambda checked=False, value=theme_id: self._apply_theme(value) if checked else None
                )
                self._theme_action_group.addAction(action)
                self.theme_menu.addAction(action)
        self.theme_menu.addSeparator()
        self.theme_menu.addAction(self.import_theme_action)
        self.theme_menu.addAction(self.export_theme_action)
        self.theme_menu.addAction(self.reload_themes_action)
        self.theme_menu.addAction(self.open_theme_folder_action)

    def _apply_theme(self, theme_id: str) -> None:
        theme = resolve_theme(theme_id, self._theme_directory)
        set_active_theme(theme)
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(build_stylesheet(theme))
        self.settings.setValue("appearance/theme", theme["id"])
        self.settings.sync()
        self.graph_view.refresh_theme()
        self.scene.update()
        self.preview_panel.update()
        self.canvas_panel.refresh_theme()
        self.canvas_panel.update()
        self.preview_3d_panel.update()
        self.parameters_panel.update()
        self.timeline_panel.update()
        self.evaluation_inspector.update()
        QTimer.singleShot(0, self._rebuild_theme_menu)
        self.statusBar().showMessage(f"Theme changed to {theme['name']}", 3000)

    def _import_theme(self) -> None:
        filename, _selected = QFileDialog.getOpenFileName(
            self,
            "Import VFX Texture Lab theme",
            str(self._theme_directory),
            "VFX Texture Lab Theme (*.json);;JSON files (*.json)",
        )
        if not filename:
            return
        try:
            source = Path(filename)
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Theme JSON must contain an object")
            exported = theme_to_json(raw)
            if exported["id"] in BUILTIN_THEMES:
                exported["id"] = f"{exported['id']}-custom"
                exported["name"] = f"{exported['name']} Custom"
            destination = self._theme_directory / f"{exported['id']}.json"
            destination.write_text(json.dumps(exported, indent=2), encoding="utf-8")
            self._rebuild_theme_menu()
            self._apply_theme(exported["id"])
            self.statusBar().showMessage(f"Imported theme {exported['name']}", 3500)
        except Exception as exc:
            QMessageBox.critical(self, "Could not import theme", str(exc))

    def _export_current_theme(self) -> None:
        exported = theme_to_json(active_theme())
        if exported["id"] in BUILTIN_THEMES:
            exported["id"] = f"{exported['id']}-custom"
            exported["name"] = f"{exported['name']} Custom"
        default_name = f"{exported['id']}.json"
        filename, _selected = QFileDialog.getSaveFileName(
            self,
            "Export theme as JSON",
            str(self._theme_directory / default_name),
            "VFX Texture Lab Theme (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            path.write_text(json.dumps(exported, indent=2), encoding="utf-8")
            self.statusBar().showMessage(f"Exported theme to {path.name}", 3500)
        except Exception as exc:
            QMessageBox.critical(self, "Could not export theme", str(exc))

    def _connect_active_scene_signals(self, scene: GraphScene) -> None:
        scene.activeNodeChanged.connect(self._active_node_changed)
        scene.selectedNodeChanged.connect(self.canvas_panel.set_item)
        scene.selectedNodeChanged.connect(self._selected_item_changed)
        scene.graphChanged.connect(self._graph_changed)
        scene.thumbnailChanged.connect(self._thumbnail_state_changed)
        scene.undo_stack.cleanChanged.connect(self._undo_clean_changed)

    def _disconnect_active_scene_signals(self, scene: GraphScene) -> None:
        pairs = (
            (scene.activeNodeChanged, self._active_node_changed),
            (scene.selectedNodeChanged, self.canvas_panel.set_item),
            (scene.selectedNodeChanged, self._selected_item_changed),
            (scene.graphChanged, self._graph_changed),
            (scene.thumbnailChanged, self._thumbnail_state_changed),
            (scene.undo_stack.cleanChanged, self._undo_clean_changed),
        )
        for signal, slot in pairs:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _connect_signals(self) -> None:
        self._connect_active_scene_signals(self.scene)
        self.canvas_panel.createCanvasRequested.connect(
            lambda: self.graph_view.add_node_at_centre("input.canvas")
        )
        self.canvas_panel.canvasChanged.connect(self._mark_document_dirty)
        self.library_panel.nodeActivated.connect(self.graph_view.add_node_at_centre)
        self.library_panel.userNodeActivated.connect(self.graph_view.add_user_node_at_centre)
        self.library_panel.graphAssetActivated.connect(self.graph_view.add_graph_asset_at_centre)
        self.library_panel.graphAssetOpenRequested.connect(self._open_graph_asset_source)
        self.library_panel.graphAssetThumbnailRequested.connect(self._edit_graph_asset_thumbnail)
        self.graph_view.graphAssetOpenRequested.connect(self._open_graph_asset_source)
        self.graph_view.backgroundClicked.connect(self._inspect_active_graph)
        self.graph_view.inspectorItemClicked.connect(self._selected_item_changed)
        self.graph_view.openGraphInstanceRequested.connect(self._insert_open_graph_instance)
        self.graph_view.graphResourceDropRequested.connect(self._insert_graph_resource)
        self.graph_view.set_open_graph_drop_validator(self._can_insert_open_graph_instance)
        self.graph_explorer.newRequested.connect(self.new_project)
        self.graph_explorer.openRequested.connect(self.open_project)
        self.graph_explorer.saveRequested.connect(self._explorer_save_requested)
        self.graph_explorer.saveAsRequested.connect(self._explorer_save_as_requested)
        self.graph_explorer.saveCopyRequested.connect(self._explorer_save_copy_requested)
        self.graph_explorer.saveAllRequested.connect(self.save_all_projects)
        self.graph_explorer.activateRequested.connect(self._explorer_activate_graph_session)
        self.graph_explorer.selectedRequested.connect(self._inspect_graph_session)
        self.graph_explorer.closeRequested.connect(self.close_graph_session)
        self.graph_explorer.closeOthersRequested.connect(self.close_other_graph_sessions)
        self.graph_explorer.duplicateRequested.connect(self.duplicate_graph_session)
        self.graph_explorer.revealRequested.connect(self._reveal_graph_session)
        self.graph_explorer.reloadRequested.connect(self._reload_graph_session)
        self.graph_explorer.addToLibraryRequested.connect(self._add_graph_session_to_library)
        self.graph_explorer.addFolderRequested.connect(self._explorer_add_resource_folder)
        self.graph_explorer.renameFolderRequested.connect(self._explorer_rename_resource_folder)
        self.graph_explorer.removeFolderRequested.connect(self._explorer_remove_resource_folder)
        self.graph_explorer.resourceSelectedRequested.connect(self._explorer_select_resource)
        self.graph_explorer.resourceRelinkRequested.connect(self._explorer_relink_resource)
        self.graph_explorer.resourceEmbedRequested.connect(self._explorer_embed_resource)
        self.graph_explorer.resourceRestoreRequested.connect(self._explorer_restore_resource)
        self.graph_explorer.resourceRevealRequested.connect(self._explorer_reveal_resource)
        self.graph_explorer.resourceRenameRequested.connect(self._explorer_rename_resource)
        self.graph_explorer.resourceMoveRequested.connect(self._explorer_move_resource)
        self.graph_explorer.resourceRemoveRequested.connect(self._explorer_remove_resource)
        self.library_panel.reloadCustomNodesRequested.connect(self._reload_custom_nodes)
        self.package_manager.sourceFilesChanged.connect(self._custom_node_files_changed)
        self.preview_panel.exportRequested.connect(self.export_active_image)
        self.preview_panel.gizmoEditStarted.connect(self._preview_gizmo_started)
        self.preview_panel.gizmoParametersChanged.connect(self._preview_gizmo_changed)
        self.preview_panel.gizmoEditFinished.connect(self._preview_gizmo_finished)
        self.preview_panel.editInputToggled.connect(self._preview_edit_input_toggled)
        self.parameters_panel.saveGroupRequested.connect(self._save_group_to_library)
        self.parameters_panel.openUserLibraryRequested.connect(self._open_user_library)
        self.parameters_panel.textureSetQuickExportRequested.connect(self._texture_set_quick_export)
        self.parameters_panel.geometryExportRequested.connect(self._geometry_export)
        self.parameters_panel.exportTemplateEditRequested.connect(self._edit_export_template)
        self.parameters_panel.manualActionRequested.connect(self._run_manual_node_action)
        self.parameters_panel.manualActionCancelRequested.connect(self._cancel_manual_node_action)
        self.preview_panel.uvOptionsChanged.connect(self._uv_preview_options_changed)
        self.parameters_panel.interactiveEditStarted.connect(self._parameter_interaction_started)
        self.parameters_panel.interactiveEditFinished.connect(self._parameter_interaction_finished)
        self.parameters_panel.histogramActivityChanged.connect(
            self.evaluation_inspector.set_background_activity
        )
        self.eval_controller.resultReady.connect(self._preview_ready)
        self.eval_controller.evaluationStarted.connect(self._preview_started)
        self.eval_controller.evaluationFailed.connect(self._preview_failed)
        self.eval_controller.evaluationProgress.connect(self._preview_progress)
        self.eval_controller.evaluationNodeState.connect(self._preview_node_state)
        self.geometry_controller.resultReady.connect(self._geometry_preview_ready)
        self.geometry_controller.evaluationStarted.connect(self._geometry_preview_started)
        self.geometry_controller.evaluationFailed.connect(self._geometry_preview_failed)
        self.geometry_controller.evaluationProgress.connect(self._geometry_preview_progress)
        self.geometry_controller.evaluationNodeState.connect(self._geometry_node_state)
        self.thumbnail_controller.resultReady.connect(self._thumbnail_ready)
        self.thumbnail_controller.evaluationFailed.connect(self._thumbnail_failed)
        self.graph_view.viewportChanged.connect(self._schedule_thumbnail_refresh)
        self.playback_controller.resultReady.connect(self._playback_frame_ready)
        self.playback_controller.evaluationFailed.connect(self._playback_frame_failed)
        self.material_controller.resultReady.connect(self._material_preview_ready)
        self.material_controller.evaluationStarted.connect(self._material_preview_started)
        self.material_controller.evaluationFailed.connect(self._material_preview_failed)
        self.material_controller.evaluationProgress.connect(self._material_preview_progress)
        self.material_controller.evaluationNodeState.connect(self._material_node_state)
        self.preview_3d_panel.textureResolutionChanged.connect(self._viewport_texture_resolution_changed)
        self.preview_3d_panel.viewportSettingsChanged.connect(self._mark_document_dirty)
        self.preview_3d_panel.settingsRequested.connect(self._show_3d_viewport_settings)
        self.timeline_panel.frameChanged.connect(self._timeline_frame_changed)
        self.timeline_panel.playToggled.connect(self._set_playing)
        self.timeline_panel.stopRequested.connect(self._stop_playback)
        self.timeline_panel.settingsChanged.connect(self._timeline_settings_changed)
        self.timeline_panel.performanceSettingsChanged.connect(self._timeline_performance_settings_changed)
        self.timeline_panel.resetSimulationsRequested.connect(self._reset_all_simulations)
        self.graph_view.simulationResetRequested.connect(self._reset_simulation_node)
        self.graph_view.exportOutputsRequested.connect(self.export_outputs)
        self.evaluation_inspector.nodeRequested.connect(self._focus_inspector_node)

    def _next_evaluation_job(self, kind: str) -> int:
        self._evaluation_job_id += 1
        self._evaluation_job_kind = str(kind)
        self._evaluation_job_started = time.perf_counter()
        return self._evaluation_job_id

    def _focus_inspector_node(self, node_uid: str) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None:
            return
        self.scene.clearSelection()
        node.setSelected(True)
        self.scene.set_active_node(node)
        self.graph_view.centerOn(node)

    def _load_custom_startup_graph(self) -> bool:
        try:
            data = self._migrate_project_data(
                json.loads(self._startup_graph_path.read_text(encoding="utf-8"))
            )
            self._cancel_interactive_previews()
            self._loading = True
            self.document = DocumentSettings.from_dict(data.get("document"))
            self.graph_asset = GraphAssetMetadata.from_dict(
                data.get("graph_asset"), default_name="Untitled Graph", created_with=__version__
            )
            self.export_profiles = ExportProfileLibrary.from_dict(data.get("export_profiles"))
            self.graph_resources = GraphResourceLibrary.from_dict(data.get("resources"))
            self.graph_asset.regenerate_identity()
            self.current_frame = 0
            self.scene.default_tiling = self.document.default_tiling
            self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
            self.scene.canvas_default_size = (self.document.width, self.document.height)
            if hasattr(self, "resolution_combo"):
                self.resolution_combo.blockSignals(True)
                self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
                self.resolution_combo.blockSignals(False)
            self.timeline_panel.set_document(self.document)
            self.timeline_panel.set_frame(0, emit=False)
            self._update_playback_interval()
            # A startup template defines the graph/document, but every new file
            # begins with the application viewport defaults rather than carrying
            # presentation state from the file used to create the template.
            self.preview_3d_panel.reset_project_state()
            self.scene.from_dict(data)
            if self.scene.active_node is None:
                candidate = next(
                    (
                        node for node in self.scene.nodes.values()
                        if node.definition.type_id in {self.MATERIAL_NODE_TYPE, self.IMAGE_OUTPUT_NODE_TYPE}
                    ),
                    next(iter(self.scene.nodes.values()), None),
                )
                self.scene.set_active_node(candidate)
            self._refresh_document_summary()
            self.current_path = None
            self.scene.undo_stack.clear()
            self.scene.undo_stack.setClean()
            self._document_dirty = False
            self._recovered_dirty = False
            self._set_dirty(False)
            self._loading = False
            QTimer.singleShot(0, self._frame_all_nodes)
            self._schedule_preview()
            self._schedule_3d_preview()
            self.statusBar().showMessage("Created project from custom startup graph", 3500)
            return True
        except Exception as exc:
            self._loading = False
            self.statusBar().showMessage(
                f"Custom startup graph could not be loaded; using built-in graph: {exc}",
                7000,
            )
            return False

    def _save_current_as_startup_graph(self) -> None:
        answer = QMessageBox.question(
            self,
            "Save startup graph",
            "Use the current graph and document settings for every new project?\n\n"
            "The current project file is not replaced or moved.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer != QMessageBox.StandardButton.Save:
            return
        try:
            self._startup_graph_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._project_data()
            data.pop("_autosave", None)
            data["_startup_template"] = {
                "app_version": __version__,
                "saved_at": time.time(),
            }
            temporary = self._startup_graph_path.with_suffix(".vfxgraph.tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(self._startup_graph_path)
            self.restore_builtin_startup_action.setEnabled(True)
            self.statusBar().showMessage("Current graph saved as the startup graph", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save startup graph", str(exc))

    def _restore_builtin_startup_graph(self) -> None:
        if not self._startup_graph_path.exists():
            self.statusBar().showMessage("The built-in startup graph is already active", 3000)
            return
        answer = QMessageBox.question(
            self,
            "Restore built-in startup graph",
            "Stop using the custom startup graph for future new projects?",
            QMessageBox.StandardButton.RestoreDefaults | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.RestoreDefaults,
        )
        if answer != QMessageBox.StandardButton.RestoreDefaults:
            return
        try:
            self._startup_graph_path.unlink(missing_ok=True)
            self.restore_builtin_startup_action.setEnabled(False)
            self.statusBar().showMessage(
                "Built-in startup graph restored for future new projects",
                4000,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not restore startup graph", str(exc))

    def _open_startup_graph_folder(self) -> None:
        self._startup_graph_path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._startup_graph_path.parent)))

    def _create_starter_graph(self) -> None:
        if self._startup_graph_path.is_file() and self._load_custom_startup_graph():
            return
        self.document = DocumentSettings()
        self.preview_3d_panel.reset_project_state()
        self.preview_3d_panel.set_viewport_setting("displacement_amount", 0.30, persist=False)
        self.scene.default_tiling = self.document.default_tiling
        self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
        self.scene.canvas_default_size = (self.document.width, self.document.height)
        if hasattr(self, "resolution_combo"):
            self.resolution_combo.blockSignals(True)
            self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
            self.resolution_combo.blockSignals(False)
        self.current_frame = 0
        if hasattr(self, "timeline_panel"):
            self.timeline_panel.set_document(self.document)
            self.timeline_panel.set_frame(0, emit=False)
        self._refresh_document_summary()
        self._loading = True
        self.scene.clear_graph(record_undo=False)

        # Keep the new-document example useful but deliberately lightweight.
        # Expensive erosion belongs in the library, not in the graph that every
        # user must evaluate each time they create a document.
        noise = self.scene.create_node("noise.ridged", QPointF(-1180, -110), record_undo=False)
        preblur = self.scene.create_node("filter.blur", QPointF(-920, -110), record_undo=False)
        levels = self.scene.create_node("filter.levels", QPointF(-660, -110), record_undo=False)
        gradient = self.scene.create_node("convert.gradient_map", QPointF(-390, -190), record_undo=False)
        normal = self.scene.create_node("convert.height_normal", QPointF(-390, 55), record_undo=False)
        metallic = self.scene.create_node("generator.constant", QPointF(-450, 250), record_undo=False)
        roughness = self.scene.create_node("generator.constant", QPointF(-210, 250), record_undo=False)
        specular = self.scene.create_node("generator.constant", QPointF(30, 250), record_undo=False)
        material_output = self.scene.create_node(self.MATERIAL_NODE_TYPE, QPointF(300, -80), record_undo=False)
        texture_set_output = self.scene.create_node(self.TEXTURE_SET_NODE_TYPE, QPointF(620, 15), record_undo=False)

        noise.parameters.update({
            "scale": 2.5, "octaves": 4, "lacunarity": 2.0, "gain": 0.48,
            "contrast": 0.92, "balance": -0.08, "disorder": 0.08,
            "ridge_sharpness": 2.0, "valley_width": 0.38,
        })
        preblur.parameters.update({"radius": 2.0, "tile": True})
        levels.parameters.update({
            "in_low": 0.08, "in_high": 0.92, "in_mid": 0.50,
            "out_low": 0.0, "out_high": 1.0, "intermediary_clamp": True,
        })
        gradient.parameters["stops"] = [
            {"position": 0.0, "color": "#18212aff"},
            {"position": 0.30, "color": "#59643fff"},
            {"position": 0.62, "color": "#8a7458ff"},
            {"position": 0.84, "color": "#a69678ff"},
            {"position": 1.0, "color": "#d8d2c5ff"},
        ]
        normal.parameters["strength"] = 4.0
        roughness.parameters["value"] = 0.72
        metallic.parameters["value"] = 0.0
        specular.parameters["value"] = 0.0
        material_output.parameters.update({
            "normal_strength": 1.2,
        })
        texture_set_output.parameters.update({
            "name": "Material",
        })

        self.scene.add_connection(noise.output_port, preblur.input_ports["Image"], record_undo=False)
        self.scene.add_connection(preblur.output_port, levels.input_ports["Image"], record_undo=False)
        self.scene.add_connection(levels.output_port, gradient.input_ports["Image"], record_undo=False)
        self.scene.add_connection(gradient.output_port, material_output.input_ports["Base Colour"], record_undo=False)
        self.scene.add_connection(levels.output_port, material_output.input_ports["Height"], record_undo=False)
        self.scene.add_connection(levels.output_port, normal.input_ports["Height"], record_undo=False)
        self.scene.add_connection(normal.output_port, material_output.input_ports["Normal"], record_undo=False)
        self.scene.add_connection(roughness.output_port, material_output.input_ports["Roughness"], record_undo=False)
        self.scene.add_connection(metallic.output_port, material_output.input_ports["Metallic"], record_undo=False)
        self.scene.add_connection(specular.output_port, material_output.input_ports["Specular Level"], record_undo=False)
        self.scene.add_connection(material_output.output_ports["Material"], texture_set_output.input_ports["Material"], record_undo=False)

        # Compact scalar defaults belong visually to the Material inputs they
        # serve. They remain ordinary selectable/editable graph nodes and can
        # be undocked with D at any time.
        for constant in (metallic, roughness, specular):
            constant.set_docked(material_output.uid, undocked_position=constant.pos())
        self.scene._refresh_docked_layout()

        self.scene.set_active_node(material_output)
        noise.setSelected(True)
        QTimer.singleShot(0, self._frame_all_nodes)
        self._loading = False
        self.current_path = None
        self.scene.undo_stack.clear()
        self.scene.undo_stack.setClean()
        self._document_dirty = False
        self._recovered_dirty = False
        self._set_dirty(False)
        self._schedule_preview()

    def _undo_clean_changed(self, clean: bool) -> None:
        del clean
        self._update_dirty_state()

    def _graph_changed(self) -> None:
        change_hint = (
            self.scene.consume_graph_change_hint()
            if hasattr(self.scene, "consume_graph_change_hint")
            else None
        )
        self._invalidate_flipbook_decode_cache()
        self._sync_preview_gizmo(getattr(self.scene, "active_node", None))
        # Geometry previews run on their own cancellable worker. Rapid graph
        # edits are collapsed into the newest mesh request instead of blocking
        # Qt or queuing every intermediate slider value.
        active_node = self.scene.active_node
        if self._is_geometry_preview_node(active_node):
            # Editing settings on a completed manual node does not change the
            # currently published mesh. In particular, Best Packing used to
            # schedule a needless persisted-result decode/UV presentation pass
            # on the UI cadence, causing a visible hitch for dense unwraps.
            # Keep the existing 2D/3D result untouched until the action button
            # is pressed; the Inspector updates its Out of Date state in place.
            if (
                change_hint is not None
                and change_hint == ("manual-settings-only", str(active_node.uid))
            ):
                self._schedule_autosave()
                return
            # Manual-action nodes deliberately keep executing from the snapshot
            # captured when their Inspector button was pressed. Edits made while
            # they run only mark the eventual result stale; they must not cancel
            # and restart the expensive operation automatically.
            if (
                active_node.definition.manual_action_label
                and str(active_node.parameters.get("_manual_status", "")) == "Running"
            ):
                self._schedule_thumbnail_refresh()
                self._schedule_autosave()
                return
            self.material_controller.cancel()
            self._material_preview_in_flight = False
            self._material_preview_pending = False
            self._pending_material_request_key = None
            self._clear_material_node_activity()
            self._schedule_geometry_preview(active_node)
            self._schedule_thumbnail_refresh()
            self._schedule_autosave()
            return

        # The 3D material preview is demand-driven, exactly like the ordinary
        # 2D node preview. Upstream graph edits only propagate through the
        # active Material branch while it remains the active focus.
        active_material = self._find_3d_output()
        if active_material is not None:
            self._refresh_material_geometry_override(active_material)
            self.preview_3d_panel.set_active_output(
                True, str(active_material.parameters.get("name", active_material.definition.name))
            )
            current_key = self._current_material_request_key()
            if (
                self._material_preview_in_flight
                and self._pending_material_request_key is not None
                and current_key != self._pending_material_request_key
            ):
                if self._playing:
                    self._reset_material_playback_stream(reset_quality=False)
                self.material_controller.cancel()
                self._material_preview_in_flight = False
                self._pending_material_request_key = None
                self._pending_material_playback_serial = -1
                self._clear_material_node_activity()
                self.preview_3d_panel.set_busy(False)
            self._schedule_3d_preview()
        elif self.scene.active_node is not None and self.scene.active_node.definition.type_id in {"graph.send", "graph.receive"}:
            self.preview_3d_panel.set_active_output(False)
        self._schedule_preview()
        self._schedule_thumbnail_refresh()
        self._schedule_autosave()

    def _active_node_changed(self, node) -> None:
        pending = getattr(self, "_pending_geometry_request", None) or {}
        pending_uid = str(pending.get("node_uid", "") or "")
        new_uid = str(getattr(node, "uid", "") or "")
        if pending_uid and pending_uid != new_uid:
            previous = self.scene.nodes.get(pending_uid)
            if (
                previous is not None
                and previous.definition.manual_action_label
                and str(previous.parameters.get("_manual_status", "")) == "Running"
            ):
                requested = int(previous.parameters.get("_manual_run_serial", 0) or 0)
                previous.parameters["_manual_completed_serial"] = requested
                previous.parameters["_manual_status"] = "Cancelled"
                previous.parameters["_manual_changed_during_run"] = False
                previous.parameters["_manual_last_error"] = ""
                self._mark_document_dirty()
        self._invalidate_flipbook_decode_cache()
        self._sync_preview_gizmo(node)
        focused_material = self._resolve_material_node(node) if self._is_material_preview_node(node) else None
        focused_material_uid = focused_material.uid if focused_material is not None else None
        if getattr(self, "_playing", False) and focused_material_uid != self._material_playback_focus_uid:
            self._reset_material_playback_stream(reset_quality=focused_material_uid is not None)
            self._material_playback_focus_uid = focused_material_uid
        if not self._is_material_preview_node(node):
            preempt = getattr(self, "_preempt_material_preview_for_2d", None)
            if callable(preempt):
                label = node.definition.name if node is not None else "no node"
                preempt(f"Switching 2D preview to {label}")
            self._material_preview_pending = False
            self.preview_3d_panel.set_active_output(False)
        # Switching the locked 2D preview is an explicit user request. Supersede
        # the old heavy render immediately instead of making the user wait for
        # a Single Image Output or erosion branch they are no longer inspecting.
        if hasattr(self, "preview_timer"):
            self.preview_timer.stop()
        if self._preview_in_flight:
            self.eval_controller.cancel()
        inspector = getattr(self, "evaluation_inspector", None)
        if inspector is not None:
            inspector.cancel_job()
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        self._preview_in_flight = False
        self._preview_pending = False
        self._playback_preview_pending = False

        if self._is_geometry_preview_node(node):
            self.material_controller.cancel()
            self._material_preview_in_flight = False
            self._material_preview_pending = False
            self._pending_material_request_key = None
            self._clear_material_node_activity()
            self.preview_3d_panel.set_active_output(
                True, str(node.parameters.get("name", node.definition.name))
            )
            self._schedule_geometry_preview(node, immediate=True)
            return

        # Leaving a geometry focus restores the project's ordinary preview mesh.
        # Material focus may immediately replace it again from its optional
        # Geometry input below.
        if hasattr(self, "geometry_preview_timer"):
            self.geometry_preview_timer.stop()
        if hasattr(self, "geometry_controller"):
            self.geometry_controller.cancel()
        self._geometry_preview_in_flight = False
        self._pending_geometry_request = None
        self._pending_geometry_node_uid = None
        self._clear_geometry_node_activity()
        self.preview_3d_panel.clear_geometry_override()

        cached_decode_playback = False
        if getattr(self, "_playing", False):
            cached_decode_playback = self._refresh_flipbook_decode_playback_mode()
            self._restart_playback_clock()
            self._invalidate_playback_buffer(
                rebuild=(
                    node is not None
                    and not self._is_material_preview_node(node)
                    and not cached_decode_playback
                )
            )

        if node is None:
            self.preview_panel.set_result(None, None, None, 0, 0, self.document.working_precision)
            return
        material_node = self._resolve_material_node(node) if self._is_material_preview_node(node) else None
        if material_node is not None:
            if (
                material_node.definition.type_id == self.MATERIAL_NODE_TYPE
                and material_node.uid not in self._legacy_3d_viewport_nodes
            ):
                if self.preview_3d_panel.adopt_legacy_output_settings(material_node.parameters):
                    self._mark_document_dirty()
                self._legacy_3d_viewport_nodes.add(material_node.uid)
            self._refresh_material_geometry_override(material_node)
            self.preview_3d_panel.set_active_output(
                True, str(material_node.parameters.get("name", material_node.definition.name))
            )
            self.preview_panel.set_busy(True, f"Switching preview to {material_node.definition.name} base colour…")
            self._schedule_3d_preview(immediate=True)
            if getattr(self, "_playing", False):
                if cached_decode_playback:
                    self._request_playback_preview()
                else:
                    self._queue_playback_prefetch()
            else:
                self._preview_pending = True
                self._arm_preview_dispatch(force_immediate=True)
            return
        if self._is_material_preview_node(node):
            self._material_preview_pending = False
            self.preview_3d_panel.set_active_output(False)
            self.preview_3d_panel.clear_output()
        self.preview_panel.set_busy(True, f"Switching preview to {node.definition.name}…")
        if getattr(self, "_playing", False):
            if cached_decode_playback:
                self._request_playback_preview()
            else:
                self._queue_playback_prefetch()
            return
        self._preview_pending = True
        self._arm_preview_dispatch(force_immediate=True)

    def _selected_item_changed(self, item) -> None:
        # Selection changes the contextual Inspector only. Evaluation still
        # follows the graph's active-node contract and starts on double-click.
        if item is None:
            session = self._active_graph_session()
            if session is not None:
                self._inspect_graph_session(session.uid)
            else:
                self.parameters_panel.set_item(None)
            return
        self.parameters_panel.set_item(item)

    def _inspect_active_graph(self) -> None:
        session = self._active_graph_session()
        if session is not None:
            self._inspect_graph_session(session.uid)

    def _explorer_activate_graph_session(self, session_uid: str) -> None:
        if not self.activate_graph_session(session_uid):
            return
        # Opening a graph is itself an Inspector target. Clear stale node
        # selection so the next node click reliably restores node parameters.
        self.scene.clearSelection()
        self._inspect_graph_session(session_uid)

    def _show_3d_viewport_settings(self) -> None:
        # Treat the viewport as an inspector target without inventing a graph
        # node. Clearing selection guarantees the next node click restores its
        # ordinary Parameters page, even when it had been selected beforehand.
        self.scene.clearSelection()
        self.parameters_dock.show()
        self.parameters_dock.raise_()
        self.parameters_panel.show_external_widget(
            "3D Viewport Settings",
            "These mesh, camera, lighting, display and quality settings are saved with the current graph file.",
            self.preview_3d_panel.settings_widget(),
            release_callback=self.preview_3d_panel.park_settings_widget,
        )

    @staticmethod
    def _graph_instance_output(
        node, kind: str | None = None, *, port_name: str | None = None
    ) -> dict | None:
        if node is None or node.definition.type_id != GRAPH_INSTANCE_TYPE:
            return None
        interface = node.parameters.get("_asset_interface", {})
        outputs = [entry for entry in interface.get("outputs", ()) if isinstance(entry, dict)]
        if port_name is not None:
            outputs = [entry for entry in outputs if str(entry.get("port", "")) == str(port_name)]
        if kind is not None:
            outputs = [entry for entry in outputs if str(entry.get("kind", "")) == str(kind)]
        if not outputs:
            return None
        return next((entry for entry in outputs if bool(entry.get("primary_preview", False))), outputs[0])

    def _active_output_name(self, node) -> str | None:
        if node is not None and node is self.scene.active_node:
            return getattr(self.scene, "active_output_name", None)
        return None

    def _is_material_preview_node(self, node) -> bool:
        if node is None:
            return False
        scene = getattr(self, "scene", None)
        explicit_output = (
            getattr(scene, "active_output_name", None)
            if scene is not None and node is getattr(scene, "active_node", None)
            else None
        )
        if explicit_output is not None:
            return node.output_data_kind(explicit_output) == "material"
        material_types = set(getattr(self, "MATERIAL_NODE_TYPES", (getattr(self, "MATERIAL_NODE_TYPE", "material.pbr"),)))
        return bool(
            node.definition.type_id in material_types | {self.TEXTURE_SET_NODE_TYPE}
            or (node.definition.type_id == GRAPH_INSTANCE_TYPE and self._graph_instance_output(node, "material") is not None)
            or (node.definition.type_id == "graph.output" and self._resolve_material_node(node) is not None)
            or (
                node.definition.type_id in {"graph.send", "graph.receive"}
                and str(getattr(node, "portal_kind", node.parameters.get("_portal_kind", ""))) == "material"
            )
        )

    def _is_geometry_preview_node(self, node) -> bool:
        if node is None:
            return False
        explicit_output = self._active_output_name(node)
        if explicit_output is not None:
            return node.output_data_kind(explicit_output) == "geometry"
        if node.definition.type_id == "output.geometry":
            return True
        if node.definition.type_id == GRAPH_INSTANCE_TYPE:
            return self._graph_instance_output(node, "geometry") is not None
        if node.definition.type_id == "graph.output":
            connection = self.scene.connection_for_input(node.uid, "Value")
            return bool(connection is not None and not connection.broken and connection.source_port.kind == "geometry")
        if node.definition.type_id in {"graph.send", "graph.receive"}:
            return str(getattr(node, "portal_kind", node.parameters.get("_portal_kind", ""))) == "geometry"
        return any(node.output_data_kind(name) == "geometry" for name in node.definition.output_names)

    @staticmethod
    def _mesh_from_geometry(geometry, *, cache_key: str = "") -> MeshData:
        mesh_cache_key = (
            f"{cache_key}:uv={geometry.uv_origin}"
            if cache_key
            else f"uv={geometry.uv_origin}"
        )
        return MeshData(
            geometry.vertices, geometry.indices, geometry.name, mesh_cache_key,
            uv_origin=geometry.uv_origin,
        )

    @staticmethod
    def _snapshot_geometry_branch_dynamic(snapshot: GraphSnapshot, source_uid: str) -> bool:
        """Return whether geometry content can vary with timeline/state.

        Presentation-only inputs (for example the UV node's checker texture) are
        deliberately excluded. They may refresh the 2D presentation, but they
        must never make the mesh itself frame-dependent or invalidate its GPU
        buffers.
        """
        visited: set[str] = set()
        stack = [str(source_uid)]
        while stack:
            uid = stack.pop()
            if uid in visited:
                continue
            visited.add(uid)
            node = snapshot.nodes.get(uid)
            if node is None:
                continue
            if (
                node.definition.uses_time
                or node.definition.is_stateful
                or (node.definition.gpu_spec is not None and node.definition.gpu_spec.uses_time)
            ):
                return True
            presentation_inputs = set(node.definition.presentation_only_inputs)
            for input_name in node.input_names:
                if input_name in presentation_inputs:
                    continue
                source = snapshot.inputs.get((uid, input_name))
                if source is not None:
                    stack.append(str(source[0]))
        return False

    @staticmethod
    def _snapshot_geometry_branch_uses_images(snapshot: GraphSnapshot, source_uid: str) -> bool:
        """Return whether image data changes the actual geometry content."""
        visited: set[str] = set()
        stack = [str(source_uid)]
        while stack:
            uid = stack.pop()
            if uid in visited:
                continue
            visited.add(uid)
            node = snapshot.nodes.get(uid)
            if node is None:
                continue
            presentation_inputs = set(node.definition.presentation_only_inputs)
            for input_name in node.input_names:
                if input_name in presentation_inputs:
                    continue
                source = snapshot.inputs.get((uid, input_name))
                if source is None:
                    continue
                input_kind = normalise_port_kind(node.definition.input_kind(input_name))
                if is_image_kind(input_kind):
                    return True
                stack.append(str(source[0]))
        return False

    def _geometry_content_revision(self, snapshot: GraphSnapshot, source_uid: str) -> str:
        """Hash geometry content while excluding root presentation-only inputs."""
        uid = str(source_uid)
        node = snapshot.nodes.get(uid)
        if node is None:
            return self.evaluator.branch_revision(snapshot, uid)
        content_inputs = {
            key: value
            for key, value in snapshot.inputs.items()
            if not (
                snapshot.nodes.get(str(key[0])) is not None
                and str(key[1]) in snapshot.nodes[str(key[0])].definition.presentation_only_inputs
            )
        }
        if len(content_inputs) == len(snapshot.inputs):
            return self.evaluator.branch_revision(snapshot, uid)
        return self.evaluator.branch_revision(GraphSnapshot(snapshot.nodes, content_inputs), uid)

    def _geometry_presentation_revision(
        self, snapshot: GraphSnapshot, source_uid: str
    ) -> tuple[str | None, bool, bool]:
        """Return revision/dynamic/present state for root presentation inputs."""
        uid = str(source_uid)
        node = snapshot.nodes.get(uid)
        if node is None or not node.definition.presentation_only_inputs:
            return None, False, False
        entries: list[tuple[str, str, str, str]] = []
        dynamic = False
        for input_name in node.definition.presentation_only_inputs:
            source = snapshot.inputs.get((uid, input_name))
            if source is None:
                continue
            source_uid_value, source_output = str(source[0]), str(source[1])
            entries.append((
                str(input_name),
                source_uid_value,
                source_output,
                self.evaluator.branch_revision(snapshot, source_uid_value),
            ))
            dynamic = dynamic or self._snapshot_geometry_branch_dynamic(snapshot, source_uid_value)
        if not entries:
            return None, False, False
        encoded = json.dumps(entries, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.blake2b(encoded, digest_size=20).hexdigest(), dynamic, True

    @staticmethod
    def _geometry_mesh_cache_key(
        *,
        revision: str,
        source_uid: str,
        output_name: str,
        session: GeometryEvaluationSession,
        image_dependent: bool,
        dynamic: bool,
    ) -> str:
        """Stable renderer identity for mesh content, independent of UV overlays."""
        animation = session.animation
        payload = {
            "revision": str(revision),
            "source_uid": str(source_uid),
            "output": str(output_name or "Geometry"),
            "width": int(session.width) if image_dependent else None,
            "height": int(session.height) if image_dependent else None,
            "precision": str(session.precision) if image_dependent else None,
            "colour_space": str(session.colour_space) if image_dependent else None,
            "render_mode": str(session.render_mode) if image_dependent else None,
            "frame": int(animation.get("frame_number", 0)) if dynamic else None,
            "frame_position": (
                round(float(animation.get("frame_position", 0.0)), 6) if dynamic else None
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return "geometry-mesh:" + hashlib.blake2b(encoded, digest_size=20).hexdigest()

    def _geometry_cache_key(
        self,
        snapshot: GraphSnapshot,
        source_uid: str,
        output_name: str,
        session: GeometryEvaluationSession,
    ) -> tuple[str, str, bool, str, str]:
        revision = self._geometry_content_revision(snapshot, source_uid)
        content_dynamic = self._snapshot_geometry_branch_dynamic(snapshot, source_uid)
        image_dependent = self._snapshot_geometry_branch_uses_images(snapshot, source_uid)
        final = str(session.render_mode).startswith("final")
        presentation_revision, presentation_dynamic, presentation_connected = (
            (None, False, False)
            if final
            else self._geometry_presentation_revision(snapshot, source_uid)
        )
        dynamic = content_dynamic or presentation_dynamic
        node = snapshot.nodes.get(str(source_uid))
        manual_request = None
        if node is not None and node.definition.manual_action_label:
            requested = int(node.parameters.get("_manual_run_serial", 0) or 0)
            completed = int(node.parameters.get("_manual_completed_serial", 0) or 0)
            if requested > completed:
                # Manual settings do not alter the published output revision,
                # but a fresh request must bypass any cache holding the previous
                # result so the action actually executes.
                manual_request = (requested, completed)
        uv_preview = bool(
            not final
            and node is not None
            and node.definition.type_id.startswith("geometry.uv_")
        )
        bake_preview = bool(
            not final
            and node is not None
            and node.definition.type_id == "geometry.bake_high_to_low"
        )
        selected_bake_map = (
            str(node.parameters.get("preview_output", "Albedo")) if bake_preview else None
        )
        presentation_context = presentation_connected or uv_preview or bake_preview
        animation = session.animation
        payload = {
            "revision": revision,
            "manual_request": manual_request,
            "presentation_revision": presentation_revision,
            "source_uid": str(source_uid),
            "output": str(output_name or "Geometry"),
            # Pure geometry remains resolution/colour-space independent. Image-
            # backed deformation and 2D UV presentation retain the fields they
            # genuinely use.
            "width": int(session.width) if image_dependent or presentation_context else None,
            "height": int(session.height) if image_dependent or presentation_context else None,
            "precision": str(session.precision) if image_dependent or presentation_connected else None,
            "colour_space": str(session.colour_space) if image_dependent or presentation_connected else None,
            "render_mode": str(session.render_mode) if image_dependent or presentation_context else None,
            "frame": int(animation.get("frame_number", 0)) if dynamic else None,
            "frame_position": (
                round(float(animation.get("frame_position", 0.0)), 6) if dynamic else None
            ),
            "geometry_preview_options": dict(session.preview_options) if uv_preview else None,
            "bake_preview_output": selected_bake_map,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        key = "geometry:" + hashlib.blake2b(encoded, digest_size=20).hexdigest()
        presentation_payload = {
            "presentation_revision": presentation_revision,
            "width": int(session.width) if presentation_context else None,
            "height": int(session.height) if presentation_context else None,
            "precision": str(session.precision) if presentation_connected else None,
            "colour_space": str(session.colour_space) if presentation_connected else None,
            "render_mode": str(session.render_mode) if presentation_context else None,
            "frame": int(animation.get("frame_number", 0)) if presentation_dynamic else None,
            "frame_position": (
                round(float(animation.get("frame_position", 0.0)), 6)
                if presentation_dynamic else None
            ),
            "geometry_preview_options": dict(session.preview_options) if uv_preview else None,
            "bake_preview_output": selected_bake_map,
        }
        presentation_encoded = json.dumps(
            presentation_payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        presentation_token = hashlib.blake2b(presentation_encoded, digest_size=16).hexdigest()
        mesh_key = self._geometry_mesh_cache_key(
            revision=revision,
            source_uid=source_uid,
            output_name=output_name,
            session=session,
            image_dependent=image_dependent,
            dynamic=content_dynamic,
        )
        return key, revision, dynamic, mesh_key, presentation_token

    def _cached_geometry_mesh(
        self,
        snapshot: GraphSnapshot,
        source_uid: str,
        output_name: str = "Geometry",
        *,
        final: bool = False,
    ) -> tuple[MeshData | None, str | None, str | None, bool]:
        session = self._geometry_evaluation_session(snapshot, final=final)
        cache_key, revision, dynamic, mesh_cache_key, _presentation_token = self._geometry_cache_key(
            snapshot, source_uid, output_name, session
        )
        cached = self._geometry_result_cache.get(cache_key)
        if cached is not None:
            return cached.mesh, revision, None, True
        result = session.evaluate(source_uid, output_name)
        if result.error or result.geometry is None:
            return None, revision, result.error or "No geometry was produced", False
        mesh = self._mesh_from_geometry(result.geometry, cache_key=mesh_cache_key)
        self._geometry_result_cache.put(
            cache_key,
            CachedGeometryMesh(
                result.geometry, mesh, revision, dynamic,
                node_metadata=getattr(result, "node_metadata", {}) or {},
                preview_image=getattr(result, "preview_image", None),
                preview_material_texture=getattr(result, "preview_material_texture", None),
                preview_material_textures=getattr(result, "preview_material_textures", {}) or {},
                preview_details=str(getattr(result, "preview_details", "") or ""),
                preview_kind=str(getattr(result, "preview_kind", "") or ""),
            ),
        )
        return mesh, revision, None, False

    def _geometry_evaluation_session(
        self, snapshot: GraphSnapshot, *, final: bool = False
    ) -> GeometryEvaluationSession:
        if final:
            width, height = int(self.document.width), int(self.document.height)
            render_mode = "final"
        else:
            width, height = self.document.preview_size()
            render_mode = "interactive" if self._playing else "preview_3d"
            if self._playing and max(width, height) > 256:
                scale = 256.0 / max(width, height)
                width = max(1, round(width * scale))
                height = max(1, round(height * scale))
        return GeometryEvaluationSession(
            self.evaluator,
            snapshot,
            width,
            height,
            precision=self.document.texture_precision,
            colour_space=self.document.colour_space,
            render_mode=render_mode,
            preview_options=(
                self.preview_panel.uv_preview_options()
                if not final and hasattr(self, "preview_panel")
                else {}
            ),
            **self._animation_context(),
        )

    def _evaluate_geometry_node(self, node, snapshot: GraphSnapshot | None = None):
        if node is None:
            return None, "No geometry node is active"
        graph = snapshot or GraphSnapshot.from_scene(self.scene)
        output_name = self._active_output_name(node)
        if not output_name:
            if node.definition.type_id == "output.geometry":
                output_name = "Geometry"
            elif node.definition.type_id == GRAPH_INSTANCE_TYPE:
                public = self._graph_instance_output(node, "geometry")
                output_name = str(public.get("port", "")) if public is not None else "Geometry"
            else:
                output_name = next(
                    (name for name in node.definition.output_names if node.output_data_kind(name) == "geometry"),
                    "Geometry",
                )
        mesh, _revision, error, _cache_hit = self._cached_geometry_mesh(
            graph, node.uid, output_name
        )
        if mesh is None:
            return None, error or "No geometry was produced"
        return mesh, None

    def _clear_geometry_node_activity(self) -> None:
        activity = getattr(self, "_geometry_node_activity", None)
        if activity:
            for uid in tuple(activity):
                self.scene.set_node_evaluation_state(uid, False)
            activity.clear()

    def _geometry_output_for_node(self, node) -> str:
        output_name = self._active_output_name(node)
        if output_name:
            return str(output_name)
        if node.definition.type_id == "output.geometry":
            return "Geometry"
        if node.definition.type_id == GRAPH_INSTANCE_TYPE:
            public = self._graph_instance_output(node, "geometry")
            return str(public.get("port", "Geometry")) if public is not None else "Geometry"
        return next(
            (name for name in node.definition.output_names if node.output_data_kind(name) == "geometry"),
            "Geometry",
        )

    def _schedule_geometry_preview(self, node=None, *, immediate: bool = False) -> None:
        if not hasattr(self, "geometry_preview_timer"):
            return
        node = node or getattr(self.scene, "active_node", None)
        if not self._is_geometry_preview_node(node):
            return
        self._pending_geometry_node_uid = str(node.uid)
        # A native call already executing in its worker cannot always stop in
        # the middle of the C++ collapse loop, but its result is invalidated
        # immediately and never presented. The debounce below prevents a queue
        # of obsolete requests during slider drags.
        if self._geometry_preview_in_flight:
            self.geometry_controller.cancel()
            self._geometry_preview_in_flight = False
            self._pending_geometry_request = None
            self._clear_geometry_node_activity()
            self.evaluation_inspector.cancel_job()
        self.geometry_preview_timer.stop()
        delay = 0 if immediate else int(self._geometry_preview_debounce_ms)
        self.geometry_preview_timer.start(delay)

    def _dispatch_pending_geometry_preview(self) -> None:
        uid = self._pending_geometry_node_uid
        self._pending_geometry_node_uid = None
        node = self.scene.nodes.get(uid) if uid else None
        if node is None or node is not self.scene.active_node or not self._is_geometry_preview_node(node):
            return
        self._show_geometry_node(node)

    def _show_geometry_node(self, node) -> bool:
        if node is None:
            return False
        graph = GraphSnapshot.from_scene(self.scene)
        self._refresh_manual_node_staleness(node, graph)
        output_name = self._geometry_output_for_node(node)
        session = self._geometry_evaluation_session(graph)
        cache_key, revision, dynamic, mesh_cache_key, presentation_token = self._geometry_cache_key(
            graph, node.uid, output_name, session
        )
        cached = self._geometry_result_cache.get(cache_key)
        if cached is not None:
            self.geometry_controller.cancel()
            self._geometry_preview_in_flight = False
            self._pending_geometry_request = None
            self._clear_geometry_node_activity()
            cached_metadata = dict(getattr(cached, "node_metadata", {}) or {})
            node_stats = dict(cached_metadata.get(str(node.uid), {}) or {})
            node_stats.update({
                "_geometry_output_vertex_count": cached.geometry.vertex_count,
                "_geometry_output_triangle_count": cached.geometry.triangle_count,
                "_geometry_output_memory_bytes": int(
                    cached.geometry.vertices.nbytes + cached.geometry.indices.nbytes
                ),
            })
            cached_metadata[str(node.uid)] = node_stats
            self._apply_geometry_node_metadata(cached_metadata)
            node.set_error(None)
            self.preview_3d_panel.set_active_output(
                True, str(node.parameters.get("name", node.definition.name))
            )
            self.preview_3d_panel.show_geometry(
                cached.mesh,
                name=str(node.parameters.get("name", node.definition.name)),
                preview_texture=getattr(cached, "preview_material_texture", None),
                preview_textures=getattr(cached, "preview_material_textures", {}) or {},
                preview_settings={"normal_y": str(node.parameters.get("normal_y", "OpenGL (+Y)"))},
            )
            cached_preview = getattr(cached, "preview_image", None)
            if isinstance(cached_preview, np.ndarray):
                self.preview_panel.set_result(
                    node.definition.name, None, None, cached_preview.shape[1], cached_preview.shape[0],
                    self.document.working_precision,
                    details_override=str(getattr(cached, "preview_details", "") or "UV layout"),
                    data_kind=str(getattr(cached, "preview_kind", "uv") or "uv"),
                    display_rgba=cached_preview,
                )
            else:
                self.preview_panel.set_result(
                    node.definition.name, None, None, 0, 0, self.document.working_precision
                )
            self.statusBar().showMessage(
                f"Geometry cache hit · {node.definition.name}", 2500
            )
            return True

        self.geometry_controller.cancel()
        self._clear_geometry_node_activity()
        self._pending_geometry_request = {
            "node_uid": str(node.uid),
            "output_name": str(output_name),
            "cache_key": cache_key,
            "mesh_cache_key": mesh_cache_key,
            "presentation_token": presentation_token,
            "revision": revision,
            "dynamic": bool(dynamic),
            "scene_id": id(self.scene),
            "session_uid": str(getattr(self, "_active_graph_session_uid", "") or ""),
            "display_name": str(node.parameters.get("name", node.definition.name)),
        }
        self._geometry_preview_in_flight = True
        self.preview_3d_panel.set_active_output(True, self._pending_geometry_request["display_name"])
        self.geometry_controller.request(session, node.uid, output_name)
        return True

    def _geometry_preview_started(self) -> None:
        request = self._pending_geometry_request or {}
        node = self.scene.nodes.get(str(request.get("node_uid", "")))
        target = str(request.get("display_name", "Geometry"))
        job_id = self._next_evaluation_job("geometry")
        self.evaluation_inspector.begin_job(
            job_id, "Evaluating geometry", target, 0, 0, "Background · latest edit wins"
        )
        self._clear_geometry_node_activity()
        if node is not None:
            detail = f"{node.definition.name} — preparing geometry…"
            self._geometry_node_activity[node.uid] = detail
            self.scene.set_node_evaluation_state(node.uid, True, 0, 0, detail)
        self.preview_3d_panel.set_busy(True, "Evaluating geometry in the background…")
        if node is not None and node.definition.type_id == "geometry.uv_unwrap":
            self.preview_panel.set_busy(True, "Preparing UV layout…")
        elif node is not None and node.definition.type_id == "geometry.bake_high_to_low":
            self.preview_panel.set_busy(True, "Baking high-to-low maps…")

    def _geometry_preview_progress(self, current: int, target: int, message: str) -> None:
        detail = str(message or "Processing geometry…")
        if target > 0:
            detail = f"{detail} — {current} of {target}"
        self.preview_3d_panel.set_busy(True, detail)
        self.statusBar().showMessage(detail)

    def _geometry_node_state(
        self, node_uid: str, active: bool, current: int, target: int, message: str
    ) -> None:
        self.scene.set_node_evaluation_state(node_uid, active, current, target, message)
        node = self.scene.nodes.get(node_uid)
        name = node.definition.name if node is not None else "Geometry stage"
        self.evaluation_inspector.update_node(
            self._evaluation_job_id, node_uid, name, active, current, target, message
        )
        activity = self._geometry_node_activity
        if active:
            detail = str(message or f"Evaluating {name}…")
            if target > 0 and " of " not in detail:
                detail = f"{detail} — {current} of {target}"
            activity.pop(node_uid, None)
            activity[node_uid] = detail
            self.preview_3d_panel.set_busy(True, detail)
            self.statusBar().showMessage(detail)
            return
        activity.pop(node_uid, None)
        if activity:
            self.preview_3d_panel.set_busy(True, next(reversed(activity.values())))
        elif self._geometry_preview_in_flight:
            self.preview_3d_panel.set_busy(True, "Geometry — uploading mesh to the renderer…")

    def _manual_geometry_input_revision(self, node, snapshot: GraphSnapshot | None = None) -> str:
        """Hash every authored input to a manual operation, not just a port named Geometry."""
        if node is None:
            return ""
        graph = snapshot or GraphSnapshot.from_scene(self.scene)
        entries: list[tuple[str, str, str, str]] = []
        try:
            for input_name in node.definition.inputs:
                if input_name in node.definition.presentation_only_inputs:
                    continue
                source = graph.inputs.get((str(node.uid), str(input_name)))
                if source is None:
                    entries.append((str(input_name), "", "", "disconnected"))
                    continue
                source_uid, source_output = str(source[0]), str(source[1] or "")
                entries.append((
                    str(input_name), source_uid, source_output,
                    str(self.evaluator.branch_revision(graph, source_uid)),
                ))
            if not entries:
                return ""
            encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return hashlib.blake2b(encoded, digest_size=20).hexdigest()
        except Exception:
            return ""

    def _refresh_manual_node_staleness(
        self, node, snapshot: GraphSnapshot | None = None
    ) -> bool:
        """Synchronise manual status without evaluating or replacing its result."""
        if (
            node is None
            or not node.definition.manual_action_label
            or not node.parameters.get("_manual_result_data")
            or str(node.parameters.get("_manual_status", "")) in {"Running", "Cancelling"}
        ):
            return False
        graph = snapshot or GraphSnapshot.from_scene(self.scene)
        applied = node.parameters.get("_manual_applied_parameters", {})
        settings_changed = bool(
            isinstance(applied, dict)
            and any(
                node.parameters.get(name) != applied.get(name)
                for name in node.definition.manual_action_relevant_parameters
            )
        )
        stored_input = str(node.parameters.get("_manual_input_revision", "") or "")
        current_input = self._manual_geometry_input_revision(node, graph)
        input_changed = bool(stored_input and current_input != stored_input)
        desired = "Out of Date" if settings_changed or input_changed else "Up to Date"
        current = str(node.parameters.get("_manual_status", "") or "")
        # Preserve an explicit failure/cancellation explanation until the artist
        # edits or reruns. Its previous result is still valid, but the status is
        # more useful than silently turning green again.
        if current in {"Failed", "Cancelled"} and desired == "Up to Date":
            return False
        if current == desired:
            return False
        node.parameters["_manual_status"] = desired
        if desired == "Out of Date":
            node.parameters["_manual_last_error"] = ""
        self._mark_document_dirty()
        if node is self.scene.active_node:
            QTimer.singleShot(0, lambda n=node: self.parameters_panel.set_item(n))
        return True

    def _apply_geometry_node_metadata(self, metadata: dict[str, dict]) -> None:
        changed_active = False
        manual_metadata_changed = False
        manual_keys = {
            "_manual_status", "_manual_completed_serial", "_manual_signature",
            "_manual_result_data", "_manual_last_error",
            "_manual_applied_parameters", "_manual_changed_during_run",
            "_manual_input_revision", "_manual_result_revision",
        }
        graph_snapshot = None
        for uid, values in (metadata or {}).items():
            node = self.scene.nodes.get(str(uid))
            if node is None or not isinstance(values, dict):
                continue
            old_manual = {key: node.parameters.get(key) for key in manual_keys}
            for key, value in values.items():
                node.parameters[str(key)] = value
            if node.definition.manual_action_label:
                applied = node.parameters.get("_manual_applied_parameters", {})
                changed_during_run = bool(node.parameters.pop("_manual_changed_during_run", False))
                if isinstance(applied, dict) and node.parameters.get("_manual_result_data"):
                    if graph_snapshot is None:
                        graph_snapshot = GraphSnapshot.from_scene(self.scene)
                    current_input_revision = self._manual_geometry_input_revision(node, graph_snapshot)
                    input_changed = (
                        bool(node.parameters.get("_manual_input_revision"))
                        and current_input_revision != str(node.parameters.get("_manual_input_revision", ""))
                    )
                    if changed_during_run or input_changed or any(
                        node.parameters.get(name) != applied.get(name)
                        for name in node.definition.manual_action_relevant_parameters
                    ):
                        node.parameters["_manual_status"] = "Out of Date"
                new_manual = {key: node.parameters.get(key) for key in manual_keys}
                manual_metadata_changed = manual_metadata_changed or new_manual != old_manual
            changed_active = changed_active or node is self.scene.active_node or node.isSelected()
        if manual_metadata_changed:
            self._mark_document_dirty()
        if changed_active and self.scene.active_node is not None:
            QTimer.singleShot(0, lambda: self.parameters_panel.set_item(self.scene.active_node))

    def _geometry_preview_ready(self, result) -> None:
        request = self._pending_geometry_request
        self._geometry_preview_in_flight = False
        self._pending_geometry_request = None
        self._clear_geometry_node_activity()
        if request is None:
            return
        if (
            request.get("scene_id") != id(self.scene)
            or request.get("session_uid") != str(getattr(self, "_active_graph_session_uid", "") or "")
        ):
            self.evaluation_inspector.cancel_job()
            return
        node = self.scene.nodes.get(str(request.get("node_uid", "")))
        if node is None or node is not self.scene.active_node:
            self.evaluation_inspector.cancel_job()
            return
        self._apply_geometry_node_metadata(getattr(result, "node_metadata", {}) or {})
        error = getattr(result, "error", None)
        geometry = getattr(result, "geometry", None)
        if error or geometry is None:
            message = str(error or "No geometry was produced")
            if node.definition.manual_action_label:
                requested = int(node.parameters.get("_manual_run_serial", 0) or 0)
                node.parameters["_manual_completed_serial"] = requested
                node.parameters["_manual_status"] = "Failed"
                node.parameters["_manual_last_error"] = message
                node.parameters["_manual_changed_during_run"] = False
                self._mark_document_dirty()
                self.parameters_panel.set_item(node)
            node.set_error(message)
            self.preview_3d_panel.clear_geometry_override()
            self.preview_3d_panel.set_active_output(True, node.definition.name)
            self.preview_3d_panel.set_error(message)
            self.evaluation_inspector.fail_job(self._evaluation_job_id, message)
            self.statusBar().showMessage(message, 5000)
            return
        cache_key = str(request["cache_key"])
        mesh_cache_key = str(request.get("mesh_cache_key", cache_key))
        revision = str(request["revision"])
        dynamic = bool(request["dynamic"])
        presentation_changed = False
        # Manual publication updates the node's persistent result only after the
        # worker succeeds. Recompute the authored-output identity now so the new
        # mesh cannot accidentally reuse the previous result's GPU buffers and
        # the next focus change immediately hits the completed-result cache.
        try:
            current_graph = GraphSnapshot.from_scene(self.scene)
            current_session = self._geometry_evaluation_session(current_graph)
            (
                current_cache_key,
                current_revision,
                current_dynamic,
                current_mesh_cache_key,
                current_presentation_token,
            ) = self._geometry_cache_key(
                current_graph, node.uid, str(request.get("output_name", "Geometry")), current_session
            )
            mesh_cache_key = current_mesh_cache_key
            revision = current_revision
            dynamic = current_dynamic
            presentation_changed = (
                str(current_presentation_token)
                != str(request.get("presentation_token", current_presentation_token))
            )
            if not presentation_changed:
                cache_key = current_cache_key
        except Exception:
            # Presentation still succeeds with the request identity; a later
            # focus refresh can rebuild the cache if graph state changed.
            pass
        mesh = self._mesh_from_geometry(geometry, cache_key=mesh_cache_key)
        self._geometry_result_cache.put(
            cache_key,
            CachedGeometryMesh(
                geometry, mesh, revision, dynamic,
                node_metadata=getattr(result, "node_metadata", {}) or {},
                preview_image=getattr(result, "preview_image", None),
                preview_material_texture=getattr(result, "preview_material_texture", None),
                preview_material_textures=getattr(result, "preview_material_textures", {}) or {},
                preview_details=str(getattr(result, "preview_details", "") or ""),
                preview_kind=str(getattr(result, "preview_kind", "") or ""),
            ),
        )
        node.set_error(None)
        self.preview_3d_panel.show_geometry(
            mesh,
            name=str(request["display_name"]),
            preview_texture=getattr(result, "preview_material_texture", None),
            preview_textures=getattr(result, "preview_material_textures", {}) or {},
            preview_settings={"normal_y": str(node.parameters.get("normal_y", "OpenGL (+Y)"))},
        )
        self.preview_3d_panel.set_busy(False)
        preview_image = getattr(result, "preview_image", None)
        if isinstance(preview_image, np.ndarray):
            self.preview_panel.set_result(
                node.definition.name, None, None, preview_image.shape[1], preview_image.shape[0],
                self.document.working_precision,
                details_override=str(getattr(result, "preview_details", "") or "UV layout"),
                data_kind=str(getattr(result, "preview_kind", "uv") or "uv"),
                display_rgba=preview_image,
            )
        else:
            self.preview_panel.set_result(
                node.definition.name, None, None, 0, 0, self.document.working_precision
            )
        self.evaluation_inspector.finish_job(self._evaluation_job_id, result)
        self.statusBar().showMessage(
            f"Geometry ready · {geometry.vertex_count:,} vertices · "
            f"{geometry.triangle_count:,} triangles · {float(getattr(result, 'elapsed_ms', 0.0)):.1f} ms",
            3500,
        )
        if presentation_changed and node is self.scene.active_node:
            # The preview-only texture/options changed while the native job was
            # running. Refresh just the lightweight persisted-result
            # presentation; the unwrap itself will not run again.
            QTimer.singleShot(0, lambda n=node: self._schedule_geometry_preview(n, immediate=True))

    def _run_manual_node_action(self, node_uid: str) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None or not node.definition.manual_action_label:
            return
        if node is not self.scene.active_node:
            self.scene.set_active_node(node)
        node.parameters["_manual_input_revision"] = self._manual_geometry_input_revision(node)
        completed = int(node.parameters.get("_manual_completed_serial", 0) or 0)
        requested = int(node.parameters.get("_manual_run_serial", 0) or 0)
        node.parameters["_manual_run_serial"] = max(completed, requested) + 1
        node.parameters["_manual_status"] = "Running"
        node.parameters["_manual_last_error"] = ""
        node.parameters["_manual_changed_during_run"] = False
        self.scene._touch()
        self.parameters_panel.set_item(node)
        self._schedule_geometry_preview(node, immediate=True)

    def _cancel_manual_node_action(self, node_uid: str) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None or not node.definition.manual_action_label:
            return
        self.geometry_controller.cancel()
        self.geometry_preview_timer.stop()
        self._geometry_preview_in_flight = False
        self._pending_geometry_request = None
        self._pending_geometry_node_uid = None
        self._clear_geometry_node_activity()
        self.evaluation_inspector.cancel_job()
        self.preview_3d_panel.set_busy(False)
        requested = int(node.parameters.get("_manual_run_serial", 0) or 0)
        node.parameters["_manual_completed_serial"] = requested
        node.parameters["_manual_status"] = "Cancelled"
        node.parameters["_manual_last_error"] = ""
        node.parameters["_manual_changed_during_run"] = False
        self._mark_document_dirty()
        self.parameters_panel.set_item(node)
        self.statusBar().showMessage(f"{node.definition.name} cancelled; previous result retained", 3500)

    def _uv_preview_options_changed(self) -> None:
        node = getattr(self.scene, "active_node", None)
        if node is None or not node.definition.type_id.startswith("geometry.uv_"):
            return
        if (
            node.definition.manual_action_label
            and str(node.parameters.get("_manual_status", "")) == "Running"
        ):
            return
        self._schedule_geometry_preview(node, immediate=True)

    def _geometry_preview_failed(self, message: str) -> None:
        request = self._pending_geometry_request
        self._geometry_preview_in_flight = False
        self._pending_geometry_request = None
        self._clear_geometry_node_activity()
        node = None
        if request is not None and request.get("scene_id") == id(self.scene):
            node = self.scene.nodes.get(str(request.get("node_uid", "")))
        if node is not None:
            if node.definition.manual_action_label:
                requested = int(node.parameters.get("_manual_run_serial", 0) or 0)
                node.parameters["_manual_completed_serial"] = requested
                node.parameters["_manual_status"] = "Failed"
                node.parameters["_manual_last_error"] = str(message or "Geometry evaluation failed")
                node.parameters["_manual_changed_during_run"] = False
                self._mark_document_dirty()
                self.parameters_panel.set_item(node)
            node.set_error(str(message or "Geometry evaluation failed"))
        self.preview_3d_panel.clear_geometry_override()
        self.preview_3d_panel.set_active_output(True, node.definition.name if node is not None else "Geometry")
        self.preview_3d_panel.set_error(str(message or "Geometry evaluation failed"))
        self.evaluation_inspector.fail_job(self._evaluation_job_id, str(message))
        self.statusBar().showMessage(str(message or "Geometry evaluation failed"), 5000)

    def _material_geometry_state(
        self,
        material_node,
        snapshot: GraphSnapshot,
        output_port: str = "Material",
    ) -> tuple[MeshData | None, str | None, str | None]:
        if material_node is None:
            return None, None, None
        graph = snapshot
        target_uid = material_node.uid
        target_port = str(output_port or "Material")
        try:
            if material_node.definition.type_id == GRAPH_INSTANCE_TYPE:
                graph, target_uid, target_port = self.evaluator._expand_graph_instances(
                    graph, target_uid, target_port
                )
            reference = material_geometry_reference(graph, target_uid)
            if reference is None:
                return None, None, None
            mesh, revision, error, _cache_hit = self._cached_geometry_mesh(
                graph, reference[0], reference[1]
            )
            if mesh is None:
                return None, revision, error or "Material geometry produced no mesh"
            return mesh, revision, None
        except Exception as exc:
            return None, None, f"{type(exc).__name__}: {exc}"

    def _material_geometry_revision(
        self,
        material_node,
        snapshot: GraphSnapshot,
        output_port: str = "Material",
    ) -> tuple[str | None, str | None]:
        """Resolve only the geometry dependency revision for material request keys.

        Playback must not rebuild the full procedural mesh merely to decide
        whether a texture frame is current. The actual viewport mesh is refreshed
        when geometry focus/structure changes; animation requests only need the
        stable branch revision.
        """
        if material_node is None:
            return None, None
        graph = snapshot
        target_uid = material_node.uid
        target_port = str(output_port or "Material")
        try:
            if material_node.definition.type_id == GRAPH_INSTANCE_TYPE:
                graph, target_uid, target_port = self.evaluator._expand_graph_instances(
                    graph, target_uid, target_port
                )
            reference = material_geometry_reference(graph, target_uid)
            if reference is None:
                return None, None
            return self.evaluator.branch_revision(graph, reference[0]), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def _refresh_material_geometry_override(
        self,
        material_node,
        snapshot: GraphSnapshot | None = None,
        output_port: str = "Material",
    ) -> str | None:
        graph = snapshot or GraphSnapshot.from_scene(self.scene)
        mesh, revision, error = self._material_geometry_state(material_node, graph, output_port)
        if error:
            self.preview_3d_panel.clear_geometry_override()
            self.statusBar().showMessage(f"Material geometry: {error}", 4000)
            return None
        if mesh is None:
            self.preview_3d_panel.clear_geometry_override()
            return None
        self.preview_3d_panel.set_geometry_override(mesh, name=str(material_node.parameters.get("name", material_node.definition.name)))
        return revision

    def _resolve_material_node(self, node, snapshot: GraphSnapshot | None = None):
        if node is None:
            return None

        def source_for(current, input_name: str):
            if snapshot is not None:
                source = snapshot.inputs.get((current.uid, input_name))
                return snapshot.nodes.get(source[0]) if source is not None else None
            connection = self.scene.connection_for_input(current.uid, input_name)
            return connection.source_node if connection is not None and not connection.broken else None

        material_types = set(getattr(self, "MATERIAL_NODE_TYPES", (getattr(self, "MATERIAL_NODE_TYPE", "material.pbr"),)))
        current = node
        if current.definition.type_id == self.TEXTURE_SET_NODE_TYPE:
            current = source_for(current, "Material")

        visited: set[str] = set()
        while current is not None:
            if current.uid in visited:
                return None
            visited.add(current.uid)
            type_id = current.definition.type_id
            if type_id in material_types:
                return current
            if type_id == GRAPH_INSTANCE_TYPE and self._graph_instance_output(current, "material") is not None:
                return current
            if type_id == "graph.output":
                current = source_for(current, "Value")
                continue
            if type_id == "graph.send":
                current = source_for(current, "Input")
                continue
            if type_id == "graph.receive":
                if snapshot is not None:
                    current = source_for(current, "Input")
                else:
                    sender = self.scene.nodes.get(str(current.parameters.get("sender_uid", "")))
                    current = source_for(sender, "Input") if sender is not None else None
                continue
            return None
        return None

    def _find_3d_output(self):
        active = self.scene.active_node
        if active is None:
            return None
        explicit_output = getattr(self.scene, "active_output_name", None)
        if explicit_output is not None and active.output_data_kind(explicit_output) != "material":
            return None
        return self._resolve_material_node(active)

    def _preview_source_for_node(
        self,
        node,
        snapshot: GraphSnapshot | None = None,
    ) -> tuple[str, str, str, str] | None:
        if node is None:
            return None
        explicit_output = (
            getattr(getattr(self, "scene", None), "active_output_name", None)
            if node is getattr(getattr(self, "scene", None), "active_node", None)
            else None
        )
        if explicit_output is not None:
            kind = node.output_data_kind(explicit_output)
            label = node.output_ports.get(explicit_output).display_name if explicit_output in node.output_ports else explicit_output
            if kind == "material":
                material_name = str(label or node.definition.name)
                return (node.uid, explicit_output, f"{material_name} · Base Colour", material_name)
            if kind in {"grayscale", "color", "vector", "scalar"}:
                return (node.uid, explicit_output, str(label or node.definition.name), node.definition.name)
            return None
        if (
            node.definition.type_id == "transform.crop"
            and getattr(getattr(self, "preview_panel", None), "edit_input_enabled", False)
        ):
            if snapshot is None:
                connection = self.scene.connection_for_input(node.uid, "Image")
                if connection is None or connection.broken:
                    return None
                source_uid = connection.source_node.uid
                source_output = connection.output_name
            else:
                source = snapshot.inputs.get((node.uid, "Image"))
                if source is None:
                    return None
                source_uid, source_output = str(source[0]), str(source[1])
            return (
                str(source_uid),
                str(source_output),
                f"{node.definition.name} · Source",
                node.definition.name,
            )
        if self._is_material_preview_node(node):
            material = self._resolve_material_node(node, snapshot)
            if material is None:
                return None
            material_name = str(getattr(material, "parameters", {}).get("name", material.definition.name)) or material.definition.name
            # A Graph Instance names its complete Material output with a stable
            # interface port ID. The evaluator expands that output and then
            # resolves its Base Colour lazily like an ordinary Material node.
            if material.definition.type_id == GRAPH_INSTANCE_TYPE:
                public = self._graph_instance_output(material, "material")
                if public is None:
                    return None
                material_name = str(public.get("name") or material.definition.name)
                return (material.uid, str(public.get("port", "")), f"{material_name} · Base Colour", material_name)
            # Material-producing nodes expose their resolved Base Colour through
            # the evaluator's lazy material-channel path. This also supplies the
            # semantic grey default when a material intentionally has no authored
            # Base Colour map.
            return (material.uid, "Base Colour", f"{material_name} · Base Colour", material_name)
        if node.definition.type_id == GRAPH_INSTANCE_TYPE:
            public = self._graph_instance_output(node)
            if public is None:
                return None
            kind = str(public.get("kind", ""))
            if kind not in {"grayscale", "color", "vector", "scalar"}:
                return None
            name = str(public.get("name") or node.definition.name)
            return (node.uid, str(public.get("port", "")), name, node.definition.name)
        if node.definition.type_id == "graph.send":
            if snapshot is None:
                connection = self.scene.connection_for_input(node.uid, "Input")
                if connection is None or connection.broken:
                    return None
                return (connection.source_node.uid, connection.output_name, node.definition.name, node.definition.name)
            source = snapshot.inputs.get((node.uid, "Input"))
            if source is None:
                return None
            return (str(source[0]), str(source[1]), node.definition.name, node.definition.name)
        for output_name in node.definition.output_names:
            if node.output_data_kind(output_name) in {"grayscale", "color", "vector", "scalar"}:
                return (node.uid, output_name, node.definition.name, node.definition.name)
        return None

    @staticmethod
    def _scaled_document_size(document: DocumentSettings, max_dimension: int) -> tuple[int, int]:
        maximum = max(int(max_dimension), 1)
        scale = maximum / max(document.width, document.height, 1)
        return max(1, round(document.width * scale)), max(1, round(document.height * scale))

    def _material_request_spec(self):
        output = self._find_3d_output()
        if output is None:
            return None
        if output.definition.type_id == GRAPH_INSTANCE_TYPE:
            requested_port = (
                getattr(getattr(self, "scene", None), "active_output_name", None)
                if output is getattr(getattr(self, "scene", None), "active_node", None)
                else None
            )
            public_material = self._graph_instance_output(
                output, "material", port_name=requested_port if requested_port else None
            )
            if public_material is None:
                return None
            output_port = str(public_material.get("port", ""))
        else:
            output_port = "Material"
        texture_resolution = str(self.preview_3d_panel.viewport_setting("texture_resolution"))
        if texture_resolution == "Match 2D Preview":
            texture_max = int(self.document.preview_max_dimension)
        else:
            try:
                texture_max = int(texture_resolution)
            except ValueError:
                texture_max = 512
        # Full-resolution graph readback, CPU mip generation and GPU upload are
        # unsuitable for real-time material animation. Playback uses a bounded
        # live map resolution, then pausing immediately settles the authored
        # viewport resolution again.
        if self._playing:
            texture_max = min(int(texture_max), int(self._material_playback_live_max))
        texture_width, texture_height = self._scaled_document_size(self.document, texture_max)

        # Static inspection can reuse the larger 2D graph cache. Playback avoids
        # that forced high-resolution readback and evaluates directly at the live
        # 3D map size.
        evaluation_max = (
            texture_max
            if self._playing
            else max(int(self.document.preview_max_dimension), texture_max)
        )
        evaluation_width, evaluation_height = self._scaled_document_size(self.document, evaluation_max)
        snapshot = GraphSnapshot.from_scene(self.scene)
        animation = self._animation_context()
        branch_revision = self.evaluator.branch_revision(snapshot, output.uid)
        geometry_revision, geometry_error = self._material_geometry_revision(
            output, snapshot, output_port
        )
        payload = {
            "output": output.uid,
            "output_port": output_port,
            "branch": branch_revision,
            "geometry_branch": geometry_revision or "",
            "geometry_error": geometry_error or "",
            "evaluation": (evaluation_width, evaluation_height),
            "texture": (texture_width, texture_height),
            "precision": self.document.texture_precision.value,
            "colour_space": self.document.colour_space,
            "animation": animation,
        }
        key = hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
            digest_size=20,
        ).hexdigest()
        return (
            output,
            output_port,
            snapshot,
            evaluation_width,
            evaluation_height,
            texture_width,
            texture_height,
            animation,
            key,
        )

    def _current_material_request_key(self) -> str | None:
        spec = self._material_request_spec()
        return None if spec is None else spec[-1]

    def _preview_request_key(
        self,
        snapshot: GraphSnapshot,
        node_uid: str,
        output_name: str,
        width: int,
        height: int,
        display_width: int,
        display_height: int,
        render_mode: str,
    ) -> str:
        payload = {
            "node": str(node_uid),
            "output": str(output_name or "Image"),
            "branch": self.evaluator.branch_revision(snapshot, node_uid),
            "source": (int(width), int(height)),
            # UI chrome, busy labels and dock splitters can change the recommended
            # presentation size by a handful of pixels while the graph result is
            # otherwise identical. Bucket display preparation so those harmless
            # layout changes reuse the completed preview instead of submitting a
            # new GPU readback. A genuinely larger panel still crosses a bucket
            # boundary and requests a sharper presentation image.
            "display": (
                min(int(width), ((max(int(display_width), 1) + 63) // 64) * 64),
                min(int(height), ((max(int(display_height), 1) + 63) // 64) * 64),
            ),
            "precision": self.document.texture_precision.value,
            "colour_space": self.document.colour_space,
            "render_mode": str(render_mode or "preview"),
            "animation": self._animation_context(),
        }
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
            digest_size=20,
        ).hexdigest()

    def _remember_material_metadata(self, key: str, result: MaterialEvaluationResult) -> None:
        metadata = replace(result, textures={}, node_traces=())
        self._material_preview_metadata.pop(key, None)
        self._material_preview_metadata[key] = metadata
        while len(self._material_preview_metadata) > self._material_preview_metadata_limit:
            self._material_preview_metadata.popitem(last=False)

    def _material_metadata(self, key: str) -> MaterialEvaluationResult | None:
        metadata = self._material_preview_metadata.get(key)
        if metadata is None:
            return None
        self._material_preview_metadata.move_to_end(key)
        return metadata

    def _clear_geometry_caches(self) -> None:
        self._geometry_result_cache.clear()
        self.preview_3d_panel.canvas.renderer.clear_geometry_cache()

    def _clear_presentation_caches(self) -> None:
        self._preview_result_cache.clear()
        self._thumbnail_cache.clear()
        self._material_result_cache.clear()
        self._clear_geometry_caches()
        self._material_preview_metadata.clear()
        self._last_material_result_key = None
        self._pending_preview_cache_key = None
        self.preview_3d_panel.clear_material_cache()
        self.material_controller.clear_static_cache()

    def _thumbnail_state_changed(self, node: NodeItem) -> None:
        current = self._thumbnail_current
        if current is not None and current[1] == node.uid and not node.thumbnail_enabled:
            self._preempt_thumbnail_work()
        self._schedule_thumbnail_refresh(immediate=True)

    def _preempt_thumbnail_work(self) -> None:
        timer = getattr(self, "thumbnail_timer", None)
        if timer is not None:
            timer.stop()
        if self._thumbnail_in_flight:
            self.thumbnail_controller.cancel()
            current = self._thumbnail_current
            if current is not None and current[0] == str(self._active_graph_session_uid or ""):
                node = self.scene.nodes.get(current[1])
                if node is not None and node.thumbnail_enabled:
                    node.set_thumbnail_status(
                        "stale" if node.thumbnail_image is not None else "not_evaluated",
                        "Updating…" if node.thumbnail_image is not None else "Not evaluated",
                    )
        self._thumbnail_in_flight = False
        self._thumbnail_current = None

    def _visible_thumbnail_nodes(self) -> list[NodeItem]:
        if not hasattr(self, "graph_view"):
            return []
        visible = self.graph_view.mapToScene(self.graph_view.viewport().rect()).boundingRect()
        nodes = [
            node for node in self.scene.nodes.values()
            if node.thumbnail_enabled
            and not node.is_docked
            and node.supports_thumbnail()
            and node.sceneBoundingRect().intersects(visible)
        ]
        nodes.sort(key=lambda node: (
            0 if node is self.scene.active_node else 1,
            0 if node.isSelected() else 1,
            node.scenePos().y(),
            node.scenePos().x(),
        ))
        return nodes

    def _thumbnail_preview_source(self, node: NodeItem) -> tuple[str, str, str] | None:
        output_name = node.resolved_thumbnail_output()
        if output_name is None:
            return None
        kind = str(node.output_data_kind(output_name))
        if kind not in NodeItem.THUMBNAIL_VISUAL_KINDS:
            return None
        return node.uid, output_name, kind

    def _thumbnail_request_key(
        self,
        snapshot: GraphSnapshot,
        node: NodeItem,
        output_name: str,
    ) -> str:
        animation = self._animation_context()
        payload = {
            "session": str(self._active_graph_session_uid or ""),
            "node": node.uid,
            "output": output_name,
            "branch": self.evaluator.branch_revision(snapshot, node.uid),
            "size": (128, 128),
            "precision": self.document.texture_precision.value,
            "colour_space": self.document.colour_space,
            "frame": int(animation["frame_number"]),
            "frame_position": float(animation["frame_position"]),
            "loop_phase": float(animation["loop_phase"]),
        }
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"),
            digest_size=20,
        ).hexdigest()

    def _schedule_thumbnail_refresh(self, *_ignored, immediate: bool = False) -> None:
        timer = getattr(self, "thumbnail_timer", None)
        if timer is None:
            return
        if not any(
            node.thumbnail_enabled and not node.is_docked and node.supports_thumbnail()
            for node in self.scene.nodes.values()
        ):
            self._preempt_thumbnail_work()
            return
        delay = 80 if immediate else self._thumbnail_idle_delay_ms
        if self._playing:
            elapsed = (time.perf_counter() - self._thumbnail_last_animation_schedule) * 1000.0
            delay = max(delay, int(self._thumbnail_animation_interval_ms - elapsed))
        if timer.isActive():
            if immediate and timer.remainingTime() > delay:
                timer.start(max(delay, 0))
            return
        timer.start(max(delay, 0))

    def _dispatch_thumbnail_work(self) -> None:
        if self._thumbnail_in_flight:
            return
        # Never start independent thumbnail evaluations during timeline
        # playback. The active node can reuse the already-presented playback
        # frame for free; other pinned nodes settle once playback pauses.
        if self._playing:
            return
        if (
            self._preview_in_flight
            or self._preview_pending
            or self._material_preview_in_flight
            or self._material_preview_pending
            or self._interactive_parameter_edit_depth > 0
            or QApplication.mouseButtons() != Qt.MouseButton.NoButton
        ):
            self._schedule_thumbnail_refresh()
            return
        nodes = self._visible_thumbnail_nodes()
        if not nodes:
            return
        snapshot = GraphSnapshot.from_scene(self.scene)
        for node in nodes:
            source = self._thumbnail_preview_source(node)
            if source is None:
                continue
            node_uid, output_name, _kind = source
            try:
                cache_key = self._thumbnail_request_key(snapshot, node, output_name)
            except Exception as exc:
                node.set_thumbnail_status("error", f"Preview unavailable\n{exc}")
                continue
            if (
                node.thumbnail_cache_key == cache_key
                and node.thumbnail_state in {"ready", "error"}
            ):
                continue
            cached = self._thumbnail_cache.get(cache_key)
            if cached is not None:
                if cached.rgba is not None:
                    node.set_thumbnail_rgba(cached.rgba, cache_key=cache_key)
                else:
                    node.set_thumbnail_signal(cached.signal_value, cache_key=cache_key)
                continue
            node.set_thumbnail_status(
                "rendering",
                "Rendering…" if node.thumbnail_image is None else "Updating…",
            )
            self._thumbnail_in_flight = True
            self._thumbnail_current = (
                str(self._active_graph_session_uid or ""),
                node_uid,
                cache_key,
                output_name,
            )
            self._thumbnail_last_animation_schedule = time.perf_counter()
            self.thumbnail_controller.request(
                snapshot,
                node_uid,
                128,
                128,
                precision=self.document.texture_precision,
                colour_space=self.document.colour_space,
                render_mode="thumbnail",
                interactive_node_uid=node_uid,
                prepare_display=True,
                display_width=128,
                display_height=128,
                output_name=output_name,
                collect_traces=False,
                priority=-1,
                **self._animation_context(),
            )
            return

    def _update_active_thumbnail_from_preview(self, result) -> None:
        node = self.scene.active_node
        if (
            node is None
            or not node.thumbnail_enabled
            or node.is_docked
            or not node.supports_thumbnail()
        ):
            return
        output_name = node.resolved_thumbnail_output()
        if output_name is None or self._pending_preview_source_uid != node.uid:
            return
        preview_output = str(self._pending_preview_source_output or "")
        output_kind = node.output_data_kind(output_name)
        if preview_output != output_name and output_kind != "material":
            return
        if getattr(result, "error", None):
            return
        try:
            snapshot = GraphSnapshot.from_scene(self.scene)
            cache_key = self._thumbnail_request_key(snapshot, node, output_name)
        except Exception:
            return
        signal_value = getattr(result, "signal_value", None)
        if signal_value is not None:
            cached = CachedThumbnail(signal_value=signal_value)
            self._thumbnail_cache.put(cache_key, cached)
            node.set_thumbnail_signal(signal_value, cache_key=cache_key)
            return
        image = getattr(result, "image", None)
        if not isinstance(image, np.ndarray):
            return
        rgba = _prepare_cpu_preview_rgba8(
            image,
            128,
            128,
            str(getattr(result, "data_kind", "grayscale")),
        )
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8).copy()
        self._thumbnail_cache.put(cache_key, CachedThumbnail(rgba=rgba))
        node.set_thumbnail_rgba(rgba, cache_key=cache_key)

    def _thumbnail_ready(self, result) -> None:
        current = self._thumbnail_current
        self._thumbnail_in_flight = False
        self._thumbnail_current = None
        if current is None:
            return
        session_uid, node_uid, cache_key, output_name = current
        if session_uid != str(self._active_graph_session_uid or ""):
            return
        node = self.scene.nodes.get(node_uid)
        if (
            node is None
            or not node.thumbnail_enabled
            or node.is_docked
            or node.resolved_thumbnail_output() != output_name
        ):
            self._schedule_thumbnail_refresh()
            return
        try:
            snapshot = GraphSnapshot.from_scene(self.scene)
            if self._thumbnail_request_key(snapshot, node, output_name) != cache_key:
                node.set_thumbnail_status(
                    "stale" if node.thumbnail_image is not None else "not_evaluated",
                    "Updating…" if node.thumbnail_image is not None else "Not evaluated",
                )
                self._schedule_thumbnail_refresh(immediate=True)
                return
        except Exception:
            self._schedule_thumbnail_refresh()
            return
        error = str(getattr(result, "error", "") or "")
        if error:
            node.thumbnail_cache_key = cache_key
            node.set_thumbnail_status("error", "Preview error")
            QTimer.singleShot(25, self._dispatch_thumbnail_work)
            return
        signal_value = getattr(result, "signal_value", None)
        if signal_value is not None:
            cached = CachedThumbnail(signal_value=signal_value)
            self._thumbnail_cache.put(cache_key, cached)
            node.set_thumbnail_signal(signal_value, cache_key=cache_key)
            QTimer.singleShot(25, self._dispatch_thumbnail_work)
            return
        rgba = getattr(result, "display_rgba", None)
        if not isinstance(rgba, np.ndarray):
            image = getattr(result, "image", None)
            if isinstance(image, np.ndarray):
                rgba = _prepare_cpu_preview_rgba8(
                    image,
                    128,
                    128,
                    str(getattr(result, "data_kind", "grayscale")),
                )
        if not isinstance(rgba, np.ndarray):
            node.thumbnail_cache_key = cache_key
            node.set_thumbnail_status("error", "Preview unavailable")
            QTimer.singleShot(25, self._dispatch_thumbnail_work)
            return
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8).copy()
        self._thumbnail_cache.put(cache_key, CachedThumbnail(rgba=rgba))
        node.set_thumbnail_rgba(rgba, cache_key=cache_key)
        QTimer.singleShot(25, self._dispatch_thumbnail_work)

    def _thumbnail_failed(self, message: str) -> None:
        current = self._thumbnail_current
        self._thumbnail_in_flight = False
        self._thumbnail_current = None
        if current is not None and current[0] == str(self._active_graph_session_uid or ""):
            node = self.scene.nodes.get(current[1])
            if node is not None and node.thumbnail_enabled:
                node.thumbnail_cache_key = current[2]
                node.set_thumbnail_status("error", "Preview unavailable")
        # Continue with other visible pinned thumbnails, but do not retry this
        # unchanged failing revision in a tight loop. A graph/output revision
        # change clears the key and makes it eligible again.
        QTimer.singleShot(25, self._dispatch_thumbnail_work)

    def _cached_material_result_for_inspector(
        self, result: MaterialEvaluationResult, detail: str, elapsed_ms: float
    ) -> MaterialEvaluationResult:
        bytes_used = sum(int(array.nbytes) for array in result.textures.values())
        trace = PresentationCacheTrace(
            node_uid=result.output_uid,
            name=f"{result.output_name} resolved preview",
            elapsed_ms=max(float(elapsed_ms), 0.0),
            width=result.width,
            height=result.height,
            precision=self.document.working_precision,
            data_kind="material",
            bytes_used=bytes_used,
            render_mode="preview_3d",
            details=detail,
        )
        return replace(
            result,
            elapsed_ms=max(float(elapsed_ms), 0.0),
            backend_summary="Preview cache",
            node_traces=(trace,),
            cache_hits=int(result.cache_hits) + 1,
            finalise_ms=0.0,
        )

    def _try_reuse_material_preview(
        self,
        output,
        evaluation_width: int,
        evaluation_height: int,
        texture_width: int,
        texture_height: int,
        request_key: str,
    ) -> bool:
        metadata = self._material_metadata(request_key)
        if metadata is not None:
            started = time.perf_counter()
            if self.preview_3d_panel.activate_cached_result(metadata, request_key):
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                job_id = self._next_evaluation_job("3d")
                self.evaluation_inspector.begin_job(
                    job_id,
                    "Reusing 3D material",
                    metadata.output_name,
                    evaluation_width,
                    evaluation_height,
                    f"3D preview → {texture_width}×{texture_height}",
                )
                cached = self._cached_material_result_for_inspector(
                    metadata,
                    "Resolved material channels and renderer-resident mipmapped textures were reused; no graph evaluation, readback or upload was submitted.",
                    elapsed_ms,
                )
                self.evaluation_inspector.finish_job(job_id, cached)
                self.evaluation_inspector.add_stage(
                    "Renderer material reused", "GPU resident", elapsed_ms,
                    "Swapped the cached texture-set views and redrew the viewport.",
                )
                self._last_material_result_key = request_key
                self._material_preview_pending = False
                self.preview_3d_panel.set_busy(False)
                self.statusBar().showMessage(
                    f"{metadata.output_name} · resolved material and renderer textures reused · {elapsed_ms:.1f} ms",
                    3500,
                )
                return True

        cached_entry = self._material_result_cache.get(request_key)
        if cached_entry is None:
            return False
        result = cached_entry.result
        job_id = self._next_evaluation_job("3d")
        self.evaluation_inspector.begin_job(
            job_id,
            "Reusing resolved material",
            result.output_name,
            evaluation_width,
            evaluation_height,
            f"3D preview → {texture_width}×{texture_height}",
        )
        self.preview_3d_panel.set_busy(True, "Material — reusing resolved maps and restoring renderer textures…")
        started = time.perf_counter()
        reused = self.preview_3d_panel.set_result(result, cache_key=request_key)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._remember_material_metadata(request_key, result)
        cached = self._cached_material_result_for_inspector(
            result,
            "Resolved CPU material maps were reused; graph evaluation and GPU readback were skipped.",
            elapsed_ms,
        )
        self.evaluation_inspector.finish_job(job_id, cached)
        self.evaluation_inspector.add_stage(
            "Renderer material reused" if reused else "Renderer upload from resolved cache",
            "GPU resident" if reused else "CPU → GPU",
            elapsed_ms,
            "No graph work was performed." if reused else "Only the cached authored material maps were uploaded.",
        )
        self._last_material_result_key = request_key
        self._material_preview_pending = False
        self.preview_3d_panel.set_busy(False)
        self.statusBar().showMessage(
            f"{result.output_name} · resolved material cache hit · {elapsed_ms:.1f} ms", 3500
        )
        return True

    def _present_cached_2d_preview(self, result, cache_key: str) -> None:
        started = time.perf_counter()
        self._preview_in_flight = False
        self._preview_pending = False
        self.preview_panel.set_busy(False)
        source_width = int(getattr(result, "source_width", 0) or self._pending_preview_size[0])
        source_height = int(getattr(result, "source_height", 0) or self._pending_preview_size[1])
        self.preview_panel.set_result(
            self._pending_preview_name,
            result.image,
            result.error,
            source_width,
            source_height,
            self.document.working_precision,
            frame_number=result.frame_number,
            time_seconds=result.time_seconds,
            signal_value=result.signal_value,
            data_kind=getattr(result, "data_kind", "grayscale"),
            output_precision=getattr(result, "precision", "16-bit"),
            display_rgba=getattr(result, "display_rgba", None),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        job_id = self._next_evaluation_job("2d")
        width, height = self._pending_preview_size
        self.evaluation_inspector.begin_job(
            job_id, "Reusing 2D preview", self._pending_preview_name or "2D Preview", width, height, "Preview cache"
        )
        display = getattr(result, "display_rgba", None)
        trace = PresentationCacheTrace(
            node_uid=str(getattr(self.scene.active_node, "uid", "")),
            name=f"{self._pending_preview_name or '2D Preview'} display result",
            elapsed_ms=elapsed_ms,
            width=source_width,
            height=source_height,
            precision="8-bit display",
            data_kind=str(getattr(result, "data_kind", "grayscale")),
            bytes_used=int(display.nbytes) if isinstance(display, np.ndarray) else 0,
            details="View-ready RGBA8 pixels were reused; no graph evaluation or final GPU readback was submitted.",
        )
        cached_result = replace(
            result, elapsed_ms=elapsed_ms, finalise_ms=0.0,
            cache_hits=int(getattr(result, "cache_hits", 0)) + 1, node_traces=(trace,),
        )
        self.evaluation_inspector.finish_job(job_id, cached_result)
        self._playback_last_result = result
        self._pending_preview_cache_key = None
        self.statusBar().showMessage(
            f"2D preview cache hit · {self._pending_preview_name or 'Preview'} · {elapsed_ms:.1f} ms", 3000
        )
        self._continue_pending_preview()

    def _clear_material_node_activity(self) -> None:
        activity = getattr(self, "_material_node_activity", None)
        if not activity:
            return
        for uid in tuple(activity):
            self.scene.set_node_evaluation_state(uid, False)
        activity.clear()

    def _preempt_material_preview_for_2d(self, reason: str = "2D preview requested") -> None:
        """Yield automatic 3D work immediately to direct 2D interaction."""
        timer = getattr(self, "material_preview_timer", None)
        timer_active = bool(timer is not None and timer.isActive())
        in_flight = bool(getattr(self, "_material_preview_in_flight", False))
        queued_present = bool(
            getattr(self, "_material_playback_pending_result", None) is not None
            or (
                getattr(self, "material_present_timer", None) is not None
                and self.material_present_timer.isActive()
            )
        )
        if not timer_active and not in_flight and not queued_present:
            return
        if timer_active:
            timer.stop()
        if getattr(self, "_playing", False):
            self._reset_material_playback_stream(reset_quality=False)
        if in_flight:
            self.material_controller.cancel()
        self._material_preview_in_flight = False
        self._pending_material_request_key = None
        self._pending_material_playback_serial = -1
        clear_activity = getattr(self, "_clear_material_node_activity", None)
        if callable(clear_activity):
            clear_activity()
        key_provider = getattr(self, "_current_material_request_key", None)
        current_key = key_provider() if callable(key_provider) else None
        self._material_preview_pending = bool(
            current_key is not None and current_key != getattr(self, "_last_material_result_key", None)
        )
        panel = getattr(self, "preview_3d_panel", None)
        if panel is not None:
            panel.set_busy(False)
        status_bar = getattr(self, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage(f"{reason} — 3D material refresh paused", 1500)

    def _sync_preview_gizmo(self, node=None) -> None:
        panel = getattr(self, "preview_panel", None)
        scene = getattr(self, "scene", None)
        if panel is None or scene is None:
            return
        if node is None:
            node = getattr(scene, "active_node", None)
        if node is None:
            panel.set_gizmo_context(None, None, None)
            return
        panel.set_gizmo_context(node.uid, node.definition.type_id, node.parameters)

    def _preview_gizmo_started(self, node_uid: str) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None:
            return
        if self._preview_gizmo_action_uid is not None:
            self._preview_gizmo_finished(self._preview_gizmo_action_uid)
        self._preview_gizmo_action_uid = node.uid
        self.scene.begin_user_action(
            f"Adjust {node.definition.name} in 2D Preview",
            merge_key=f"node:{node.uid}:preview-gizmo",
        )
        self._parameter_interaction_started(node.uid)

    def _preview_gizmo_changed(self, node_uid: str, changes) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None or not isinstance(changes, dict):
            return
        if self._preview_gizmo_action_uid != node.uid:
            self._preview_gizmo_started(node.uid)
        changed = False
        for name, raw_value in changes.items():
            spec = node.definition.parameter_spec(str(name))
            if spec is None:
                continue
            value = raw_value
            if spec.kind in {"float", "int"}:
                try:
                    numeric = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if spec.minimum is not None:
                    numeric = max(numeric, float(spec.minimum))
                if spec.maximum is not None:
                    numeric = min(numeric, float(spec.maximum))
                value = int(round(numeric)) if spec.kind == "int" else float(numeric)
            if node.parameters.get(spec.name) == value:
                continue
            node.parameters[spec.name] = value
            changed = True
        if not changed:
            return
        self.scene._touch()
        self.preview_panel.canvas.set_gizmo_context(
            node.uid,
            node.definition.type_id,
            node.parameters,
            edit_input=self.preview_panel.edit_input_enabled,
        )
        self._schedule_preview()

    def _preview_gizmo_finished(self, node_uid: str) -> None:
        active_uid = self._preview_gizmo_action_uid
        if active_uid is None:
            return
        self._preview_gizmo_action_uid = None
        self.scene.end_user_action(merge_key=f"node:{active_uid}:preview-gizmo")
        self._parameter_interaction_finished(str(node_uid or active_uid))
        node = self.scene.nodes.get(active_uid)
        if node is not None:
            self._sync_preview_gizmo(node)
            if node.isSelected():
                QTimer.singleShot(0, lambda current=node: self.parameters_panel.set_item(current))

    def _preview_edit_input_toggled(self, _checked: bool) -> None:
        node = getattr(self.scene, "active_node", None)
        if node is None:
            return
        self._sync_preview_gizmo(node)
        if self.preview_timer.isActive():
            self.preview_timer.stop()
        if self._preview_in_flight:
            self.eval_controller.cancel()
            self._preview_in_flight = False
        self._preview_pending = True
        self._arm_preview_dispatch(force_immediate=True)

    def _parameter_interaction_started(self, node_uid: str) -> None:
        self._interactive_parameter_edit_depth += 1
        self._interactive_parameter_node_uid = str(node_uid or "") or None
        # Direct slider feedback always wins over automatic material refreshes,
        # even when the edited branch is unrelated to the active Material branch.
        self._preempt_material_preview_for_2d("Editing parameters")
        key_provider = getattr(self, "_current_material_request_key", None)
        current_key = key_provider() if callable(key_provider) else None
        if current_key is not None and current_key != getattr(self, "_last_material_result_key", None):
            self._material_preview_pending = True

    def _parameter_interaction_finished(self, node_uid: str) -> None:
        del node_uid
        if self._interactive_parameter_edit_depth > 0:
            self._interactive_parameter_edit_depth -= 1
        if self._interactive_parameter_edit_depth > 0:
            return
        self._interactive_parameter_edit_depth = 0
        self._interactive_parameter_node_uid = None

        active = getattr(self.scene, "active_node", None)
        if self._is_geometry_preview_node(active):
            # Settle on the exact authored mesh immediately when the user lets
            # go. Any lower-priority request from the drag is superseded.
            self._schedule_geometry_preview(active, immediate=True)
            return

        if self._find_3d_output() is not None:
            # Material focus now drives both previews: settle the Base Colour in
            # 2D first, then let the queued 3D refresh reuse the resulting cache.
            self._material_preview_pending = True

        # Supersede any reduced-cost draft immediately and resolve the exact
        # authored 2D Preview result. This is a single newest-value render, never
        # a backlog of every intermediate slider position.
        self.preview_timer.stop()
        self.eval_controller.cancel()
        inspector = getattr(self, "evaluation_inspector", None)
        if inspector is not None:
            inspector.cancel_job()
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        self._preview_in_flight = False
        self._playback_preview_pending = False
        self._preview_pending = True
        self._arm_preview_dispatch(force_immediate=True)

    @staticmethod
    def _remaining_dispatch_delay_ms(last_dispatch: float, interval_ms: int) -> int:
        if last_dispatch <= 0.0:
            return 0
        elapsed_ms = (time.perf_counter() - last_dispatch) * 1000.0
        return max(0, int(round(float(interval_ms) - elapsed_ms)))

    def _arm_material_preview_dispatch(self, *, force_immediate: bool = False) -> None:
        if self._material_preview_in_flight or not self._material_preview_pending:
            return
        # Direct parameter feedback always wins. The 3D material bridge waits
        # until the exact 2D preview has settled instead of queueing duplicate
        # high-resolution graph work behind it.
        if self._interactive_parameter_edit_depth > 0:
            return
        if not self._playing and (self._preview_in_flight or self._preview_pending):
            return
        if self.material_preview_timer.isActive():
            if force_immediate:
                self.material_preview_timer.stop()
            else:
                return
        if force_immediate:
            delay = 0
        else:
            delay = self._remaining_dispatch_delay_ms(
                self._material_preview_last_dispatch, self._material_preview_interval_ms
            )
            if not self._playing:
                delay = max(delay, int(getattr(self, "_material_preview_idle_delay_ms", 300)))
        self.material_preview_timer.start(delay)

    def _viewport_texture_resolution_changed(self) -> None:
        if self._find_3d_output() is None:
            return
        if self._playing:
            self._reset_material_playback_stream(reset_quality=True)
        if self._material_preview_in_flight:
            self.material_controller.cancel()
            self._material_preview_in_flight = False
            self._pending_material_request_key = None
            self._pending_material_playback_serial = -1
            self._clear_material_node_activity()
        self._schedule_3d_preview(immediate=True)

    def _schedule_3d_preview(self, *, immediate: bool = False) -> None:
        if not hasattr(self, "material_preview_timer"):
            return
        if not self.preview_3d_panel.available or self._find_3d_output() is None:
            self._material_preview_pending = False
            if self.material_preview_timer.isActive():
                self.material_preview_timer.stop()
            return
        preempt_thumbnail = getattr(self, "_preempt_thumbnail_work", None)
        if callable(preempt_thumbnail):
            preempt_thumbnail()
        self._material_preview_pending = True
        self._arm_material_preview_dispatch(force_immediate=bool(immediate or self._playing))

    def _dispatch_pending_3d_preview(self) -> None:
        if self._find_3d_output() is None:
            self._material_preview_pending = False
            return
        if self._material_preview_in_flight or not self._material_preview_pending:
            return
        if self._interactive_parameter_edit_depth > 0:
            return
        if not self._playing and (self._preview_in_flight or self._preview_pending):
            return
        self._material_preview_pending = False
        self._material_preview_last_dispatch = time.perf_counter()
        self._request_3d_preview()

    def _request_3d_preview(self) -> None:
        if not self.preview_3d_panel.available:
            return
        if self._material_preview_in_flight:
            self._material_preview_pending = True
            return
        spec = self._material_request_spec()
        if spec is None:
            self.material_controller.cancel()
            self._material_preview_in_flight = False
            self._material_preview_pending = False
            self._pending_material_uid = None
            self._pending_material_request_key = None
            self._last_material_result_key = None
            self._clear_material_node_activity()
            self.preview_3d_panel.clear_output()
            return
        (
            output,
            output_port,
            snapshot,
            evaluation_width,
            evaluation_height,
            texture_width,
            texture_height,
            animation,
            request_key,
        ) = spec
        if request_key == self._last_material_result_key:
            self._material_preview_pending = False
            return
        if not self._playing and self._try_reuse_material_preview(
            output, evaluation_width, evaluation_height, texture_width, texture_height, request_key
        ):
            return
        self._pending_material_uid = output.uid
        self._pending_material_request_key = request_key
        self._material_preview_in_flight = True
        self._material_request_is_playback = bool(self._playing)
        if self._playing:
            self._material_playback_request_serial += 1
            self._pending_material_playback_epoch = self._material_playback_epoch
            self._pending_material_playback_serial = self._material_playback_request_serial
        else:
            self._pending_material_playback_epoch = self._material_playback_epoch
            self._pending_material_playback_serial = -1
        # A focused Material now prepares Base Colour for every completed live
        # frame. The same evaluation result feeds both outputs; the 2D preview
        # is no longer artificially capped at 15 FPS and does not start a second
        # graph evaluation.
        prepare_display = True
        if not self._playing:
            self.preview_3d_panel.set_busy(
                True,
                f"Evaluating active Material — {evaluation_width} × {evaluation_height} graph preview "
                f"→ {texture_width} × {texture_height} material maps",
            )
        self.material_controller.request(
            snapshot,
            output.uid,
            output_port,
            evaluation_width,
            evaluation_height,
            texture_width,
            texture_height,
            self.document.texture_precision,
            self.document.colour_space,
            animation,
            playback=self._playing,
            collect_traces=(not self._playing) or self.timeline_panel.profiler_enabled,
            prepare_display=prepare_display,
        )

    def _material_preview_progress(self, current: int, target: int, message: str) -> None:
        if self._playing:
            return
        detail = str(message or "Evaluating material…")
        if target > 0:
            detail = f"{detail} — {current} of {target}"
        self.preview_3d_panel.set_busy(True, detail)
        self.statusBar().showMessage(detail)

    def _material_node_state(
        self,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        if self._playing:
            return
        activity = self._material_node_activity
        self.scene.set_node_evaluation_state(node_uid, active, current, target, message)
        node = self.scene.nodes.get(node_uid)
        inspector_name = node.definition.name if node is not None else "Material stage"
        self.evaluation_inspector.update_node(
            self._evaluation_job_id, node_uid, inspector_name, active, current, target, message
        )
        node_name = node.definition.name if node is not None else "Material node"
        if active:
            detail = str(message or f"Evaluating {node_name} for 3D preview…")
            if target > 0 and " of " not in detail:
                detail = f"{detail} — {current} of {target}"
            activity.pop(node_uid, None)
            activity[node_uid] = detail
            self.preview_3d_panel.set_busy(True, detail)
            self.statusBar().showMessage(detail)
            return
        activity.pop(node_uid, None)
        if activity:
            detail = next(reversed(activity.values()))
            self.preview_3d_panel.set_busy(True, detail)
        elif self._material_preview_in_flight:
            self.preview_3d_panel.set_busy(True, "Material — uploading maps to the renderer…")

    def _material_preview_started(self) -> None:
        if self._playing or self._material_request_is_playback:
            return
        job_id = self._next_evaluation_job("3d")
        output = self._find_3d_output()
        spec = self._material_request_spec()
        if spec is not None:
            _, _, _, eval_w, eval_h, tex_w, tex_h, _, _ = spec
            target_name = str(output.parameters.get("name", output.definition.name)) if output is not None else "Material"
            self.evaluation_inspector.begin_job(
                job_id, "Evaluating 3D material", target_name, eval_w, eval_h,
                f"3D preview → {tex_w}×{tex_h}",
            )
        if output is not None:
            detail = "Material — evaluating connected branches…"
            self._material_node_activity[output.uid] = detail
            self.scene.set_node_evaluation_state(output.uid, True, 0, 0, detail)
            self.preview_3d_panel.set_busy(True, detail)

    def _material_preview_ready(self, result: MaterialEvaluationResult) -> None:
        completed_key = self._pending_material_request_key
        completed_epoch = int(self._pending_material_playback_epoch)
        completed_serial = int(self._pending_material_playback_serial)
        current = self._find_3d_output()
        current_spec = None
        current_key = None
        current_branch_revision = result.branch_revision if self._playing else ""
        if not self._playing:
            current_spec = self._material_request_spec()
            current_key = None if current_spec is None else current_spec[-1]
            if current is not None and current_spec is not None:
                try:
                    current_branch_revision = self.evaluator.branch_revision(current_spec[2], current.uid)
                except Exception:
                    current_branch_revision = ""
        valid = bool(
            current is not None
            and current.uid == result.output_uid
            and completed_key is not None
            and current_branch_revision == result.branch_revision
            and (self._playing or current_key == completed_key)
            and (not self._playing or completed_epoch == self._material_playback_epoch)
        )
        if not valid:
            if not self._playing:
                self.evaluation_inspector.cancel_job()
            self._material_preview_in_flight = False
            self._pending_material_request_key = None
            self._pending_material_playback_serial = -1
            self._clear_material_node_activity()
            self._material_preview_pending = (current is not None) if self._playing else (current_key is not None)
            if self._material_preview_pending:
                self._arm_material_preview_dispatch(force_immediate=self._playing)
            return

        if self._playing:
            # Present Base Colour immediately on worker completion. Epoch and
            # serial checks prevent a frame from the previous focus stream from
            # reaching either viewport after focus returns to the Material.
            self._present_material_playback_2d(result, completed_epoch, completed_serial)
            # Latest completed frame wins. Clear the worker slot immediately so
            # evaluation of a newer playhead frame can overlap 3D presentation.
            pending = self._material_playback_pending_result
            if pending is None or completed_serial > int(pending[3]):
                self._material_playback_pending_result = (
                    result, completed_key, completed_epoch, completed_serial
                )
            self._material_preview_in_flight = False
            self._pending_material_request_key = None
            self._pending_material_playback_serial = -1
            self._clear_material_node_activity()
            if result.frame_number != self.current_frame:
                self._material_preview_pending = True
                self._arm_material_preview_dispatch(force_immediate=True)
            self._arm_material_playback_presentation()
            return

        detail = "Material — uploading maps to the renderer…"
        self._material_node_activity[result.output_uid] = detail
        self.scene.set_node_evaluation_state(result.output_uid, True, 0, 0, detail)
        self.preview_3d_panel.set_busy(True, detail)
        # Defer the renderer upload by one event-loop turn so the status text and
        # orange output-node activity become visible before a large texture
        # upload occupies the UI thread.
        QTimer.singleShot(
            0,
            lambda ready=result, key=completed_key: self._apply_material_preview_result(ready, key),
        )

    def _apply_material_preview_result(
        self,
        result: MaterialEvaluationResult,
        completed_key: str,
        *,
        queued_playback: bool = False,
    ) -> None:
        current_key = self._current_material_request_key()
        if (
            not queued_playback
            and (
                self._pending_material_request_key != completed_key
                or (not self._playing and current_key != completed_key)
            )
        ):
            self.evaluation_inspector.cancel_job()
            self._material_preview_in_flight = False
            self._pending_material_request_key = None
            self._clear_material_node_activity()
            self._material_preview_pending = current_key is not None
            if self._material_preview_pending:
                self._arm_material_preview_dispatch(force_immediate=self._playing)
            return
        upload_started = time.perf_counter()
        try:
            if not self._playing:
                self._material_result_cache.put(completed_key, CachedMaterialResult(result))
                self._remember_material_metadata(completed_key, result)
            renderer_reused = self.preview_3d_panel.set_result(
                result,
                cache_key=None if self._playing else completed_key,
                incremental=self._playing,
            )
            self._last_material_result_key = completed_key
            upload_ms = (time.perf_counter() - upload_started) * 1000.0
            if self._playing and self._is_material_preview_node(getattr(self.scene, "active_node", None)):
                self._record_material_playback_presentation(result, upload_ms)
            if self._playing:
                self._update_material_playback_budget(result, upload_ms)
            else:
                self.evaluation_inspector.finish_job(
                    self._evaluation_job_id, result, upload_ms=0.0 if renderer_reused else upload_ms
                )
                if renderer_reused:
                    self.evaluation_inspector.add_stage(
                        "Renderer material reused", "GPU resident", upload_ms,
                        "The resolved texture set was already resident; no CPU → GPU upload was required.",
                    )
        finally:
            if not queued_playback:
                self._material_preview_in_flight = False
                self._pending_material_request_key = None
                self._clear_material_node_activity()
        if self._playing and result.frame_number != self.current_frame:
            self._material_preview_pending = True
        self._arm_material_preview_dispatch(force_immediate=self._playing)
        if not self._playing:
            self._schedule_thumbnail_refresh()

    def _material_preview_failed(self, message: str) -> None:
        if not self._playing:
            self.evaluation_inspector.fail_job(self._evaluation_job_id, message)
        self._material_preview_in_flight = False
        self._pending_material_request_key = None
        self._clear_material_node_activity()
        self.preview_3d_panel.set_error(message)
        if self._find_3d_output() is not None:
            self._arm_material_preview_dispatch(force_immediate=self._playing)
        if not self._playing:
            self._schedule_thumbnail_refresh()

    def _active_is_flipbook(self) -> bool:
        node = self.scene.active_node
        return bool(node is not None and node.definition.type_id == self.FLIPBOOK_NODE_TYPE)

    def _active_is_flipbook_decode(self) -> bool:
        node = self.scene.active_node
        return bool(node is not None and node.definition.type_id == "animation.flipbook_decode")

    def _refresh_flipbook_decode_playback_mode(
        self, snapshot: GraphSnapshot | None = None
    ) -> bool:
        """Classify the active decoder as cached-atlas or evaluated playback.

        Imported static atlases can be loaded once and sliced locally. A decoder
        fed by Flipbook Generator is different: the generator is a timeline
        sampler, not a materialised atlas during ordinary evaluation. The
        evaluator already has a direct-generator decode path, so these decoders
        belong in the normal frame-ahead playback scheduler.
        """
        node = self.scene.active_node
        cached = False
        if node is not None and node.definition.type_id == "animation.flipbook_decode":
            snapshot = snapshot or GraphSnapshot.from_scene(self.scene)
            cached = self._fast_flipbook_decode_source(node, snapshot) is not None
        self._playback_cached_flipbook_decode = cached
        return cached

    def _uses_cached_flipbook_decode_playback(self) -> bool:
        return bool(
            self._active_is_flipbook_decode()
            and getattr(self, "_playback_cached_flipbook_decode", False)
        )

    def _invalidate_flipbook_decode_cache(self) -> None:
        self._flipbook_decode_sheet = None
        self._flipbook_decode_node_uid = None
        self._flipbook_decode_source_uid = None
        self._flipbook_decode_snapshot = None
        self._pending_decode_node_uid = None
        self._pending_decode_source_uid = None
        self._playback_cached_flipbook_decode = False

    @staticmethod
    def _snapshot_branch_uses_time(snapshot: GraphSnapshot, source_uid: str) -> bool:
        visited: set[str] = set()
        stack = [source_uid]
        while stack:
            uid = stack.pop()
            if uid in visited:
                continue
            visited.add(uid)
            node = snapshot.nodes.get(uid)
            if node is None:
                continue
            if node.definition.uses_time or (node.definition.gpu_spec is not None and node.definition.gpu_spec.uses_time):
                return True
            for input_name in node.input_names:
                source = snapshot.inputs.get((uid, input_name))
                if source is not None:
                    stack.append(source[0])
        return False

    @staticmethod
    def _snapshot_signal_output(
        snapshot: GraphSnapshot,
        source_uid: str,
        output_name: str,
        context: EvalContext,
        memo: dict[str, dict[str, float | tuple[float, ...]]] | None = None,
        visiting: set[str] | None = None,
    ) -> float | tuple[float, ...]:
        memo = {} if memo is None else memo
        visiting = set() if visiting is None else visiting
        if source_uid in memo:
            outputs = memo[source_uid]
            return outputs.get(output_name, next(iter(outputs.values())))
        if source_uid in visiting:
            raise ValueError("Cycle detected in flipbook Phase signal graph")
        node = snapshot.nodes.get(source_uid)
        if node is None or not node.definition.is_signal_node or node.definition.signal_evaluator is None:
            raise ValueError("Flipbook Phase must be driven by an Animation signal")
        visiting.add(source_uid)
        inputs: dict[str, float | tuple[float, ...]] = {}
        parameters = dict(node.parameters)
        for input_name in node.input_names:
            source_ref = snapshot.inputs.get((source_uid, input_name))
            if source_ref is None:
                continue
            value = MainWindow._snapshot_signal_output(
                snapshot, source_ref[0], source_ref[1], context, memo, visiting
            )
            parameter_name = node.parameter_for_port(input_name)
            if parameter_name is not None:
                parameters[parameter_name] = float(value[0] if isinstance(value, tuple) else value)
            else:
                inputs[input_name] = value
        raw = node.definition.signal_evaluator(inputs, parameters, context)
        if isinstance(raw, dict):
            outputs = {str(name): value for name, value in raw.items()}
        else:
            outputs = {node.definition.output_names[0]: raw}
        memo[source_uid] = outputs
        visiting.remove(source_uid)
        return outputs.get(output_name, next(iter(outputs.values())))

    def _fast_flipbook_decode_source(self, node, snapshot: GraphSnapshot) -> str | None:
        if node.definition.type_id != "animation.flipbook_decode":
            return None
        phase_ref = snapshot.inputs.get((node.uid, "Phase"))
        if phase_ref is not None:
            phase_source = snapshot.nodes.get(phase_ref[0])
            if phase_source is None or not phase_source.definition.is_signal_node:
                return None
        source_ref = snapshot.inputs.get((node.uid, "Sheet"))
        if source_ref is None:
            return None
        source = snapshot.nodes.get(source_ref[0])
        if source is None or source.definition.type_id == self.FLIPBOOK_NODE_TYPE:
            return None
        if self._snapshot_branch_uses_time(snapshot, source.uid):
            return None
        return source.uid

    def _try_fast_flipbook_decode(self, node, snapshot: GraphSnapshot) -> bool:
        source_uid = self._fast_flipbook_decode_source(node, snapshot)
        if source_uid is None:
            return False

        if (
            self._flipbook_decode_sheet is not None
            and self._flipbook_decode_node_uid == node.uid
            and self._flipbook_decode_source_uid == source_uid
        ):
            self._flipbook_decode_snapshot = snapshot
            self._present_fast_flipbook_decode(node)
            return True

        if (
            self._preview_in_flight
            and self._pending_preview_kind == "flipbook_decode_sheet"
            and self._pending_decode_node_uid == node.uid
            and self._pending_decode_source_uid == source_uid
        ):
            return True

        self._flipbook_decode_sheet = None
        self._flipbook_decode_node_uid = None
        self._flipbook_decode_source_uid = None
        self._pending_decode_node_uid = node.uid
        self._pending_decode_source_uid = source_uid
        self._flipbook_decode_snapshot = snapshot
        self._pending_preview_name = node.definition.name
        self._pending_preview_kind = "flipbook_decode_sheet"
        self._pending_preview_details = None
        self._pending_preview_size = self.document.preview_size()
        width, height = self._pending_preview_size
        self._pending_display_size = self.preview_panel.recommended_render_size(width, height)
        display_width, display_height = self._pending_display_size
        self._preview_in_flight = True
        self.eval_controller.request(
            snapshot, source_uid, width, height,
            precision=self.document.texture_precision,
            colour_space=self.document.colour_space,
            render_mode="preview",
            **self._animation_context(),
        )
        return True

    def _present_fast_flipbook_decode(self, node) -> None:
        sheet = self._flipbook_decode_sheet
        if sheet is None:
            return
        animation = self._animation_context()
        context = EvalContext(
            width=sheet.shape[1],
            height=sheet.shape[0],
            **animation,
        )
        effective_parameters = dict(node.parameters)
        snapshot = self._flipbook_decode_snapshot
        if snapshot is not None:
            phase_ref = snapshot.inputs.get((node.uid, "Phase"))
            if phase_ref is not None:
                try:
                    phase_value = self._snapshot_signal_output(
                        snapshot, phase_ref[0], phase_ref[1], context
                    )
                    effective_parameters["__input_Phase"] = float(
                        phase_value[0] if isinstance(phase_value, tuple) else phase_value
                    )
                except Exception as exc:
                    self.preview_panel.set_result(
                        node.definition.name, None, f"{type(exc).__name__}: {exc}", 0, 0, self.document.working_precision
                    )
                    return
        try:
            cell, selection, (column, row) = extract_native_flipbook_cell(sheet, effective_parameters, context)
        except Exception as exc:
            self.preview_panel.set_result(
                node.definition.name, None, f"{type(exc).__name__}: {exc}", 0, 0, self.document.working_precision
            )
            return

        self._pending_preview_kind = "frame"
        self._pending_preview_name = node.definition.name
        self._pending_preview_size = (cell.shape[1], cell.shape[0])
        self._preview_in_flight = False
        self._playback_preview_pending = False
        self.preview_panel.set_busy(False)
        details = (
            f"{cell.shape[1]} × {cell.shape[0]} decoded frame · "
            f"cell {selection.relative_index + 1}/{selection.frame_count} "
            f"(atlas {selection.atlas_index}, column {column + 1}, row {row + 1}) · "
            f"{selection.playback_mode}"
        )
        if selection.playback_mode == "Source FPS":
            details += f" · {float(node.parameters.get('source_fps', 30.0)):g} FPS"
        self.preview_panel.set_result(
            node.definition.name, cell, None, cell.shape[1], cell.shape[0], self.document.working_precision,
            frame_number=self.current_frame,
            time_seconds=float(animation["time_seconds"]),
            details_override=details,
            data_kind=self._flipbook_decode_data_kind,
            output_precision=self._flipbook_decode_precision,
        )
        self.statusBar().showMessage(
            f"Cached flipbook decode · requested cell {selection.relative_index + 1} · "
            f"displayed cell {selection.relative_index + 1} · atlas loaded in {self._flipbook_decode_load_ms:.1f} ms",
            2500,
        )

    def _arm_preview_dispatch(self, *, force_immediate: bool = False) -> None:
        if self._preview_in_flight or not self._preview_pending:
            return
        if self.preview_timer.isActive():
            if force_immediate:
                self.preview_timer.stop()
            else:
                return
        interval_ms = (
            int(getattr(self, "_interactive_preview_interval_ms", 16))
            if getattr(self, "_interactive_parameter_edit_depth", 0) > 0
            else self._preview_interval_ms
        )
        delay = 0 if force_immediate else self._remaining_dispatch_delay_ms(
            self._preview_last_dispatch, interval_ms
        )
        self.preview_timer.start(delay)

    def _schedule_preview(self) -> None:
        if not hasattr(self, "preview_timer"):
            return
        active = getattr(self.scene, "active_node", None)
        if self._is_geometry_preview_node(active):
            self._schedule_geometry_preview(active)
            return
        preempt_thumbnail = getattr(self, "_preempt_thumbnail_work", None)
        if callable(preempt_thumbnail):
            preempt_thumbnail()
        if not self._playing:
            preempt = getattr(self, "_preempt_material_preview_for_2d", None)
            if callable(preempt):
                preempt("2D preview requested")
        if (
            getattr(self, "_interactive_parameter_edit_depth", 0) > 0
            and self._preview_in_flight
            and getattr(self, "_pending_preview_kind", "frame") == "frame"
        ):
            # Do not cancel every draft frame while the mouse is moving. Rapid
            # edits previously invalidated each render before it could reach the
            # screen, so the preview appeared frozen until the drag slowed or
            # stopped. Keep the current lightweight draft alive, collapse all
            # newer values into one pending request, then render the newest
            # snapshot immediately after the current frame is presented. This
            # produces bounded-latency animation without building a queue.
            self._preview_pending = True
        if self._playing and not self._active_is_flipbook():
            if self._active_is_flipbook_decode() and self._refresh_flipbook_decode_playback_mode():
                self._playback_preview_pending = True
                if not self._preview_in_flight:
                    QTimer.singleShot(0, self._request_playback_preview)
            else:
                # A graph/parameter change invalidates prepared animation frames,
                # but static upstream resources remain in the evaluator GPU cache.
                self._restart_playback_clock()
                self._invalidate_playback_buffer(rebuild=True)
            return
        self._preview_pending = True
        self._arm_preview_dispatch()

    def _dispatch_pending_preview(self) -> None:
        if not self._playing:
            preempt = getattr(self, "_preempt_material_preview_for_2d", None)
            if callable(preempt):
                preempt("2D preview dispatch")
        if self._playing and not self._active_is_flipbook():
            self._preview_pending = False
            self._request_playback_preview()
            return
        if self._preview_in_flight or not self._preview_pending:
            return
        self._preview_pending = False
        self._preview_last_dispatch = time.perf_counter()
        self._evaluate_active()

    def _continue_pending_preview(self) -> None:
        if self._playing:
            self._schedule_thumbnail_refresh()
            return
        self._arm_preview_dispatch()
        if not self._preview_in_flight and not self._preview_pending:
            self._arm_material_preview_dispatch()
            self._schedule_thumbnail_refresh()

    def _animation_context(self, frame: float | int | None = None) -> dict[str, float | int]:
        self.document.normalise()
        frame_position = float(self.current_frame if frame is None else frame)
        frame_position = self.document.clamp_frame_position(frame_position)
        frame_number = min(max(int(frame_position), 0), self.document.last_frame)
        return {
            "time_seconds": self.document.time_for_frame(frame_position),
            "frame_number": frame_number,
            "frame_position": frame_position,
            "delta_time": 1.0 / self.document.frames_per_second,
            "duration_seconds": self.document.duration_seconds,
            "normalised_time": self.document.normalised_time_for_frame(frame_position),
            "loop_phase": self.document.loop_phase_for_frame(frame_position),
            "frames_per_second": self.document.frames_per_second,
            "document_frame_count": self.document.frame_count,
            "loop_start_frame": self.document.loop_start_frame,
            "loop_end_frame": self.document.loop_end_frame,
        }

    def _timeline_frame_changed(self, frame: int) -> None:
        self.current_frame = min(max(int(frame), 0), self.document.last_frame)
        # A Flipbook Generator previews the whole configured sheet, so changing the
        # playhead does not require rebuilding that same sheet.
        if not self._active_is_flipbook():
            node = self.scene.active_node
            if node is not None and node.definition.type_id == "animation.flipbook_decode":
                snapshot = GraphSnapshot.from_scene(self.scene)
                if self._try_fast_flipbook_decode(node, snapshot):
                    self._schedule_3d_preview(immediate=self._playing)
                    return
            self._schedule_preview()
        self._schedule_3d_preview(immediate=self._playing)

    def _timeline_settings_changed(self) -> None:
        self.document.loop_start_frame = self.timeline_panel.loop_start.value()
        self.document.loop_end_frame = self.timeline_panel.loop_end.value()
        self.document.playback_speed = self.timeline_panel.playback_speed
        self.document.normalise()
        self._update_playback_interval()
        self._mark_document_dirty()
        self._schedule_preview()
        self._schedule_3d_preview()

    def _timeline_performance_settings_changed(self) -> None:
        self.settings.setValue("timeline/playback_mode", self.timeline_panel.playback_mode_name)
        self.settings.setValue("timeline/profiler_enabled", self.timeline_panel.profiler_enabled)
        if self._playing and not self._uses_cached_flipbook_decode_playback() and not self._active_is_flipbook():
            self._restart_playback_clock()
            self._invalidate_playback_buffer(rebuild=True)
        elif not self.timeline_panel.profiler_enabled:
            self.timeline_panel.set_performance_text("")

    def _restart_playback_clock(self) -> None:
        self._playback_clock_started = time.perf_counter()
        self._playback_clock_start_frame = int(self.current_frame)
        self._playback_last_clock_step = 0

    def _invalidate_playback_buffer(self, *, rebuild: bool = False) -> None:
        controller = getattr(self, "playback_controller", None)
        if controller is not None:
            controller.cancel()
        self._playback_buffer.clear()
        self._playback_render_in_flight = False
        self._playback_render_frame = None
        self._playback_waiting_target = None
        self._playback_snapshot = None
        self._playback_node_uid = None
        self._playback_preview_uid = None
        self._playback_preview_output = None
        self._playback_preview_name = None
        self._playback_static_result = None
        self._playback_static_uploaded = False
        if rebuild and self._playing:
            self._prepare_playback_session()
            self._queue_playback_prefetch()

    def _prepare_playback_session(self) -> bool:
        node = self.scene.active_node
        if node is None:
            return False
        self._playback_snapshot = GraphSnapshot.from_scene(self.scene)
        source = self._preview_source_for_node(node, self._playback_snapshot)
        if source is None:
            return False
        self._playback_node_uid = node.uid
        self._playback_preview_uid = str(source[0])
        self._playback_preview_output = str(source[1])
        self._playback_preview_name = str(source[2])
        self._playback_source_size = self.document.preview_size()
        self._playback_display_size = self.preview_panel.recommended_render_size(*self._playback_source_size)
        return True

    def _playback_frame_after(self, frame: int, steps: int = 1) -> int | None:
        start = self.timeline_panel.loop_start.value()
        end = self.timeline_panel.loop_end.value()
        result = int(frame)
        for _ in range(max(int(steps), 0)):
            result += 1
            if result > end:
                if self.timeline_panel.loop_enabled:
                    result = start
                else:
                    return None
        return result

    def _playback_frame_is_ahead(self, frame: int, *, depth: int | None = None) -> bool:
        """Return whether *frame* is still a near-future frame for the playhead.

        Real-time playback may finish a frame after the timeline has already
        advanced past it. Such a completed frame must still be presented rather
        than left in the buffer forever. Conversely, genuinely prefetched frames
        should remain buffered until their timeline position arrives.
        """
        limit = max(int(depth if depth is not None else self._playback_prefetch_depth), 1)
        cursor = int(self.current_frame)
        for _ in range(limit):
            cursor = self._playback_frame_after(cursor)
            if cursor is None:
                return False
            if int(frame) == cursor:
                return True
        return False

    def _queue_playback_prefetch(self) -> None:
        if (
            not self._playing
            or self._active_is_flipbook()
            or self._uses_cached_flipbook_decode_playback()
            or self._playback_render_in_flight
            or self._playback_static_result is not None
            or self._is_material_preview_node(getattr(self.scene, "active_node", None))
        ):
            return
        if self._playback_snapshot is None or self._playback_node_uid is None:
            if not self._prepare_playback_session():
                return

        candidates: list[int] = []
        if self._playback_waiting_target is not None:
            candidates.append(int(self._playback_waiting_target))
        cursor = int(self.current_frame)
        for _ in range(max(int(self._playback_prefetch_depth), 1)):
            following = self._playback_frame_after(cursor)
            if following is None:
                break
            candidates.append(following)
            cursor = following

        frame = next((
            candidate for candidate in candidates
            if candidate not in self._playback_buffer and candidate != self._playback_render_frame
        ), None)
        if frame is None:
            return
        width, height = self._playback_source_size
        display_width, display_height = self._playback_display_size
        self._playback_render_in_flight = True
        self._playback_render_frame = int(frame)
        self.playback_controller.request(
            self._playback_snapshot,
            getattr(self, "_playback_preview_uid", self._playback_node_uid),
            width,
            height,
            precision=self.document.texture_precision,
            colour_space=self.document.colour_space,
            render_mode="preview",
            output_name=getattr(self, "_playback_preview_output", "Image"),
            prepare_display=True,
            display_width=display_width,
            display_height=display_height,
            collect_traces=self.timeline_panel.profiler_enabled,
            **self._animation_context(frame),
        )

    def _trim_playback_buffer(self) -> None:
        while len(self._playback_buffer) > max(int(self._playback_buffer_limit), 1):
            oldest_frame = next(iter(self._playback_buffer))
            if oldest_frame == self._playback_waiting_target and len(self._playback_buffer) > 1:
                self._playback_buffer.move_to_end(oldest_frame)
                continue
            self._playback_buffer.popitem(last=False)

    def _playback_frame_ready(self, result) -> None:
        frame = int(getattr(result, "frame_number", self._playback_render_frame or self.current_frame))
        self._playback_render_in_flight = False
        self._playback_render_frame = None
        if not self._playing:
            return

        # A branch with no time-dependent reachable nodes is identical for every
        # frame. Keep one compact prepared result and advance only timeline
        # metadata thereafter; no repeated graph evaluation, readback or QImage
        # upload is necessary.
        if int(getattr(result, "dynamic_nodes", 0)) == 0:
            self._playback_static_result = result
            self._playback_static_uploaded = False
            self._playback_buffer.clear()
            mode = self.timeline_panel.playback_mode_name
            if mode == "Every frame" and self._playback_waiting_target == frame:
                self._playback_waiting_target = None
                self.current_frame = frame
                self.timeline_panel.set_frame(frame, emit=False)
                self._present_static_playback_frame(frame)
            else:
                # The image is identical for every frame, so it can satisfy the
                # current playhead immediately even if it was prepared using a
                # different frame number.
                self._playback_waiting_target = None
                self._present_static_playback_frame(self.current_frame)
            return

        self._playback_buffer[frame] = result
        self._playback_buffer.move_to_end(frame)
        self._trim_playback_buffer()

        mode = self.timeline_panel.playback_mode_name
        if mode == "Every frame" and self._playback_waiting_target == frame:
            self._playback_buffer.pop(frame, None)
            self._playback_waiting_target = None
            self.current_frame = frame
            self.timeline_panel.set_frame(frame, emit=False)
            self._present_playback_result(result)
        elif mode == "Real-time":
            # A costly frame often finishes after the wall-clock playhead has
            # advanced. 0.28.0 only presented exact frame-number matches, which
            # could starve the 2D preview indefinitely on animated heavy nodes.
            # Keep true frame-ahead results buffered, but immediately present a
            # completed frame that the playhead has already reached or passed.
            if frame == self.current_frame or not self._playback_frame_is_ahead(frame):
                self._playback_buffer.pop(frame, None)
                if self._playback_waiting_target == frame:
                    self._playback_waiting_target = None
                self._present_playback_result(result)
        self._queue_playback_prefetch()

    def _playback_frame_failed(self, message: str) -> None:
        self._playback_render_in_flight = False
        self._playback_render_frame = None
        self.statusBar().showMessage(str(message), 7000)
        if self._playing:
            QTimer.singleShot(0, self._queue_playback_prefetch)

    def _present_playback_result(self, result) -> None:
        node = self.scene.active_node
        if node is None or node.uid != self._playback_node_uid:
            return
        self._pending_preview_source_uid = str(self._playback_preview_uid or node.uid)
        self._pending_preview_source_output = str(self._playback_preview_output or "Image")
        self._update_active_thumbnail_from_preview(result)
        started = time.perf_counter()
        width = int(getattr(result, "source_width", 0) or self._playback_source_size[0])
        height = int(getattr(result, "source_height", 0) or self._playback_source_size[1])
        self.preview_panel.set_result(
            getattr(self, "_playback_preview_name", node.definition.name),
            getattr(result, "image", None),
            getattr(result, "error", None),
            width,
            height,
            self.document.working_precision,
            frame_number=int(getattr(result, "frame_number", self.current_frame)),
            time_seconds=float(getattr(result, "time_seconds", 0.0)),
            signal_value=getattr(result, "signal_value", None),
            data_kind=getattr(result, "data_kind", "grayscale"),
            output_precision=getattr(result, "precision", "16-bit"),
            display_rgba=getattr(result, "display_rgba", None),
        )
        self._playback_last_present_ms = (time.perf_counter() - started) * 1000.0
        self._playback_last_result = result
        self._playback_presented_frames += 1
        self._playback_present_times.append(time.perf_counter())
        self._update_performance_profiler(result)
        # Let 3D follow completed frames without competing with the frame that is
        # currently being prepared for the direct 2D timeline.
        self._schedule_3d_preview(immediate=False)

    def _present_static_playback_frame(self, frame: int) -> None:
        result = self._playback_static_result
        if result is None:
            return
        frame = int(frame)
        time_seconds = self.document.time_for_frame(frame)
        if not self._playback_static_uploaded:
            # Upload/present the prepared image exactly once for this playback
            # session, then update only the lightweight label on later frames.
            self._present_playback_result(result)
            self._playback_static_uploaded = True
            self.preview_panel.update_frame_metadata(frame, time_seconds)
            return
        started = time.perf_counter()
        self.preview_panel.update_frame_metadata(frame, time_seconds)
        self._playback_last_present_ms = (time.perf_counter() - started) * 1000.0
        self._playback_last_result = result
        self._playback_presented_frames += 1
        self._playback_present_times.append(time.perf_counter())
        self._update_performance_profiler(result)
        self._schedule_3d_preview(immediate=False)

    def _update_performance_profiler(self, result=None) -> None:
        if not self.timeline_panel.profiler_enabled:
            return
        ready = result if result is not None else self._playback_last_result
        times = tuple(self._playback_present_times)
        rendered_fps = 0.0
        if self._playing and len(times) >= 2 and times[-1] > times[0]:
            rendered_fps = (len(times) - 1) / (times[-1] - times[0])
        if ready is None:
            self.timeline_panel.set_performance_text(
                f"Playback profiler · buffered {len(self._playback_buffer)} · dropped {self._playback_dropped_frames}"
            )
            return
        traces = [
            trace for trace in tuple(getattr(ready, "node_traces", ()) or ())
            if str(getattr(trace, "stage", "node")) == "node" and not bool(getattr(trace, "cache_hit", False))
        ]
        slowest = sorted(traces, key=lambda trace: float(getattr(trace, "elapsed_ms", 0.0)), reverse=True)[:3]
        slow_text = ", ".join(
            f"{getattr(trace, 'name', 'Node')} {float(getattr(trace, 'elapsed_ms', 0.0)):.1f} ms"
            for trace in slowest
        ) or "all graph nodes cached"
        cache_mb = float(getattr(ready, "gpu_cache_bytes", 0)) / (1024.0 * 1024.0)
        self.timeline_panel.set_performance_text(
            f"Rendered {rendered_fps:.1f} FPS · eval {float(getattr(ready, 'elapsed_ms', 0.0)):.1f} ms · "
            f"finalise {float(getattr(ready, 'finalise_ms', 0.0)):.1f} ms · present {float(getattr(self, '_playback_last_present_ms', 0.0)):.1f} ms · "
            f"buffered {len(self._playback_buffer)} · dropped {self._playback_dropped_frames}\n"
            f"Time-dependent {int(getattr(ready, 'dynamic_nodes', 0))} · static {int(getattr(ready, 'static_nodes', 0))} · "
            f"fused {int(getattr(ready, 'fused_nodes', 0))} nodes / {int(getattr(ready, 'fused_passes', 0))} passes · "
            f"cache hits {int(getattr(ready, 'cache_hits', 0))} · GPU cache {cache_mb:.1f} MB · slowest: {slow_text}"
        )

    def _update_playback_interval(self) -> None:
        if not hasattr(self, "playback_timer"):
            return
        effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
        self.playback_timer.setInterval(max(1, round(1000.0 / effective_fps)))

    def _set_playing(self, playing: bool) -> None:
        preempt_thumbnail = getattr(self, "_preempt_thumbnail_work", None)
        if callable(preempt_thumbnail):
            preempt_thumbnail()
        self._playing = bool(playing)
        self.timeline_panel.set_playing(self._playing)
        if self._playing:
            start = self.timeline_panel.loop_start.value()
            end = self.timeline_panel.loop_end.value()
            if self.current_frame < start or self.current_frame > end:
                self.current_frame = start
                self.timeline_panel.set_frame(self.current_frame, emit=False)
            self.preview_timer.stop()
            self._preview_pending = False
            # Editing and playback use separate workers. Cancel any stale edit
            # preview before priming exact frame-ahead playback.
            self.eval_controller.cancel()
            self._preview_in_flight = False
            self._playback_dropped_frames = 0
            self._playback_presented_frames = 0
            self._playback_present_times.clear()
            self._restart_playback_clock()
            self._update_playback_interval()
            self._invalidate_playback_buffer(rebuild=False)
            self._reset_material_playback_stream(reset_quality=True)
            self._material_playback_2d_presented_frames = 0
            active_material = self._find_3d_output()
            self._material_playback_focus_uid = active_material.uid if active_material is not None else None
            effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
            self._material_playback_present_interval_ms = max(1, round(1000.0 / min(effective_fps, 30.0)))
            self.material_present_timer.stop()
            cached_decode = self._refresh_flipbook_decode_playback_mode()
            material_playback = self._is_material_preview_node(getattr(self.scene, "active_node", None))
            if not self._active_is_flipbook() and not cached_decode and not material_playback:
                self._prepare_playback_session()
                self._queue_playback_prefetch()
            self.playback_timer.start()
            if cached_decode:
                self._request_playback_preview()
            self._schedule_3d_preview(immediate=False)
        else:
            self.playback_timer.stop()
            self._reset_material_playback_stream(reset_quality=False)
            self._material_playback_focus_uid = None
            self._playback_preview_pending = False
            self._invalidate_playback_buffer(rebuild=False)
            # Pausing settles on the exact playhead frame even if real-time
            # playback skipped display frames.
            self._schedule_preview()
            self._schedule_3d_preview(immediate=True)
            self._schedule_thumbnail_refresh()

    def _stop_playback(self) -> None:
        self._set_playing(False)
        self.current_frame = self.timeline_panel.loop_start.value()
        self.timeline_panel.set_frame(self.current_frame, emit=False)
        self._schedule_preview()

    def _cancel_interactive_previews(self, *, include_material: bool = True) -> None:
        """Cancel background previews and make the scheduler immediately reusable."""
        if hasattr(self, "preview_timer"):
            self.preview_timer.stop()
        if hasattr(self, "geometry_preview_timer"):
            self.geometry_preview_timer.stop()
        if hasattr(self, "geometry_controller"):
            self.geometry_controller.cancel()
        self._geometry_preview_in_flight = False
        self._pending_geometry_request = None
        self._pending_geometry_node_uid = None
        clear_geometry_activity = getattr(self, "_clear_geometry_node_activity", None)
        if callable(clear_geometry_activity):
            clear_geometry_activity()
        preempt_thumbnail = getattr(self, "_preempt_thumbnail_work", None)
        if callable(preempt_thumbnail):
            preempt_thumbnail()
        self.eval_controller.cancel()
        if hasattr(self, "playback_controller"):
            self.playback_controller.cancel()
        self.evaluation_inspector.cancel_job()
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        self._preview_in_flight = False
        self._preview_pending = False
        self._playback_preview_pending = False
        if hasattr(self, "_playback_buffer"):
            self._playback_buffer.clear()
            self._playback_render_in_flight = False
            self._playback_render_frame = None
            self._playback_waiting_target = None
            self._playback_static_result = None
            self._playback_static_uploaded = False
        if include_material:
            if hasattr(self, "material_preview_timer"):
                self.material_preview_timer.stop()
            self._reset_material_playback_stream(reset_quality=False)
            self.material_controller.cancel()
            self._material_preview_in_flight = False
            self._material_preview_pending = False
            self._pending_material_request_key = None
            clear_material_activity = getattr(self, "_clear_material_node_activity", None)
            if callable(clear_material_activity):
                clear_material_activity()

    def _refresh_active_geometry_after_state_reset(self) -> None:
        active = self.scene.active_node
        if self._is_geometry_preview_node(active):
            self._show_geometry_node(active)
            return
        material = self._find_3d_output()
        if material is not None:
            self._refresh_material_geometry_override(material)

    def _reset_all_simulations(self) -> None:
        self._cancel_interactive_previews()
        self.evaluator.reset_simulations()
        self._clear_geometry_caches()
        self._refresh_active_geometry_after_state_reset()
        self.statusBar().showMessage("All simulation state reset", 3500)
        self._schedule_preview()
        self._schedule_3d_preview()

    def _reset_simulation_node(self, node_uid: str) -> None:
        self._cancel_interactive_previews()
        self.evaluator.reset_simulations(node_uid)
        self._clear_geometry_caches()
        self._refresh_active_geometry_after_state_reset()
        node = self.scene.nodes.get(node_uid)
        name = node.definition.name if node is not None else "Simulation"
        self.statusBar().showMessage(f"{name} state reset", 3500)
        self._schedule_preview()
        self._schedule_3d_preview()

    def _reset_material_playback_stream(self, *, reset_quality: bool = False) -> None:
        """Invalidate every queued/presented frame from the previous Material focus stream.

        A completed frame may be waiting for the 3D cadence after its worker has
        already released the evaluation slot. Focus changes must invalidate that
        presentation as well as the worker request; otherwise returning to the
        same Material can interleave an old frame with the newly started stream.
        """
        self._material_playback_epoch += 1
        self._material_playback_request_serial = 0
        self._pending_material_playback_epoch = self._material_playback_epoch
        self._pending_material_playback_serial = -1
        self._material_playback_pending_result = None
        self._material_playback_last_presented_frame = -1
        self._material_playback_last_2d_frame = -1
        self._material_playback_last_2d_serial = -1
        self._material_playback_last_3d_serial = -1
        self._material_playback_last_3d_present = 0.0
        timer = getattr(self, "material_present_timer", None)
        if timer is not None:
            timer.stop()
        if reset_quality:
            # Live material maps stay power-of-two. Several procedural/wrapped
            # operations are authored around PoT textures; the former 192 px
            # intermediate tier could magnify a one-texel wrap boundary into a
            # moving horizontal band when the preview was enlarged.
            self._material_playback_live_max = 256
            self._material_playback_latency_ema_ms = 0.0
            self._material_playback_fast_frames = 0
            self._material_playback_slow_frames = 0

    def _arm_material_playback_presentation(self) -> None:
        if not self._playing or self._material_playback_pending_result is None:
            return
        if self.material_present_timer.isActive():
            return
        if self.timeline_panel.playback_mode_name == "Every frame":
            delay = 0
        elif self._material_playback_last_3d_present <= 0.0:
            delay = 0
        else:
            elapsed_ms = (time.perf_counter() - self._material_playback_last_3d_present) * 1000.0
            delay = max(0, int(round(self._material_playback_present_interval_ms - elapsed_ms)))
        self.material_present_timer.start(max(delay, 0))

    def _present_pending_material_playback(self) -> None:
        pending = self._material_playback_pending_result
        self._material_playback_pending_result = None
        if not self._playing or pending is None:
            return
        result, completed_key, completed_epoch, completed_serial = pending
        node = getattr(self.scene, "active_node", None)
        current = self._find_3d_output()
        if (
            node is None
            or not self._is_material_preview_node(node)
            or current is None
            or current.uid != result.output_uid
            or int(completed_epoch) != self._material_playback_epoch
            or int(completed_serial) <= self._material_playback_last_3d_serial
        ):
            return
        self._apply_material_preview_result(
            result, completed_key, queued_playback=True
        )
        self._material_playback_last_3d_serial = int(completed_serial)
        self._material_playback_last_3d_present = time.perf_counter()
        if self._material_playback_pending_result is not None:
            self._arm_material_playback_presentation()

    def _update_material_playback_budget(
        self, result: MaterialEvaluationResult, upload_ms: float
    ) -> None:
        total_ms = max(float(result.elapsed_ms), 0.0) + max(float(upload_ms), 0.0)
        if self._material_playback_latency_ema_ms <= 0.0:
            self._material_playback_latency_ema_ms = total_ms
        else:
            self._material_playback_latency_ema_ms = (
                self._material_playback_latency_ema_ms * 0.82 + total_ms * 0.18
            )
        effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
        budget_ms = 1000.0 / min(effective_fps, 30.0)
        # Keep live maps power-of-two. The former 192 px tier could expose a
        # one-texel wrap/resampling boundary as a moving scanline when enlarged.
        tiers = (128, 256)
        current = int(self._material_playback_live_max)
        index = min(range(len(tiers)), key=lambda candidate: abs(tiers[candidate] - current))
        if self._material_playback_latency_ema_ms > budget_ms * 1.20 and index > 0:
            self._material_playback_slow_frames += 1
            self._material_playback_fast_frames = 0
            # Do not let one focus-switch warm-up or texture resize force an
            # immediate quality drop. Sustained pressure is required.
            if self._material_playback_slow_frames >= 8:
                self._material_playback_live_max = tiers[index - 1]
                self._material_playback_latency_ema_ms = 0.0
                self._material_playback_slow_frames = 0
        elif self._material_playback_latency_ema_ms < budget_ms * 0.58 and index < len(tiers) - 1:
            self._material_playback_fast_frames += 1
            self._material_playback_slow_frames = 0
            if self._material_playback_fast_frames >= 30:
                self._material_playback_live_max = tiers[index + 1]
                self._material_playback_latency_ema_ms = 0.0
                self._material_playback_fast_frames = 0
        else:
            self._material_playback_fast_frames = 0
            self._material_playback_slow_frames = 0

    def _present_material_playback_2d(
        self, result: MaterialEvaluationResult, completed_epoch: int, completed_serial: int
    ) -> None:
        """Present one complete current-stream Base Colour frame without re-evaluation."""
        node = getattr(self.scene, "active_node", None)
        current = self._find_3d_output()
        if (
            node is None
            or not self._is_material_preview_node(node)
            or current is None
            or current.uid != result.output_uid
            or int(completed_epoch) != self._material_playback_epoch
            or int(completed_serial) <= self._material_playback_last_2d_serial
        ):
            return
        if result.base_colour_display is None:
            return
        self.preview_panel.set_prepared_playback_frame(
            result.base_colour_display,
            node_name=f"{result.output_name} · Base Colour",
            width=result.width,
            height=result.height,
            frame_number=result.frame_number,
            time_seconds=result.time_seconds,
            details=(
                f"{result.width} × {result.height} live material playback · Colour · "
                f"{len(result.dynamic_channels)} changing map(s) · "
                f"{result.static_cache_hits} static map cache hit(s)"
            ),
        )
        self._material_playback_last_2d_frame = int(result.frame_number)
        self._material_playback_last_2d_serial = int(completed_serial)
        self._material_playback_2d_presented_frames += 1

    def _record_material_playback_presentation(
        self, result: MaterialEvaluationResult, upload_ms: float
    ) -> None:
        """Record a completed 3D presentation without re-presenting Base Colour."""
        self._playback_last_present_ms = max(float(upload_ms), 0.0)
        self._material_playback_last_presented_frame = int(result.frame_number)
        self._playback_last_result = result
        self._playback_presented_frames += 1
        self._playback_present_times.append(time.perf_counter())
        if self.timeline_panel.profiler_enabled:
            self._update_performance_profiler(result)

    def _material_playback_tick(self) -> bool:
        """Advance a focused Material using the single material evaluation stream."""
        node = getattr(self.scene, "active_node", None)
        if node is None or not self._is_material_preview_node(node):
            return False

        if self.timeline_panel.playback_mode_name == "Every frame":
            if self._material_preview_in_flight or self._material_playback_pending_result is not None:
                return True
            if self._material_playback_last_presented_frame != self.current_frame:
                self._schedule_3d_preview(immediate=True)
                return True
            target = self._playback_frame_after(self.current_frame)
            if target is None:
                self._set_playing(False)
                return True
            self.current_frame = target
            self.timeline_panel.set_frame(target, emit=False)
            self._schedule_3d_preview(immediate=True)
            return True

        start = self.timeline_panel.loop_start.value()
        end = self.timeline_panel.loop_end.value()
        span = max(end - start + 1, 1)
        effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
        step = int((time.perf_counter() - self._playback_clock_started) * effective_fps)
        previous_step = self._playback_last_clock_step
        if step <= previous_step:
            return True
        self._playback_dropped_frames += max(step - previous_step - 1, 0)
        self._playback_last_clock_step = step
        start_offset = self._playback_clock_start_frame - start
        absolute = start_offset + step
        if not self.timeline_panel.loop_enabled and absolute >= span:
            self.current_frame = end
            self.timeline_panel.set_frame(end, emit=False)
            self._set_playing(False)
            return True
        target = start + (absolute % span if self.timeline_panel.loop_enabled else min(absolute, span - 1))
        if target != self.current_frame:
            self.current_frame = target
            self.timeline_panel.set_frame(target, emit=False)
            self._schedule_3d_preview(immediate=True)
        return True

    def _playback_tick(self) -> None:
        if not self._playing:
            return

        if self._material_playback_tick():
            return

        # Flipbook Generator and imported Flipbook Decode keep their specialised
        # local playback paths. Ordinary graphs use the exact frame-ahead buffer.
        if self._active_is_flipbook() or self._uses_cached_flipbook_decode_playback():
            next_frame = self._playback_frame_after(self.current_frame)
            if next_frame is None:
                self._set_playing(False)
                return
            self.current_frame = next_frame
            self.timeline_panel.set_frame(next_frame, emit=False)
            self._request_playback_preview()
            self._schedule_3d_preview(immediate=False)
            return

        if self._playback_static_result is not None:
            if self.timeline_panel.playback_mode_name == "Every frame":
                target = self._playback_frame_after(self.current_frame)
                if target is None:
                    self._set_playing(False)
                    return
                self.current_frame = target
                self.timeline_panel.set_frame(target, emit=False)
                self._present_static_playback_frame(target)
                return

            start = self.timeline_panel.loop_start.value()
            end = self.timeline_panel.loop_end.value()
            span = max(end - start + 1, 1)
            effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
            step = int((time.perf_counter() - self._playback_clock_started) * effective_fps)
            previous_step = self._playback_last_clock_step
            if step <= previous_step:
                return
            self._playback_dropped_frames += max(step - previous_step - 1, 0)
            self._playback_last_clock_step = step
            start_offset = self._playback_clock_start_frame - start
            absolute = start_offset + step
            if not self.timeline_panel.loop_enabled and absolute >= span:
                self.current_frame = end
                self.timeline_panel.set_frame(end, emit=False)
                self._set_playing(False)
                return
            target = start + (absolute % span if self.timeline_panel.loop_enabled else min(absolute, span - 1))
            if target == self.current_frame:
                return
            self.current_frame = target
            self.timeline_panel.set_frame(target, emit=False)
            self._present_static_playback_frame(target)
            return

        if self.timeline_panel.playback_mode_name == "Every frame":
            target = self._playback_frame_after(self.current_frame)
            if target is None:
                self._set_playing(False)
                return
            buffered = self._playback_buffer.pop(target, None)
            if buffered is None:
                self._playback_waiting_target = target
                self._queue_playback_prefetch()
                self._update_performance_profiler()
                return
            self.current_frame = target
            self.timeline_panel.set_frame(target, emit=False)
            self._playback_waiting_target = None
            self._present_playback_result(buffered)
            self._queue_playback_prefetch()
            return

        # Real-time mode derives the playhead from wall-clock time. Rendering is
        # exact quality, but a display frame may be skipped when it is not ready.
        start = self.timeline_panel.loop_start.value()
        end = self.timeline_panel.loop_end.value()
        span = max(end - start + 1, 1)
        effective_fps = max(self.document.frames_per_second * self.document.playback_speed, 1.0)
        step = int((time.perf_counter() - self._playback_clock_started) * effective_fps)
        previous_step = self._playback_last_clock_step
        if step <= previous_step:
            self._queue_playback_prefetch()
            return
        # Count timeline intervals skipped because the UI clock advanced by more
        # than one frame between timer callbacks, even if the newest target was ready.
        self._playback_dropped_frames += max(step - previous_step - 1, 0)
        self._playback_last_clock_step = step
        start_offset = self._playback_clock_start_frame - start
        absolute = start_offset + step
        if not self.timeline_panel.loop_enabled and absolute >= span:
            self.current_frame = end
            self.timeline_panel.set_frame(end, emit=False)
            self._set_playing(False)
            return
        target = start + (absolute % span if self.timeline_panel.loop_enabled else min(absolute, span - 1))
        if target == self.current_frame:
            self._queue_playback_prefetch()
            return
        self.current_frame = target
        self.timeline_panel.set_frame(target, emit=False)
        buffered = self._playback_buffer.pop(target, None)
        if buffered is not None:
            self._present_playback_result(buffered)
        else:
            # When the exact wall-clock target is not ready, present the newest
            # completed frame that is no longer ahead of the playhead. This
            # preserves visible motion under load without ever queuing stale work.
            late_frame = next((
                candidate for candidate in reversed(self._playback_buffer)
                if not self._playback_frame_is_ahead(candidate)
            ), None)
            if late_frame is not None:
                late_result = self._playback_buffer.pop(late_frame)
                for stale in tuple(self._playback_buffer):
                    if not self._playback_frame_is_ahead(stale):
                        self._playback_buffer.pop(stale, None)
                self._present_playback_result(late_result)
            else:
                self._playback_dropped_frames += 1
                self._update_performance_profiler()
            self._playback_waiting_target = target
        self._queue_playback_prefetch()

    def _request_playback_preview(self) -> None:
        if not self._playing or self._active_is_flipbook():
            return
        scene = getattr(self, "scene", None)
        node = getattr(scene, "active_node", None)
        if node is not None and node.definition.type_id == "animation.flipbook_decode":
            snapshot = GraphSnapshot.from_scene(scene)
            if self._try_fast_flipbook_decode(node, snapshot):
                return
        if hasattr(self, "playback_controller"):
            self._queue_playback_prefetch()
            return
        # Compatibility fallback for lightweight scheduler harnesses and older
        # embedded integrations that do not construct the playback controller.
        if self._preview_in_flight:
            self._playback_preview_pending = True
            return
        self._playback_preview_pending = False
        self._preview_pending = False
        self.preview_timer.stop()
        self._preview_last_dispatch = time.perf_counter()
        self._evaluate_active()

    def _flipbook_preview_configuration(self, node) -> tuple[list[float], int, int, int, int, int, str] | str:
        columns, rows = effective_grid(node.parameters)
        samples = sample_positions_from_node(self.document, node.parameters)
        if not samples:
            return "The selected flipbook range contains no samples."
        capacity = columns * rows
        if len(samples) > capacity:
            return f"{len(samples)} frames do not fit inside a {columns} × {rows} flipbook ({capacity} cells)."

        source_width, source_height = self.document.preview_size()
        authored_padding = max(int(node.parameters.get("padding", 0)), 0)
        # Keep the complete preview sheet bounded while preserving the document
        # aspect ratio. This makes even an 8 × 8 flipbook practical to inspect.
        max_sheet_dimension = 1024
        width_without_padding = max(max_sheet_dimension - max(columns - 1, 0) * authored_padding, 1)
        height_without_padding = max(max_sheet_dimension - max(rows - 1, 0) * authored_padding, 1)
        scale = min(
            1.0,
            width_without_padding / max(columns * source_width, 1),
            height_without_padding / max(rows * source_height, 1),
        )
        cell_width = max(1, round(source_width * scale))
        cell_height = max(1, round(source_height * scale))
        preview_padding = max(0, round(authored_padding * scale))
        background = str(node.parameters.get("background", "#00000000"))
        return samples, columns, rows, cell_width, cell_height, preview_padding, background

    def _evaluate_active(self) -> None:
        node = self.scene.active_node
        if node is None:
            self._pending_preview_source_uid = None
            self._pending_preview_source_output = None
            self.eval_controller.cancel()
            self._preview_in_flight = False
            self.preview_panel.set_result(None, None, None, 0, 0, self.document.working_precision)
            return

        # Geometry values are not image resources. Keep them entirely on the
        # dedicated mesh evaluator/3D inspection path even when a delayed 2D
        # preview timer fires after focus changes or parameter edits.
        if self._is_geometry_preview_node(node):
            self._pending_preview_source_uid = None
            self._pending_preview_source_output = None
            self._pending_preview_cache_key = None
            self.eval_controller.cancel()
            self._preview_in_flight = False
            self._preview_pending = False
            self.preview_panel.set_busy(False)
            self._show_geometry_node(node)
            return

        snapshot = GraphSnapshot.from_scene(self.scene)
        preview_source = self._preview_source_for_node(node, snapshot)
        if preview_source is None:
            self._pending_preview_source_uid = None
            self._pending_preview_source_output = None
            self.eval_controller.cancel()
            self._preview_in_flight = False
            if self._is_material_preview_node(node):
                self.preview_panel.show_notice(
                    node.definition.name,
                    "Material Base Colour preview is unavailable.",
                )
                self._arm_material_preview_dispatch(force_immediate=True)
            else:
                self.preview_panel.set_result(node.definition.name, None, "Nothing connected to preview.", 0, 0, self.document.working_precision)
            return
        preview_uid, preview_output, preview_name, _preview_owner_name = preview_source
        self._pending_preview_source_uid = str(preview_uid)
        self._pending_preview_source_output = str(preview_output)

        self._pending_preview_name = preview_name
        self._pending_preview_cache_key = None

        if node.definition.type_id == "animation.flipbook_decode" and self._try_fast_flipbook_decode(node, snapshot):
            return

        self._pending_preview_kind = "frame"
        self._pending_preview_details = None
        self._pending_flipbook_frame_count = 0
        self._embedded_asset_cache: dict[str, tuple[int, int, str]] = {}

        if node.definition.type_id == self.FLIPBOOK_NODE_TYPE:
            configuration = self._flipbook_preview_configuration(node)
            if isinstance(configuration, str):
                self.eval_controller.cancel()
                self._preview_in_flight = False
                self.preview_panel.set_result(
                    self._pending_preview_name, None, configuration, 0, 0, self.document.working_precision
                )
                self.statusBar().showMessage(configuration, 7000)
                return
            samples, columns, rows, cell_width, cell_height, padding, background = configuration
            sheet_width = columns * cell_width + max(columns - 1, 0) * padding
            sheet_height = rows * cell_height + max(rows - 1, 0) * padding
            self._pending_preview_kind = "flipbook"
            self._pending_preview_size = (sheet_width, sheet_height)
            self._pending_flipbook_frame_count = len(samples)
            sampling = str(node.parameters.get("sampling", "Evenly Across Range"))
            source_range = str(node.parameters.get("source_range", "Document Loop"))
            self._pending_preview_details = (
                f"{sheet_width} × {sheet_height} flipbook preview · {len(samples)} frames · "
                f"{columns} × {rows} grid · {cell_width} × {cell_height} per frame · "
                f"{sampling} from {source_range}"
            )
            animations = [self._animation_context(sample) for sample in samples]
            self._preview_in_flight = True
            self.eval_controller.request_flipbook(
                snapshot,
                node.uid,
                cell_width,
                cell_height,
                animations,
                columns=columns,
                rows=rows,
                padding=padding,
                background=background,
                precision=self.document.texture_precision,
                colour_space=self.document.colour_space,
            )
            return

        self._pending_preview_size = self.document.preview_size()
        width, height = self._pending_preview_size
        self._pending_display_size = self.preview_panel.recommended_render_size(width, height)
        display_width, display_height = self._pending_display_size
        self._preview_in_flight = True
        self._pending_preview_render_mode = (
            "interactive" if self._interactive_parameter_edit_depth > 0 else "preview"
        )
        cache_key = self._preview_request_key(
            snapshot, preview_uid, preview_output, width, height,
            display_width, display_height, self._pending_preview_render_mode,
        )
        if not self._playing and self._pending_preview_render_mode == "preview":
            cached_entry = self._preview_result_cache.get(cache_key)
            if cached_entry is not None:
                self._present_cached_2d_preview(cached_entry.result, cache_key)
                return
            self._pending_preview_cache_key = cache_key
        self.eval_controller.request(
            snapshot, preview_uid, width, height,
            precision=self.document.texture_precision,
            colour_space=self.document.colour_space,
            render_mode=self._pending_preview_render_mode,
            interactive_node_uid=self._interactive_parameter_node_uid,
            prepare_display=True,
            display_width=display_width,
            display_height=display_height,
            output_name=preview_output,
            **self._animation_context(),
        )

    def _preview_progress(self, current: int, target: int, name: str) -> None:
        if self._pending_preview_kind == "flipbook":
            return
        if target > 0:
            self.preview_panel.set_busy(True, f"Processing {name}… {current} of {target}")
        else:
            self.preview_panel.set_busy(True, f"Processing {name}…")

    def _preview_activity_map(self) -> dict[str, str]:
        activity = getattr(self, "_preview_node_activity", None)
        if activity is None:
            activity = {}
            self._preview_node_activity = activity
        return activity

    def _preview_node_state(
        self,
        node_uid: str,
        active: bool,
        current: int,
        target: int,
        message: str,
    ) -> None:
        self.scene.set_node_evaluation_state(node_uid, active, current, target, message)
        node_for_inspector = self.scene.nodes.get(node_uid)
        inspector_name = node_for_inspector.definition.name if node_for_inspector is not None else "Node"
        self.evaluation_inspector.update_node(
            self._evaluation_job_id, node_uid, inspector_name, active, current, target, message
        )
        activity = self._preview_activity_map()
        node = self.scene.nodes.get(node_uid)
        node_name = node.definition.name if node is not None else "Node"
        if active:
            detail = str(message or f"Evaluating {node_name}…")
            if target > 0:
                detail = f"{detail} — {current} of {target}"
            activity.pop(node_uid, None)
            activity[node_uid] = detail
            self.preview_panel.set_busy(True, detail)
            self.statusBar().showMessage(detail)
            return

        activity.pop(node_uid, None)
        if activity:
            detail = next(reversed(activity.values()))
            self.preview_panel.set_busy(True, detail)
            self.statusBar().showMessage(detail)
        elif self._preview_in_flight:
            self.preview_panel.set_busy(True, "Finalising preview…")

    def _preview_started(self) -> None:
        job_id = self._next_evaluation_job("2d")
        width, height = self._pending_preview_size
        target = self._pending_preview_name or "2D Preview"
        mode = "Playback" if self._playing else self._pending_preview_render_mode
        self.evaluation_inspector.begin_job(job_id, "Evaluating 2D preview", target, width, height, mode)
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        message = (
            f"Rendering flipbook preview… {self._pending_flipbook_frame_count} frames"
            if self._pending_preview_kind == "flipbook"
            else "Loading flipbook atlas once…"
            if self._pending_preview_kind == "flipbook_decode_sheet"
            else "Evaluating… playback drops stale frames" if self._playing
            else "Evaluating lightweight drag preview…" if self._pending_preview_render_mode == "interactive"
            else "Evaluating exact preview… latest edit wins"
        )
        self.preview_panel.set_busy(True, message)

    def _continue_playback_after_preview(self, rendered_frame: int | None = None) -> None:
        if not self._playing or self._active_is_flipbook():
            self._playback_preview_pending = False
            return
        if self._playback_preview_pending or rendered_frame != self.current_frame:
            self._playback_preview_pending = False
            QTimer.singleShot(0, self._request_playback_preview)

    def _validated_preview_result(self, result):
        """Repair a valid full result whose small presentation readback is empty.

        A legitimate black graph is allowed.  We only rebuild when the retained
        full-resolution image contains visible finite RGB values but the
        separately prepared presentation buffer is entirely black or malformed.
        This covers the intermittent Fluvial finalisation race without treating
        black itself as an error condition.
        """
        if getattr(result, "error", None) or getattr(result, "signal_value", None) is not None:
            return result
        image = getattr(result, "image", None)
        display = getattr(result, "display_rgba", None)
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] < 3:
            return result
        rgb = np.asarray(image[..., :3], dtype=np.float32)
        if not np.isfinite(rgb).all():
            return result
        source_visible = bool(np.max(np.abs(rgb)) > 1.0e-7)
        malformed = not isinstance(display, np.ndarray) or display.ndim != 3 or display.shape[2] != 4
        presentation_black = False
        if isinstance(display, np.ndarray) and display.ndim == 3 and display.shape[2] >= 3:
            presentation_black = not np.any(display[..., :3])
        if not source_visible or (not malformed and not presentation_black):
            return result
        width, height = self._pending_display_size
        rebuilt = _prepare_cpu_preview_rgba8(
            image, max(int(width), 1), max(int(height), 1),
            str(getattr(result, "data_kind", "grayscale")),
        )
        return replace(result, display_rgba=rebuilt)

    def _preview_ready(self, result) -> None:
        # A cancelled image result can still be queued on the Qt event loop.
        # Never let that stale result mark a focused Geometry node as a failed
        # CPU/WGSL image node after its mesh preview has already succeeded.
        if self._is_geometry_preview_node(self.scene.active_node):
            self._pending_preview_cache_key = None
            self._preview_in_flight = False
            self._preview_pending = False
            self.preview_panel.set_busy(False)
            self.scene.clear_node_evaluation_states()
            self._show_geometry_node(self.scene.active_node)
            return
        # Present the texture before rebuilding the inspector table. On larger
        # graphs the diagnostic rows can take a noticeable UI turn to populate;
        # the preview itself must never wait behind diagnostics.
        result = self._validated_preview_result(result)
        self._update_active_thumbnail_from_preview(result)
        inspector_job_id = self._evaluation_job_id
        if getattr(result, "error", None):
            QTimer.singleShot(
                0,
                lambda job_id=inspector_job_id, message=str(result.error):
                    self.evaluation_inspector.fail_job(job_id, message),
            )
        else:
            QTimer.singleShot(
                0,
                lambda job_id=inspector_job_id, ready=result:
                    self.evaluation_inspector.finish_job(job_id, ready),
            )
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        if self._pending_preview_kind == "flipbook_decode_sheet":
            self._preview_in_flight = False
            self.preview_panel.set_busy(False)
            node = self.scene.active_node
            if result.error:
                self.preview_panel.set_result(
                    self._pending_preview_name, None, result.error, 0, 0, self.document.working_precision
                )
                self.statusBar().showMessage(result.error, 7000)
                self._continue_pending_preview()
                return
            if (
                node is None
                or node.definition.type_id != "animation.flipbook_decode"
                or node.uid != self._pending_decode_node_uid
                or result.image is None
            ):
                self._schedule_preview()
                return
            self._flipbook_decode_sheet = result.image.copy()
            self._flipbook_decode_node_uid = node.uid
            self._flipbook_decode_source_uid = self._pending_decode_source_uid
            self._flipbook_decode_backend = result.backend
            self._flipbook_decode_load_ms = result.elapsed_ms
            self._flipbook_decode_data_kind = getattr(result, "data_kind", "color")
            self._flipbook_decode_precision = getattr(result, "precision", "16-bit")
            self._pending_decode_node_uid = None
            self._pending_decode_source_uid = None
            self._present_fast_flipbook_decode(node)
            self._continue_pending_preview()
            return

        cache_key = self._pending_preview_cache_key
        if (
            cache_key is not None
            and not self._playing
            and self._pending_preview_kind == "frame"
            and not getattr(result, "error", None)
            and (getattr(result, "display_rgba", None) is not None or getattr(result, "signal_value", None) is not None)
        ):
            self._preview_result_cache.put(cache_key, CachedPreviewResult(result))
        self._pending_preview_cache_key = None
        self._preview_in_flight = False
        self.preview_panel.set_busy(False)
        source_width = int(getattr(result, "source_width", 0) or 0)
        source_height = int(getattr(result, "source_height", 0) or 0)
        if source_width > 0 and source_height > 0:
            width, height = source_width, source_height
        elif result.image is not None and getattr(result.image, "ndim", 0) == 3:
            height, width = result.image.shape[:2]
        else:
            width, height = self._pending_preview_size
        is_flipbook = self._pending_preview_kind == "flipbook"
        presentation_started = time.perf_counter()
        self.preview_panel.set_result(
            self._pending_preview_name, result.image, result.error, width, height, self.document.working_precision,
            frame_number=None if is_flipbook else result.frame_number,
            time_seconds=None if is_flipbook else result.time_seconds,
            signal_value=result.signal_value,
            details_override=self._pending_preview_details if is_flipbook else None,
            data_kind=getattr(result, "data_kind", "grayscale"),
            output_precision=getattr(result, "precision", "16-bit"),
            display_rgba=getattr(result, "display_rgba", None),
        )
        self._playback_last_present_ms = (time.perf_counter() - presentation_started) * 1000.0
        self._playback_last_result = result
        if not self._playing and not is_flipbook:
            self._update_performance_profiler(result)
        self.scene.clear_node_errors()
        if result.error:
            self.scene.set_node_error(result.error_node_uid, result.error)
            failed_node = self.scene.nodes.get(result.error_node_uid or "")
            if failed_node is not None and failed_node.definition.is_external:
                self.package_manager.record_runtime_error(failed_node.definition, result.error)
            self.statusBar().showMessage(result.error, 7000)
            self._continue_playback_after_preview(result.frame_number)
            self._continue_pending_preview()
            return
        fallback = f" · {len(result.fallback_nodes)} CPU fallback(s)" if result.fallback_nodes else ""
        if is_flipbook:
            self.statusBar().showMessage(
                f"{result.backend} flipbook preview · {self._pending_flipbook_frame_count} frames · "
                f"{result.elapsed_ms:.1f} ms · {result.cache_hits} cache hit(s){fallback}",
                6500,
            )
        else:
            simulation = (
                f" · Simulation {result.simulation_nodes} node(s), {result.simulation_steps} step(s)"
                if getattr(result, "simulation_nodes", 0)
                else ""
            )
            finalise = (
                f" · finalise/readback {result.finalise_ms:.1f} ms"
                if getattr(result, "finalise_ms", 0.0) >= 0.1
                else ""
            )
            self.statusBar().showMessage(
                f"{result.backend} preview · {result.elapsed_ms:.1f} ms{finalise} · "
                f"GPU {result.gpu_nodes} / CPU {result.cpu_nodes} / Signal {result.signal_nodes} nodes · "
                f"frame {result.frame_number} · {result.cache_hits} cache hit(s){simulation}{fallback}",
                6500,
            )
        self._continue_playback_after_preview(result.frame_number)
        self._continue_pending_preview()

    def _preview_failed(self, message: str) -> None:
        if self._is_geometry_preview_node(self.scene.active_node):
            self._pending_preview_cache_key = None
            self._preview_in_flight = False
            self._preview_pending = False
            self.preview_panel.set_busy(False)
            self.scene.clear_node_evaluation_states()
            self._show_geometry_node(self.scene.active_node)
            return
        self.evaluation_inspector.fail_job(self._evaluation_job_id, message)
        activity = getattr(self, "_preview_node_activity", None)
        if activity is not None:
            activity.clear()
        self.scene.clear_node_evaluation_states()
        was_decode_sheet = self._pending_preview_kind == "flipbook_decode_sheet"
        self._pending_preview_cache_key = None
        self._preview_in_flight = False
        self.preview_panel.set_busy(False)
        self.statusBar().showMessage(message, 7000)
        if was_decode_sheet:
            self._pending_decode_node_uid = None
            self._pending_decode_source_uid = None
            self.preview_panel.set_result(
                self._pending_preview_name, None, message, 0, 0, self.document.working_precision
            )
            self._continue_pending_preview()
            return
        self._continue_playback_after_preview()
        self._continue_pending_preview()

    def _resolution_changed(self, text: str) -> None:
        try:
            value = int(text)
        except ValueError:
            return
        if value == self.document.preview_max_dimension:
            return
        self.document.preview_max_dimension = value
        self._mark_document_dirty()
        self.evaluator.clear_cache()
        self._refresh_document_summary()
        self._schedule_preview()
        self._schedule_3d_preview()

    def _refresh_document_summary(self) -> None:
        if not hasattr(self, "document_summary"):
            return
        preview_width, preview_height = self.document.preview_size()
        self.document_summary.setText(
            f"{self.document.width}×{self.document.height} · preview {preview_width}×{preview_height} · "
            f"{self.document.working_precision.replace('-bit float', 'F')} · "
            f"{self.document.frame_count} frames @ {self.document.frames_per_second:g} FPS"
        )
        self.document_summary.setToolTip(
            f"Working colour space: {self.document.colour_space} · "
            f"new tile-aware nodes: {'wrap' if self.document.default_tiling else 'clamp'} · "
            f"new geometric nodes: {self.document.default_geometric_rasterization.lower()}"
        )

    def edit_document_settings(self) -> None:
        dialog = DocumentSettingsDialog(DocumentSettings.from_dict(self.document.to_dict()), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.result_settings()
        if updated.to_dict() == self.document.to_dict():
            return
        self.document = updated
        self.scene.default_tiling = self.document.default_tiling
        self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
        self.scene.canvas_default_size = (self.document.width, self.document.height)
        self.current_frame = min(self.current_frame, self.document.last_frame)
        self.timeline_panel.set_document(self.document)
        self.timeline_panel.set_frame(self.current_frame, emit=False)
        self._update_playback_interval()
        self.resolution_combo.blockSignals(True)
        self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
        self.resolution_combo.blockSignals(False)
        self.evaluator.clear_cache()
        self._mark_document_dirty()
        self._refresh_document_summary()
        self._schedule_preview()
        self._schedule_3d_preview()
        self.statusBar().showMessage(
            f"Document set to {self.document.width} × {self.document.height} · {self.document.working_precision}",
            4500,
        )

    # ------------------------------------------------------------------
    # Multi-graph documents / Graph Explorer
    # ------------------------------------------------------------------
    def _next_untitled_graph_name(self) -> str:
        while True:
            index = self._untitled_graph_counter
            self._untitled_graph_counter += 1
            name = "Untitled.vfxgraph" if index == 1 else f"Untitled Graph {index}.vfxgraph"
            if not any(session.name == name for session in self._graph_sessions.values()):
                return name

    def _remove_graph_session_without_prompt(self, session_uid: str) -> None:
        session = self._graph_sessions.pop(str(session_uid), None)
        if session is None:
            return
        self.graph_explorer.remove_graph(session.uid)
        timer = self._live_graph_update_timers.pop(session.uid, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if self._active_graph_session_uid == session.uid:
            self._active_graph_session_uid = None
        try:
            session.scene.deleteLater()
        except RuntimeError:
            pass

    def _restore_previous_graph_sessions(self) -> None:
        if not getattr(self, "restore_graph_session_action", None) or not self.restore_graph_session_action.isChecked():
            return
        raw = self.settings.value("session/open_graph_paths", [])
        if isinstance(raw, str):
            paths = [raw] if raw else []
        else:
            try:
                paths = [str(value) for value in raw]
            except TypeError:
                paths = []
        if not paths:
            return
        placeholder_uid = self._active_graph_session_uid
        opened: list[GraphDocumentSession] = []
        failures: list[str] = []
        for value in paths:
            path = Path(value).expanduser()
            if not path.is_file():
                failures.append(path.name or str(path))
                continue
            try:
                opened.append(self._open_project_path_in_new_session(path.resolve()))
            except Exception:
                failures.append(path.name)
        if opened:
            placeholder = self._graph_sessions.get(str(placeholder_uid))
            if (
                placeholder is not None
                and placeholder.current_path is None
                and not placeholder.dirty
            ):
                self._remove_graph_session_without_prompt(placeholder.uid)
            active_path_text = str(self.settings.value("session/active_graph_path", "") or "")
            active_path = None
            if active_path_text:
                try:
                    active_path = Path(active_path_text).expanduser().resolve()
                except Exception:
                    active_path = None
            chosen = next(
                (session for session in opened if active_path is not None and session.current_path == active_path),
                opened[-1],
            )
            self.activate_graph_session(chosen.uid)
            self._bind_linked_instances_to_open_sessions()
            self.statusBar().showMessage(
                f"Restored {len(opened)} open graph{'s' if len(opened) != 1 else ''}.",
                4000,
            )
        if failures:
            self.statusBar().showMessage(
                "Some previous graphs could not be restored: " + ", ".join(failures[:3]),
                6000,
            )

    def _active_graph_session(self) -> GraphDocumentSession | None:
        if self._active_graph_session_uid is None:
            return None
        return self._graph_sessions.get(self._active_graph_session_uid)

    def _session_explorer_info(self, session: GraphDocumentSession) -> ExplorerGraphInfo:
        try:
            session.graph_resources.capture_scene(session.scene)
            counts = session.graph_resources.reference_counts(session.scene)
            folders = tuple(
                ExplorerFolderInfo(folder.uid, folder.name, folder.parent_uid)
                for folder in session.graph_resources.folders
            )
            resources = tuple(
                ExplorerResourceInfo(
                    uid=resource.uid,
                    name=resource.name,
                    kind=resource.kind,
                    folder_uid=resource.folder_uid,
                    status=resource.status(session.current_path)[0],
                    status_text=resource.status(session.current_path)[1],
                    path=str(resource.resolved_path(session.current_path) or resource.source_path),
                    embedded=bool(resource.embedded_data),
                    uses=int(counts.get(resource.uid, 0)),
                )
                for resource in session.graph_resources.resources
            )
        except Exception:
            folders = ()
            resources = ()
        return ExplorerGraphInfo(
            uid=session.uid,
            name=session.name,
            path=str(session.current_path or ""),
            dirty=session.dirty,
            active=session.uid == self._active_graph_session_uid,
            embedded=session.current_path is None,
            folders=folders,
            resources=resources,
        )

    def _graph_interface_for_session(self, session: GraphDocumentSession) -> dict:
        try:
            data = session.scene.to_dict()
            data["graph_asset"] = session.graph_asset.to_dict()
            return parse_graph_asset_interface(
                data, self.registry, source_path=session.current_path
            )
        except Exception as exc:
            return {
                "name": session.graph_asset.name,
                "inputs": [],
                "outputs": [],
                "parameters": [],
                "warnings": [f"Could not inspect the published interface: {exc}"],
            }

    def _inspect_graph_session(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return
        self.parameters_dock.show()
        try:
            portability = recovery_summary(session.scene.to_dict())
        except (RuntimeError, AttributeError):
            portability = {
                "linked_graphs": 0, "embedded_graphs": 0, "cached_graphs": 0,
                "external_images": 0, "embedded_images": 0,
                "external_meshes": 0, "embedded_meshes": 0,
            }
        self.parameters_panel.show_graph_properties(
            session.uid,
            session.graph_asset,
            display_name=session.name,
            source_path=str(session.current_path or ""),
            interface=self._graph_interface_for_session(session),
            on_change=lambda field_name, value, uid=session.uid: self._graph_asset_metadata_changed(
                uid, field_name, value
            ),
            on_new_identity=lambda uid=session.uid: self._regenerate_graph_asset_identity(uid),
            portability=portability,
            on_export_self_contained=lambda uid=session.uid: self._run_for_graph_session(
                uid, self.export_self_contained_graph
            ),
            on_export_package=lambda uid=session.uid: self._run_for_graph_session(
                uid, self.export_vfxpackage
            ),
            on_capture_thumbnail_2d=(
                (lambda uid=session.uid: self._capture_graph_thumbnail_2d(uid))
                if session.uid == self._active_graph_session_uid else None
            ),
            on_capture_thumbnail_3d=(
                (lambda uid=session.uid: self._capture_graph_thumbnail_3d(uid))
                if session.uid == self._active_graph_session_uid else None
            ),
            on_import_thumbnail=lambda uid=session.uid: self._import_graph_thumbnail(uid),
            on_clear_thumbnail=lambda uid=session.uid: self._clear_graph_thumbnail(uid),
        )

    def _set_graph_thumbnail(self, session_uid: str, encoded_png: str, source: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return
        session.graph_asset.thumbnail_source = str(source or "")
        self._graph_asset_metadata_changed(session.uid, "thumbnail_png", str(encoded_png or ""))
        if not encoded_png:
            session.graph_asset.thumbnail_source = ""
        session.graph_asset.normalise()
        if session.uid == self._active_graph_session_uid:
            self.graph_asset = session.graph_asset
        self._inspect_graph_session(session.uid)

    def _capture_graph_thumbnail_2d(self, session_uid: str) -> None:
        if str(session_uid) != str(self._active_graph_session_uid):
            QMessageBox.information(
                self, "Open graph to capture thumbnail",
                "Open this graph on the canvas before capturing its 2D preview.",
            )
            return
        image = self.preview_panel.display_image
        if image.isNull():
            QMessageBox.information(
                self, "No 2D preview available",
                "Double-click a graph output or another image-producing node, wait for the 2D preview, then capture it.",
            )
            return
        try:
            encoded = encode_thumbnail_image(image)
        except Exception as exc:
            QMessageBox.critical(self, "Could not capture thumbnail", str(exc))
            return
        self._set_graph_thumbnail(str(session_uid), encoded, "2d")
        self.statusBar().showMessage("Captured graph thumbnail from the 2D Preview", 3500)

    def _capture_graph_thumbnail_3d(self, session_uid: str) -> None:
        if str(session_uid) != str(self._active_graph_session_uid):
            QMessageBox.information(
                self, "Open graph to capture thumbnail",
                "Open this graph on the canvas before capturing its 3D preview.",
            )
            return
        image = self.preview_3d_panel.capture_image()
        if image.isNull():
            QMessageBox.information(
                self, "No 3D preview available",
                "Evaluate a Material or Texture Set Output in the 3D Preview, then capture it.",
            )
            return
        try:
            encoded = encode_thumbnail_image(image)
        except Exception as exc:
            QMessageBox.critical(self, "Could not capture thumbnail", str(exc))
            return
        self._set_graph_thumbnail(str(session_uid), encoded, "3d")
        self.statusBar().showMessage("Captured graph thumbnail from the 3D Preview", 3500)

    def _import_graph_thumbnail(self, session_uid: str) -> None:
        filename, _selected = QFileDialog.getOpenFileName(
            self,
            "Import graph thumbnail",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
        )
        if not filename:
            return
        from PySide6.QtGui import QImage
        image = QImage(filename)
        if image.isNull():
            QMessageBox.warning(self, "Could not import thumbnail", "The selected file is not a readable image.")
            return
        try:
            encoded = encode_thumbnail_image(image)
        except Exception as exc:
            QMessageBox.critical(self, "Could not import thumbnail", str(exc))
            return
        self._set_graph_thumbnail(str(session_uid), encoded, "imported")
        self.statusBar().showMessage(f"Imported graph thumbnail from {Path(filename).name}", 3500)

    def _clear_graph_thumbnail(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None or not session.graph_asset.thumbnail_png:
            return
        self._set_graph_thumbnail(str(session_uid), "", "")
        self.statusBar().showMessage("Cleared graph thumbnail", 3000)

    def _graph_asset_metadata_changed(self, session_uid: str, field_name: str, value) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None or not hasattr(session.graph_asset, str(field_name)):
            return
        if field_name == "tags":
            value = list(value or [])
        setattr(session.graph_asset, str(field_name), value)
        session.graph_asset.normalise()
        session.document_dirty = True
        if session.uid == self._active_graph_session_uid:
            self.graph_asset = session.graph_asset
            self._document_dirty = True
            self._update_dirty_state()
        self._update_graph_explorer_entry(session.uid)
        timer = self._live_graph_update_timers.get(session.uid)
        if timer is not None:
            timer.start()
        self._schedule_autosave()

    def _regenerate_graph_asset_identity(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return
        answer = QMessageBox.question(
            self,
            "Generate new asset identity?",
            "Treat this graph as a new unrelated asset? Existing Graph Instances use the current identity to recognise copies and updates.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        session.graph_asset.regenerate_identity()
        self._graph_asset_metadata_changed(session.uid, "asset_id", session.graph_asset.asset_id)
        self._inspect_graph_session(session.uid)

    def _refresh_graph_inspector(self, session_uid: str) -> None:
        if self.parameters_panel.is_showing_graph(str(session_uid)):
            self._inspect_graph_session(str(session_uid))

    def _update_graph_explorer_entry(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return
        try:
            self.graph_explorer.update_graph(self._session_explorer_info(session))
        except RuntimeError:
            # Harmless late signal during QApplication/MainWindow destruction.
            pass

    def _register_graph_session(
        self,
        scene: GraphScene,
        document: DocumentSettings,
        *,
        current_path: Path | None = None,
        display_name: str | None = None,
        graph_asset: GraphAssetMetadata | None = None,
        export_profiles: ExportProfileLibrary | None = None,
        graph_resources: GraphResourceLibrary | None = None,
    ) -> GraphDocumentSession:
        resolved_display_name = display_name or self._next_untitled_graph_name()
        metadata = graph_asset or GraphAssetMetadata(
            name=Path(resolved_display_name).stem, created_with=__version__
        )
        metadata.normalise()
        session = GraphDocumentSession(
            uid=uuid.uuid4().hex,
            scene=scene,
            document=document,
            current_path=current_path.resolve() if current_path is not None else None,
            viewport_state=None,
            display_name=resolved_display_name,
            graph_asset=metadata,
            export_profiles=export_profiles or ExportProfileLibrary.default(),
            graph_resources=graph_resources or GraphResourceLibrary(),
        )
        self._graph_sessions[session.uid] = session
        scene.graphChanged.connect(
            lambda uid=session.uid: self._session_model_changed(uid)
        )
        scene.undo_stack.cleanChanged.connect(
            lambda _clean, uid=session.uid: self._session_clean_state_changed(uid)
        )
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(220)
        timer.timeout.connect(lambda uid=session.uid: self._propagate_live_graph_source(uid))
        self._live_graph_update_timers[session.uid] = timer
        self._update_graph_explorer_entry(session.uid)
        return session

    def _register_current_graph_session(self) -> None:
        session = self._register_graph_session(
            self.scene,
            self.document,
            current_path=self.current_path,
            display_name=self.current_path.name if self.current_path else self._next_untitled_graph_name(),
            graph_asset=self.graph_asset,
            export_profiles=self.export_profiles,
            graph_resources=self.graph_resources,
        )
        session.document_dirty = self._document_dirty
        session.recovered_dirty = self._recovered_dirty
        session.current_frame = self.current_frame
        session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
        session.view_transform = QTransform(self.graph_view.transform())
        session.view_center = self.graph_view.mapToScene(self.graph_view.viewport().rect().center())
        self._active_graph_session_uid = session.uid
        self.graph_explorer.set_active(session.uid)
        self._update_graph_explorer_entry(session.uid)
        self._inspect_graph_session(session.uid)

    def _stash_active_graph_session(self) -> None:
        session = self._active_graph_session()
        if session is None:
            return
        session.document = self.document
        session.graph_asset = self.graph_asset
        session.export_profiles = self.export_profiles
        session.graph_resources = self.graph_resources
        session.current_path = self.current_path.resolve() if self.current_path is not None else None
        session.document_dirty = bool(self._document_dirty)
        session.recovered_dirty = bool(self._recovered_dirty)
        session.current_frame = int(self.current_frame)
        session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
        session.view_transform = QTransform(self.graph_view.transform())
        session.view_center = self.graph_view.mapToScene(self.graph_view.viewport().rect().center())
        self._update_graph_explorer_entry(session.uid)

    def _cancel_graph_switch_work(self) -> None:
        if getattr(self, "_playing", False):
            self._stop_playback()
        for timer_name in ("preview_timer", "material_preview_timer", "material_present_timer", "thumbnail_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        for controller_name in ("eval_controller", "playback_controller", "material_controller", "thumbnail_controller"):
            controller = getattr(self, controller_name, None)
            if controller is not None:
                controller.cancel()
        self._preview_in_flight = False
        self._preview_pending = False
        self._material_preview_in_flight = False
        self._material_preview_pending = False
        self._pending_material_request_key = None
        self._reset_material_playback_stream(reset_quality=False)
        self._material_playback_focus_uid = None
        self._thumbnail_in_flight = False
        self._thumbnail_current = None
        self._invalidate_playback_buffer(rebuild=False)

    def activate_graph_session(self, session_uid: str) -> bool:
        uid = str(session_uid)
        session = self._graph_sessions.get(uid)
        if session is None:
            return False
        if uid == self._active_graph_session_uid:
            self.graph_explorer.set_active(uid)
            return True

        self._switching_graph_session = True
        try:
            self._cancel_graph_switch_work()
            self._stash_active_graph_session()
            old_scene = self.scene
            self._disconnect_active_scene_signals(old_scene)

            self.scene = session.scene
            self.document = session.document
            self.graph_asset = session.graph_asset
            self.export_profiles = session.export_profiles
            self.graph_resources = session.graph_resources
            self.current_path = session.current_path
            self.current_frame = int(session.current_frame)
            self._document_dirty = bool(session.document_dirty)
            self._recovered_dirty = bool(session.recovered_dirty)
            self._active_graph_session_uid = uid

            self.evaluator.scene = self.scene
            self.graph_view.set_graph_scene(self.scene)
            self.parameters_panel.set_scene(self.scene)
            self.canvas_panel.set_scene(self.scene)
            self._connect_active_scene_signals(self.scene)

            self.scene.default_tiling = self.document.default_tiling
            self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
            self.scene.canvas_default_size = (self.document.width, self.document.height)
            self.timeline_panel.set_document(self.document)
            self.timeline_panel.set_frame(self.current_frame, emit=False)
            self._update_playback_interval()
            self.resolution_combo.blockSignals(True)
            self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
            self.resolution_combo.blockSignals(False)
            self._refresh_document_summary()
            if session.viewport_state is not None:
                self.preview_3d_panel.load_project_state(deepcopy(session.viewport_state))
            else:
                self.preview_3d_panel.reset_project_state()

            if session.view_transform is not None:
                self.graph_view.setTransform(QTransform(session.view_transform))
            if session.view_center is not None:
                self.graph_view.centerOn(session.view_center)
            else:
                self.graph_view._refresh_scene_bounds()

            selected = [item for item in self.scene.selectedItems() if isinstance(item, (NodeItem, GroupFrameItem))]
            selected_item = selected[0] if len(selected) == 1 else None
            self.parameters_panel.set_item(selected_item)
            self.canvas_panel.set_item(selected_item)
            self.scene.set_active_node(
                self.scene.active_node,
                output_name=getattr(self.scene, "active_output_name", None),
                force=True,
            )
        finally:
            self._switching_graph_session = False

        self.graph_explorer.set_active(uid)
        for key in self._graph_sessions:
            self._update_graph_explorer_entry(key)
        self._update_dirty_state()
        self._schedule_thumbnail_refresh(immediate=True)
        self.statusBar().showMessage(f"Active graph: {session.name}", 2500)
        return True

    def _session_clean_state_changed(self, session_uid: str) -> None:
        self._update_graph_explorer_entry(session_uid)
        if session_uid == self._active_graph_session_uid and not self._switching_graph_session:
            try:
                self._update_dirty_state()
            except RuntimeError:
                # A final cleanChanged may arrive while Qt is deleting the
                # window's active QUndoStack during interpreter shutdown.
                pass

    def _session_model_changed(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return
        if session_uid == self._active_graph_session_uid:
            session.document = self.document
            session.graph_asset = self.graph_asset
            session.export_profiles = self.export_profiles
            session.graph_resources = self.graph_resources
            session.current_path = self.current_path
            session.document_dirty = self._document_dirty
            session.recovered_dirty = self._recovered_dirty
            session.current_frame = self.current_frame
        self._update_graph_explorer_entry(session_uid)
        if self._propagating_live_graphs or self._loading:
            return
        self._refresh_graph_inspector(session_uid)
        timer = self._live_graph_update_timers.get(str(session_uid))
        if timer is not None:
            timer.start()

    def _project_data_for_session(
        self,
        session: GraphDocumentSession,
        *,
        serialise_live_instances: bool = True,
        visiting: set[str] | None = None,
    ) -> dict:
        visiting = set() if visiting is None else set(visiting)
        if session.uid in visiting:
            raise ValueError("Recursive open-graph dependency detected while serialising.")
        visiting.add(session.uid)
        # Keep stable resource IDs authoritative on the live scene before
        # serialising. This matters when one node has just split away from a
        # shared resource through a direct source or embed-mode edit.
        session.graph_resources.capture_scene(session.scene)
        data = session.scene.to_dict()
        data["version"] = 20
        data["document"] = session.document.to_dict()
        data["graph_asset"] = session.graph_asset.to_dict()
        data["export_profiles"] = session.export_profiles.to_dict()
        data["viewport_3d"] = deepcopy(
            self.preview_3d_panel.project_state()
            if session.uid == self._active_graph_session_uid
            else (session.viewport_state or {})
        )

        for node_data in data.get("nodes", []):
            parameters = node_data.setdefault("parameters", {})
            if node_data.get("type") == GRAPH_INSTANCE_TYPE and str(parameters.get("_asset_mode", "")) == "Session":
                source_uid = str(parameters.get("_asset_session_uid", ""))
                source_session = self._graph_sessions.get(source_uid)
                if source_session is not None:
                    nested = self._project_data_for_session(
                        source_session,
                        serialise_live_instances=serialise_live_instances,
                        visiting=visiting,
                    )
                    parameters["_asset_cached_graph"] = deepcopy(nested)
                    if serialise_live_instances:
                        if source_session.current_path is not None:
                            parameters["_asset_mode"] = "Linked"
                            parameters["_asset_path"] = str(source_session.current_path)
                            parameters["_asset_embedded_graph"] = None
                            parameters["_asset_status"] = "Linked"
                        else:
                            parameters["_asset_mode"] = "Embedded"
                            parameters["_asset_path"] = ""
                            parameters["_asset_embedded_graph"] = deepcopy(nested)
                            parameters["_asset_status"] = "Embedded from open graph"
                        parameters.pop("_asset_session_uid", None)
            if node_data.get("type") not in {"input.image", "input.mesh"}:
                continue
            if parameters.get("embedded"):
                path = Path(str(parameters.get("path", ""))).expanduser()
                if not path.is_absolute() and session.current_path is not None:
                    path = session.current_path.parent / path
                if path.is_file():
                    path = path.resolve()
                    stat = path.stat()
                    cache_key = str(path.resolve())
                    cached = self._embedded_asset_cache.get(cache_key)
                    if cached is None or cached[:2] != (stat.st_mtime_ns, stat.st_size):
                        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                        cached = (stat.st_mtime_ns, stat.st_size, encoded)
                        self._embedded_asset_cache[cache_key] = cached
                    parameters["_embedded_data"] = cached[2]
                    parameters["_embedded_name"] = path.name
            else:
                parameters.pop("_embedded_data", None)
                parameters.pop("_embedded_name", None)
                parameters.pop("_embedded_original_name", None)
        session.graph_resources.capture_serialized_nodes(data.get("nodes", []))
        data["resources"] = session.graph_resources.to_dict()
        session.graph_resources.compact_serialized_nodes(data.get("nodes", []))
        return data

    def _open_session_uid_for_path(self, path_value, *, owner: GraphDocumentSession | None = None) -> str | None:
        text = str(path_value or "").strip()
        if not text:
            return None
        try:
            path = Path(text).expanduser()
            if not path.is_absolute() and owner is not None and owner.current_path is not None:
                path = owner.current_path.parent / path
            resolved = path.resolve()
        except Exception:
            return None
        for uid, session in self._graph_sessions.items():
            if session.current_path is not None and session.current_path.resolve() == resolved:
                return uid
        return None

    def _instance_open_session_uid(
        self, owner: GraphDocumentSession, node: NodeItem
    ) -> str | None:
        if node.definition.type_id != GRAPH_INSTANCE_TYPE:
            return None
        child_uid = str(node.parameters.get("_asset_session_uid", "")).strip()
        if child_uid in self._graph_sessions:
            return child_uid
        return self._open_session_uid_for_path(node.parameters.get("_asset_path"), owner=owner)

    def _session_depends_on(self, start_uid: str, target_uid: str, seen: set[str] | None = None) -> bool:
        if start_uid == target_uid:
            return True
        seen = set() if seen is None else seen
        if start_uid in seen:
            return False
        seen.add(start_uid)
        session = self._graph_sessions.get(start_uid)
        if session is None:
            return False
        for node in session.scene.nodes.values():
            child_uid = self._instance_open_session_uid(session, node)
            if not child_uid:
                continue
            if child_uid == target_uid or self._session_depends_on(child_uid, target_uid, seen):
                return True
        return False

    def _can_insert_open_graph_instance(self, source_uid: str) -> tuple[bool, str]:
        source = self._graph_sessions.get(str(source_uid))
        target = self._active_graph_session()
        if source is None or target is None:
            return False, "The dragged graph is no longer open."
        if source.uid == target.uid:
            return False, "A graph cannot contain an instance of itself."
        if self._session_depends_on(source.uid, target.uid):
            return False, "This drop would create a recursive graph dependency."
        return True, ""

    def _insert_open_graph_instance(self, source_uid: str, position: QPointF) -> None:
        source = self._graph_sessions.get(str(source_uid))
        target = self._active_graph_session()
        if source is None or target is None:
            return
        allowed, reason = self._can_insert_open_graph_instance(source.uid)
        if not allowed:
            self.statusBar().showMessage(reason or "Cannot add this graph here.", 5500)
            return
        try:
            data = self._project_data_for_session(source, serialise_live_instances=False)
            interface = parse_graph_asset_interface(
                data, self.registry, source_path=source.current_path
            )
            if not interface.get("outputs"):
                raise ValueError("The source graph has no connected Graph Output nodes.")
            parameters = instance_parameters_for_asset(
                data,
                interface,
                source_path=source.current_path,
                embedded=source.current_path is None,
            )
            parameters["_asset_mode"] = "Session"
            parameters["_asset_session_uid"] = source.uid
            parameters["_asset_status"] = "Open graph · live"
            parameters["_asset_cached_graph"] = deepcopy(data)
            if source.current_path is None:
                parameters["_asset_embedded_graph"] = deepcopy(data)
            self.scene.clearSelection()
            node = self.scene.create_node(
                GRAPH_INSTANCE_TYPE, QPointF(position), parameters=parameters
            )
            node.setSelected(True)
            self.graph_view._refresh_scene_bounds()
            self.statusBar().showMessage(
                f"Added live instance of {source.name}. Unsaved source edits update it automatically.",
                4500,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not add open graph", str(exc))

    def _insert_graph_resource(
        self, source_uid: str, resource_uid: str, position: QPointF
    ) -> None:
        source = self._graph_sessions.get(str(source_uid))
        target = self._active_graph_session()
        if source is None or target is None:
            self.statusBar().showMessage("The dragged graph resource is no longer available.", 4000)
            return

        source.graph_resources.capture_scene(source.scene)
        source_resource = source.graph_resources.by_id(resource_uid)
        if source_resource is None:
            self.statusBar().showMessage("The dragged graph resource is no longer available.", 4000)
            return

        try:
            crossed_graphs = source.uid != target.uid
            if crossed_graphs:
                target_resource = target.graph_resources.copy_resource_from(
                    source.graph_resources,
                    source_resource.uid,
                    source_owner_path=source.current_path,
                )
            else:
                target_resource = source_resource

            node_type = "input.mesh" if target_resource.kind == "mesh" else "input.image"
            parameters = target.graph_resources.parameters_for_resource(target_resource.uid)
            target.scene.clearSelection()
            node = target.scene.create_node(
                node_type, QPointF(position), parameters=parameters
            )
            node.setSelected(True)
            target.graph_resources.capture_scene(target.scene)
            if crossed_graphs:
                self._mark_resource_library_dirty(target)
            else:
                self._update_graph_explorer_entry(target.uid)
            self.graph_view._refresh_scene_bounds()
            action = "Copied and added" if crossed_graphs else "Added"
            self.statusBar().showMessage(
                f"{action} {target_resource.name} as a "
                f"{'Mesh Input' if target_resource.kind == 'mesh' else 'Image Input'}.",
                4000,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not add graph resource", str(exc))

    def _bind_linked_instances_to_open_sessions(self) -> None:
        """Use the authoritative in-memory graph whenever its linked source is open.

        This is what makes editing a child graph in Explorer immediately visible
        in already-open parents, even when the parent originally loaded the child
        as a normal linked file asset. Closing the source converts these Session
        links back to ordinary linked or embedded instances.
        """
        if self._propagating_live_graphs:
            return
        prepared: dict[str, tuple[dict, dict]] = {}
        changed_sessions: set[str] = set()
        self._propagating_live_graphs = True
        try:
            for target in self._graph_sessions.values():
                for node in target.scene.nodes.values():
                    if node.definition.type_id != GRAPH_INSTANCE_TYPE:
                        continue
                    if str(node.parameters.get("_asset_mode", "")) == "Session":
                        continue
                    source_uid = self._open_session_uid_for_path(
                        node.parameters.get("_asset_path"), owner=target
                    )
                    source = self._graph_sessions.get(str(source_uid)) if source_uid else None
                    if source is None or source.uid == target.uid:
                        continue
                    if self._session_depends_on(source.uid, target.uid):
                        node.set_error("Open graph binding would create a recursive dependency.")
                        continue
                    try:
                        cached = prepared.get(source.uid)
                        if cached is None:
                            data = self._project_data_for_session(
                                source, serialise_live_instances=False
                            )
                            interface = parse_graph_asset_interface(
                                data, self.registry, source_path=source.current_path
                            )
                            cached = (data, interface)
                            prepared[source.uid] = cached
                        data, interface = cached
                        target.scene._apply_graph_instance_asset(
                            node, deepcopy(data), deepcopy(interface),
                            source_path=source.current_path, embedded=False, touch=False,
                        )
                        node.parameters["_asset_mode"] = "Session"
                        node.parameters["_asset_session_uid"] = source.uid
                        node.parameters["_asset_status"] = "Open graph · live"
                        node.parameters["_asset_cached_graph"] = deepcopy(data)
                        node.set_error(None)
                        changed_sessions.add(target.uid)
                    except Exception as exc:
                        node.set_error(f"Could not bind open graph source: {exc}")
            for uid in changed_sessions:
                session = self._graph_sessions.get(uid)
                if session is not None:
                    session.scene.graphChanged.emit()
                    self._update_graph_explorer_entry(uid)
        finally:
            self._propagating_live_graphs = False
        for uid in changed_sessions:
            self._propagate_live_graph_source(uid)

    def _propagate_live_graph_source(self, source_uid: str) -> None:
        if self._propagating_live_graphs:
            return
        if str(source_uid) not in self._graph_sessions:
            return
        # Propagate breadth-first so A -> B -> C live graph chains refresh in a
        # single debounced pass. graphChanged is intentionally suppressed from
        # scheduling nested timers while this queue owns the propagation.
        queue = deque([str(source_uid)])
        visited: set[str] = set()
        self._propagating_live_graphs = True
        try:
            while queue:
                current_uid = queue.popleft()
                if current_uid in visited:
                    continue
                visited.add(current_uid)
                source = self._graph_sessions.get(current_uid)
                if source is None:
                    continue
                dependants = self._dependant_open_instances(source.uid)
                if not dependants:
                    continue
                try:
                    data = self._project_data_for_session(
                        source, serialise_live_instances=False
                    )
                    interface = parse_graph_asset_interface(
                        data, self.registry, source_path=source.current_path
                    )
                except Exception as exc:
                    for _session, node in dependants:
                        node.set_error(f"Open graph could not be refreshed: {exc}")
                    continue
                changed_targets: set[str] = set()
                for target_session, node in dependants:
                    try:
                        target_session.scene._apply_graph_instance_asset(
                            node,
                            deepcopy(data),
                            deepcopy(interface),
                            source_path=source.current_path,
                            embedded=source.current_path is None,
                            touch=False,
                        )
                        node.parameters["_asset_mode"] = "Session"
                        node.parameters["_asset_session_uid"] = source.uid
                        node.parameters["_asset_status"] = "Open graph · live"
                        node.parameters["_asset_cached_graph"] = deepcopy(data)
                        node.set_error(None)
                        # An unsaved child is embedded when its parent is saved,
                        # so changes to that live child are parent document data.
                        if source.current_path is None:
                            target_session.document_dirty = True
                            if target_session.uid == self._active_graph_session_uid:
                                self._document_dirty = True
                        changed_targets.add(target_session.uid)
                    except Exception as exc:
                        node.set_error(f"Open graph refresh failed: {exc}")
                for target_uid in changed_targets:
                    target = self._graph_sessions.get(target_uid)
                    if target is None:
                        continue
                    target.scene.graphChanged.emit()
                    self._update_graph_explorer_entry(target_uid)
                    if target_uid not in visited:
                        queue.append(target_uid)
        finally:
            self._propagating_live_graphs = False
        if self._active_graph_session_uid in visited:
            update_dirty = getattr(self, "_update_dirty_state", None)
            if callable(update_dirty):
                update_dirty()

    def _run_for_graph_session(self, session_uid: str, operation) -> bool:
        uid = str(session_uid)
        previous = self._active_graph_session_uid
        if not self.activate_graph_session(uid):
            return False
        try:
            return bool(operation())
        finally:
            if previous and previous in self._graph_sessions and previous != uid:
                self.activate_graph_session(previous)

    def _explorer_save_requested(self, session_uid: str) -> None:
        self._run_for_graph_session(session_uid, self.save_project)

    def _explorer_save_as_requested(self, session_uid: str) -> None:
        self._run_for_graph_session(session_uid, self.save_project_as)

    def _explorer_save_copy_requested(self, session_uid: str) -> None:
        def save_copy() -> bool:
            destination = self._choose_graph_path(save=True)
            if destination is None:
                return False
            try:
                data = self._project_data()
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
                temporary.replace(destination)
                self.statusBar().showMessage(
                    f"Saved a copy as {destination.name}; the current graph remains linked to its original file.",
                    4500,
                )
                return True
            except Exception as exc:
                QMessageBox.critical(self, "Could not save graph copy", str(exc))
                return False
        self._run_for_graph_session(session_uid, save_copy)

    def save_all_projects(self) -> bool:
        previous = self._active_graph_session_uid
        for uid, session in list(self._graph_sessions.items()):
            if not session.dirty:
                continue
            self.activate_graph_session(uid)
            if not self.save_project():
                if previous and previous in self._graph_sessions:
                    self.activate_graph_session(previous)
                return False
        if previous and previous in self._graph_sessions:
            self.activate_graph_session(previous)
        self.statusBar().showMessage("All modified graphs saved", 3000)
        return True

    def duplicate_graph_session(self, session_uid: str) -> None:
        source = self._graph_sessions.get(str(session_uid))
        if source is None:
            return
        data = self._project_data_for_session(source)
        duplicated_resources = GraphResourceLibrary.from_project_data(data)
        scene = GraphScene(self.registry, self)
        scene.default_tiling = source.document.default_tiling
        scene.default_geometric_rasterization = source.document.default_geometric_rasterization
        scene.canvas_default_size = (source.document.width, source.document.height)
        session = self._register_graph_session(
            scene,
            DocumentSettings.from_dict(data.get("document")),
            display_name=f"{Path(source.name).stem} Copy.vfxgraph",
            graph_asset=GraphAssetMetadata.from_dict(
                data.get("graph_asset"),
                default_name=source.graph_asset.name,
                created_with=__version__,
            ),
            export_profiles=ExportProfileLibrary.from_dict(data.get("export_profiles")),
            graph_resources=duplicated_resources,
        )
        self.activate_graph_session(session.uid)
        self._loading = True
        try:
            self.preview_3d_panel.load_project_state(data.get("viewport_3d"))
            self.scene.from_dict(data)
        finally:
            self._loading = False
        self.scene.undo_stack.clear()
        self.scene.undo_stack.setClean()
        self._document_dirty = True
        self._update_dirty_state()
        self.graph_view.fitInView(
            self.scene.content_bounds().adjusted(-120, -120, 120, 120),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._inspect_graph_session(session.uid)

    def _dependant_open_instances(self, source_uid: str) -> list[tuple[GraphDocumentSession, NodeItem]]:
        result: list[tuple[GraphDocumentSession, NodeItem]] = []
        source = self._graph_sessions.get(str(source_uid))
        source_path = source.current_path.resolve() if source and source.current_path is not None else None
        for session in self._graph_sessions.values():
            for node in session.scene.nodes.values():
                if node.definition.type_id != GRAPH_INSTANCE_TYPE:
                    continue
                direct_uid = str(node.parameters.get("_asset_session_uid", "")).strip()
                matches = direct_uid == str(source_uid)
                if not matches and source_path is not None:
                    linked_uid = self._open_session_uid_for_path(
                        node.parameters.get("_asset_path"), owner=session
                    )
                    matches = linked_uid == str(source_uid)
                if matches:
                    result.append((session, node))
        return result

    def _detach_session_dependants(self, source: GraphDocumentSession) -> None:
        dependants = self._dependant_open_instances(source.uid)
        if not dependants:
            return
        if source.current_path is not None and source.current_path.is_file():
            try:
                data = json.loads(source.current_path.read_text(encoding="utf-8"))
                interface = parse_graph_asset_interface(data, self.registry, source_path=source.current_path)
                for target, node in dependants:
                    target.scene._apply_graph_instance_asset(
                        node, deepcopy(data), deepcopy(interface),
                        source_path=source.current_path, embedded=False, touch=False,
                    )
                    target.scene.graphChanged.emit()
                return
            except Exception:
                pass
        data = self._project_data_for_session(source)
        interface = parse_graph_asset_interface(data, self.registry, source_path=source.current_path)
        for target, node in dependants:
            target.scene._apply_graph_instance_asset(
                node, deepcopy(data), deepcopy(interface),
                source_path=None, embedded=True, touch=False,
            )
            node.parameters.pop("_asset_session_uid", None)
            node.parameters["_asset_status"] = "Embedded when source graph closed"
            target.document_dirty = True
            if target.uid == self._active_graph_session_uid:
                self._document_dirty = True
            target.scene.graphChanged.emit()
            self._update_graph_explorer_entry(target.uid)

    def _confirm_close_graph_session(self, session: GraphDocumentSession) -> bool:
        dependants = self._dependant_open_instances(session.uid)
        previous = self._active_graph_session_uid
        self.activate_graph_session(session.uid)
        if session.current_path is None and dependants:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Close unsaved graph used by other graphs?")
            box.setText(
                f"{session.name} is used by {len(dependants)} open Graph Instance"
                f"{'s' if len(dependants) != 1 else ''}."
            )
            box.setInformativeText(
                "Save it as a linked .vfxgraph, or embed its current revision into the dependant graphs before closing."
            )
            save_button = box.addButton("Save Graph…", QMessageBox.ButtonRole.AcceptRole)
            embed_button = box.addButton("Embed and Close", QMessageBox.ButtonRole.DestructiveRole)
            cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(save_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_button:
                if previous and previous in self._graph_sessions and previous != session.uid:
                    self.activate_graph_session(previous)
                return False
            if clicked is save_button:
                return self.save_project()
            return clicked is embed_button
        if not session.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved graph",
            f"Save changes to {session.name} before closing it?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            if previous and previous in self._graph_sessions and previous != session.uid:
                self.activate_graph_session(previous)
            return False
        if answer == QMessageBox.StandardButton.Save and not self.save_project():
            return False
        return True

    def close_graph_session(self, session_uid: str) -> bool:
        session = self._graph_sessions.get(str(session_uid))
        if session is None:
            return False
        if not self._confirm_close_graph_session(session):
            return False
        self._detach_session_dependants(session)
        was_active = session.uid == self._active_graph_session_uid
        self.graph_explorer.remove_graph(session.uid)
        timer = self._live_graph_update_timers.pop(session.uid, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._graph_sessions.pop(session.uid, None)
        if was_active:
            self._active_graph_session_uid = None
            next_uid = next(iter(self._graph_sessions), None)
            if next_uid is not None:
                self.activate_graph_session(next_uid)
            else:
                self._create_new_graph_session()
        try:
            session.scene.deleteLater()
        except RuntimeError:
            pass
        self._refresh_autosave_after_save()
        return True

    def close_active_graph(self) -> None:
        session = self._active_graph_session()
        if session is not None:
            self.close_graph_session(session.uid)

    def close_other_graph_sessions(self, keep_uid: str) -> None:
        keep = str(keep_uid)
        if keep not in self._graph_sessions:
            return
        self.activate_graph_session(keep)
        for uid in list(self._graph_sessions):
            if uid == keep:
                continue
            if not self.close_graph_session(uid):
                break
        if keep in self._graph_sessions:
            self.activate_graph_session(keep)

    def _create_new_graph_session(self) -> GraphDocumentSession:
        scene = GraphScene(self.registry, self)
        document = DocumentSettings()
        scene.default_tiling = document.default_tiling
        scene.default_geometric_rasterization = document.default_geometric_rasterization
        scene.canvas_default_size = (document.width, document.height)
        session = self._register_graph_session(scene, document)
        self.activate_graph_session(session.uid)
        self._create_starter_graph()
        self._stash_active_graph_session()
        self._update_graph_explorer_entry(session.uid)
        self._inspect_graph_session(session.uid)
        return session

    def _reveal_graph_session(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is not None and session.current_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(session.current_path.parent)))

    def _reload_graph_session(self, session_uid: str) -> None:
        session = self._graph_sessions.get(str(session_uid))
        if session is None or session.current_path is None:
            return
        if session.dirty:
            answer = QMessageBox.question(
                self, "Reload graph?", f"Discard unsaved changes in {session.name} and reload it from disk?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        self.activate_graph_session(session.uid)
        try:
            self._load_project_path(session.current_path)
            self._stash_active_graph_session()
            self._bind_linked_instances_to_open_sessions()
            self._update_graph_explorer_entry(session.uid)
        except Exception as exc:
            QMessageBox.critical(self, "Could not reload graph", str(exc))

    def _add_graph_session_to_library(self, session_uid: str) -> None:
        from .graph_asset_library import add_graph_asset_directory
        session = self._graph_sessions.get(str(session_uid))
        if session is None or session.current_path is None:
            return
        if add_graph_asset_directory(session.current_path.parent, self.settings):
            self.library_panel.rebuild()
            self.statusBar().showMessage(f"Added {session.current_path.parent} to Graph Assets", 3500)

    def _resource_session(self, session_uid: str) -> GraphDocumentSession | None:
        session = self._graph_sessions.get(str(session_uid))
        if session is not None:
            session.graph_resources.capture_scene(session.scene)
        return session

    def _mark_resource_library_dirty(self, session: GraphDocumentSession) -> None:
        session.document_dirty = True
        if session.uid == self._active_graph_session_uid:
            self.graph_resources = session.graph_resources
            self._document_dirty = True
            self._update_dirty_state()
            self._schedule_autosave()
        self._update_graph_explorer_entry(session.uid)
        self._refresh_graph_inspector(session.uid)

    def _explorer_add_resource_folder(self, session_uid: str, parent_uid: str) -> None:
        session = self._resource_session(session_uid)
        if session is None:
            return
        name, accepted = QInputDialog.getText(self, "New resource folder", "Folder name:", text="New Folder")
        if not accepted or not str(name).strip():
            return
        session.graph_resources.add_folder(str(name), str(parent_uid or ""))
        self._mark_resource_library_dirty(session)

    def _explorer_rename_resource_folder(self, session_uid: str, folder_uid: str) -> None:
        session = self._resource_session(session_uid)
        folder = session.graph_resources.folder_by_id(folder_uid) if session is not None else None
        if session is None or folder is None:
            return
        name, accepted = QInputDialog.getText(self, "Rename resource folder", "Folder name:", text=folder.name)
        if accepted and session.graph_resources.rename_folder(folder.uid, str(name)):
            self._mark_resource_library_dirty(session)

    def _explorer_remove_resource_folder(self, session_uid: str, folder_uid: str) -> None:
        session = self._resource_session(session_uid)
        folder = session.graph_resources.folder_by_id(folder_uid) if session is not None else None
        if session is None or folder is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Remove resource folder?")
        box.setText(f"Remove the virtual folder '{folder.name}'?")
        box.setInformativeText(
            "Its subfolders and resources will move to the parent folder; no files will be deleted."
        )
        remove_button = box.addButton("Remove Folder", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is remove_button and session.graph_resources.remove_folder(folder.uid):
            self._mark_resource_library_dirty(session)

    def _explorer_select_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        if session is None:
            return
        self.activate_graph_session(session.uid)
        node_uids = session.graph_resources.node_uids_for_resource(session.scene, resource_uid)
        if not node_uids:
            self.statusBar().showMessage("This resource is not currently used by a node.", 3500)
            return
        self.scene.clearSelection()
        selected = []
        for node_uid in node_uids:
            node = self.scene.nodes.get(node_uid)
            if node is not None:
                node.setSelected(True)
                selected.append(node)
        if selected:
            self.scene.set_active_node(selected[0])
            self.graph_view.centerOn(selected[0])
            self.statusBar().showMessage(
                f"Selected {len(selected)} node{'s' if len(selected) != 1 else ''} using this resource.",
                3000,
            )

    @staticmethod
    def _resource_dialog_filter(kind: str) -> tuple[str, str]:
        if str(kind) == "mesh":
            return "Choose OBJ mesh", "Wavefront OBJ meshes (*.obj);;All files (*)"
        return "Choose image", "Images (*.png *.tga *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)"

    def _explorer_relink_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        if session is None or resource is None:
            return
        title, filters = self._resource_dialog_filter(resource.kind)
        current = str(resource.resolved_path(session.current_path) or Path.home())
        filename, _selected = QFileDialog.getOpenFileName(self, f"Relink {resource.name}", current, filters)
        if not filename:
            return
        try:
            session.graph_resources.relink(resource.uid, filename)
            count = session.graph_resources.apply_resource_to_scene(session.scene, resource.uid, touch=True)
            self._mark_resource_library_dirty(session)
            self.statusBar().showMessage(
                f"Relinked {resource.name} for {count} node{'s' if count != 1 else ''}.", 4000
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not relink resource", str(exc))

    def _explorer_embed_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        if session is None or resource is None:
            return
        try:
            session.graph_resources.embed(
                resource.uid, source_path=resource.resolved_path(session.current_path)
            )
            count = session.graph_resources.apply_resource_to_scene(session.scene, resource.uid, touch=True)
            self._mark_resource_library_dirty(session)
            self.statusBar().showMessage(
                f"Embedded {resource.name} in the graph for {count} node{'s' if count != 1 else ''}.", 4000
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not embed resource", str(exc))

    def _explorer_restore_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        if session is None or resource is None or not resource.embedded_data:
            return
        extension = ".obj" if resource.kind == "mesh" else Path(resource.embedded_name or resource.name).suffix
        suggested_name = resource.embedded_name or resource.name
        if extension and not Path(suggested_name).suffix:
            suggested_name += extension
        _title, filters = self._resource_dialog_filter(resource.kind)
        filename, _selected = QFileDialog.getSaveFileName(
            self, f"Restore {resource.name}", str(Path.home() / suggested_name), filters
        )
        if not filename:
            return
        try:
            session.graph_resources.restore_embedded(resource.uid, filename, relink=True)
            count = session.graph_resources.apply_resource_to_scene(session.scene, resource.uid, touch=True)
            self._mark_resource_library_dirty(session)
            self.statusBar().showMessage(
                f"Restored and relinked {resource.name} for {count} node{'s' if count != 1 else ''}.", 4500
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could not restore resource", str(exc))

    def _explorer_reveal_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        path = resource.resolved_path(session.current_path) if resource is not None and session is not None else None
        if path is not None and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _explorer_rename_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        if session is None or resource is None:
            return
        name, accepted = QInputDialog.getText(self, "Rename graph resource", "Resource name:", text=resource.name)
        if accepted and session.graph_resources.rename_resource(resource.uid, str(name)):
            self._mark_resource_library_dirty(session)

    def _explorer_move_resource(self, session_uid: str, resource_uid: str, folder_uid: str) -> None:
        session = self._resource_session(session_uid)
        if session is not None and session.graph_resources.move_resource(resource_uid, folder_uid):
            self._mark_resource_library_dirty(session)

    def _explorer_remove_resource(self, session_uid: str, resource_uid: str) -> None:
        session = self._resource_session(session_uid)
        resource = session.graph_resources.by_id(resource_uid) if session is not None else None
        if session is None or resource is None:
            return
        counts = session.graph_resources.reference_counts(session.scene)
        if counts.get(str(resource_uid), 0):
            QMessageBox.information(
                self,
                "Resource still in use",
                "Delete or relink every node using this resource before removing it.",
            )
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Remove unused resource?")
        box.setText(f"Remove '{resource.name}' from this graph?")
        if resource.embedded_data and not resource.source_path:
            box.setInformativeText(
                "This is the graph's only embedded copy. Removing it discards those source bytes when the graph is saved."
            )
        else:
            box.setInformativeText("The linked file on disk will not be deleted.")
        remove_button = box.addButton("Remove Resource", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if (
            box.clickedButton() is remove_button
            and session.graph_resources.remove_resource(resource_uid, referenced=0)
        ):
            self._mark_resource_library_dirty(session)

    def _mark_document_dirty(self) -> None:
        if self._switching_graph_session:
            return
        self._document_dirty = True
        session = self._active_graph_session()
        if session is not None:
            session.document_dirty = True
        self._update_dirty_state()
        self._schedule_autosave()

    def _update_dirty_state(self) -> None:
        try:
            graph_dirty = not self.scene.undo_stack.isClean()
        except RuntimeError:
            return
        self._set_dirty(graph_dirty or self._document_dirty or self._recovered_dirty)

    def _backend_changed(self, index: int) -> None:
        preference = str(self.backend_combo.itemData(index) or "auto")
        self.evaluator.set_backend_preference(preference)
        self.settings.setValue("render/backend", preference)
        self._clear_presentation_caches()
        self._refresh_backend_status()
        self._schedule_preview()
        self._schedule_3d_preview()

    def _refresh_backend_status(self) -> None:
        info = self.evaluator.backend_info()
        if info["preference"] == "cpu":
            self.backend_status.setText("● CPU mode")
            self.backend_status.setToolTip("CPU reference renderer forced by the user")
        elif info["gpu_available"]:
            self.backend_status.setText("● GPU ready")
            self.backend_status.setToolTip(str(info["gpu_detail"]))
        else:
            self.backend_status.setText("● CPU fallback")
            self.backend_status.setToolTip(str(info["gpu_detail"]))

    def _clear_render_cache(self) -> None:
        self._cancel_interactive_previews()
        self.evaluator.clear_cache()
        self._clear_presentation_caches()
        for node in self.scene.nodes.values():
            if node.thumbnail_enabled:
                node.clear_thumbnail_result(keep_image=False, state="not_evaluated", message="Not evaluated")
        self.statusBar().showMessage(
            "Graph, geometry, presentation, thumbnail and 3D renderer caches cleared", 3500
        )
        self._schedule_preview()
        self._schedule_3d_preview()
        self._schedule_thumbnail_refresh()

    def _set_cache_budget(self) -> None:
        current = int(self.settings.value("render/gpu_budget_mb", 512))
        value, accepted = QInputDialog.getInt(
            self,
            "Render Cache Budget",
            "GPU cache budget (MiB):",
            current,
            64,
            16384,
            64,
        )
        if not accepted:
            return
        self.settings.setValue("render/gpu_budget_mb", value)
        cpu_value = max(value // 2, 128)
        self.evaluator.set_memory_budget_mb(value, cpu_value)
        self._material_result_cache.set_budget(cpu_value * 1024 * 1024)
        self._geometry_result_cache.set_budget(max(cpu_value, 256) * 1024 * 1024)
        self.preview_3d_panel.set_material_cache_budget_mb(value)
        self.statusBar().showMessage(
            f"Render cache budget set to {value} MiB graph/material GPU + resident geometry / "
            f"{cpu_value} MiB graph/material CPU",
            5000,
        )

    def _show_gpu_diagnostics(self) -> None:
        info = self.evaluator.backend_info()
        stats = self.evaluator.cache_stats()
        gpu = stats["gpu"]
        cpu = stats["cpu"]
        preview_cache = self._preview_result_cache.stats()
        thumbnail_cache = self._thumbnail_cache.stats()
        material_cpu_cache = self._material_result_cache.stats()
        geometry_cpu_cache = self._geometry_result_cache.stats()
        material_gpu_cache = self.preview_3d_panel.material_cache_stats()
        geometry_gpu_cache = self.preview_3d_panel.canvas.renderer.geometry_cache_stats()
        supported = "<br>".join(info["supported_gpu_nodes"]) or "None"
        QMessageBox.information(
            self,
            "GPU / Renderer Diagnostics",
            f"<b>Renderer preference:</b> {info['preference'].upper()}<br>"
            f"<b>WebGPU available:</b> {'Yes' if info['gpu_available'] else 'No'}<br>"
            f"<b>Adapter:</b> {info['gpu_detail']}<br><br>"
            f"<b>Graph GPU cache:</b> {gpu.entries} entries, {gpu.bytes_used / 1048576:.1f} / {gpu.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>Graph CPU cache:</b> {cpu.entries} entries, {cpu.bytes_used / 1048576:.1f} / {cpu.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>2D presentation cache:</b> {preview_cache.entries} entries, {preview_cache.bytes_used / 1048576:.1f} / {preview_cache.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>Node thumbnail cache:</b> {thumbnail_cache.entries} entries, {thumbnail_cache.bytes_used / 1048576:.1f} / {thumbnail_cache.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>Resolved material CPU cache:</b> {material_cpu_cache.entries} entries, {material_cpu_cache.bytes_used / 1048576:.1f} / {material_cpu_cache.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>Procedural geometry CPU cache:</b> {geometry_cpu_cache.entries} meshes, {geometry_cpu_cache.bytes_used / 1048576:.1f} / {geometry_cpu_cache.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>3D renderer material cache:</b> {material_gpu_cache.entries} sets, {material_gpu_cache.bytes_used / 1048576:.1f} / {material_gpu_cache.budget_bytes / 1048576:.0f} MiB<br>"
            f"<b>3D renderer geometry cache:</b> {geometry_gpu_cache.entries} meshes, {geometry_gpu_cache.bytes_used / 1048576:.1f} / {geometry_gpu_cache.budget_bytes / 1048576:.0f} MiB<br><br>"
            f"<b>Current document:</b> {self.document.width} × {self.document.height} · {self.document.working_precision}<br>"
            f"<b>GPU physical storage:</b> scalar R32Float · colour {'RGBA32Float' if self.document.texture_precision.value == 'rgba32f' else 'RGBA16Float'}<br>"
            f"<b>Two-component foundation:</b> RG32Float<br>"
            f"<b>3D preview:</b> {'Ready' if self.preview_3d_panel.available else 'Unavailable'} · "
            f"shared WebGPU device · {self.preview_3d_panel.canvas.renderer.mesh_summary}<br><br>"
            f"<b>WGSL texture nodes:</b><br>{supported}<br><br>"
            f"<b>CPU decode nodes:</b><br>Image Input (then uploaded for downstream GPU work)<br><br>"
            f"<b>3D material / geometry bridge:</b><br>Only authored channels are resolved. Recently focused materials retain resolved CPU maps and mipmapped renderer textures. Procedural meshes are cached by their own upstream branch revision and keep resident vertex/index buffers, so unrelated Material edits skip subdivision, mesh conversion and GPU upload. Direct graph-texture binding remains a future optimisation.",
        )

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = bool(dirty)
        session = self._active_graph_session()
        if session is not None:
            session.current_path = self.current_path.resolve() if self.current_path is not None else None
            session.document = self.document
            session.document_dirty = bool(self._document_dirty)
            session.recovered_dirty = bool(self._recovered_dirty)
            session.current_frame = int(self.current_frame)
            self._update_graph_explorer_entry(session.uid)
            name = session.name
        else:
            name = self.current_path.name if self.current_path else "Untitled.vfxgraph"
        marker = " *" if self.dirty else ""
        self.setWindowTitle(f"{name}{marker} — VFX Texture Lab")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes to the current graph?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        self._remove_autosave()
        return True

    def new_project(self) -> None:
        self._create_new_graph_session()

    @staticmethod
    def _migrate_project_data(data: dict) -> dict:
        """Upgrade older graph settings without losing authored output."""
        version = int(data.get("version", 0) or 0)
        if version < 6:
            for node_data in data.get("nodes", []):
                if node_data.get("type") != MainWindow.FLIPBOOK_NODE_TYPE:
                    continue
                parameters = node_data.setdefault("parameters", {})
                parameters.setdefault("layout", "Custom")
                parameters.setdefault("source_range", "Custom Frame Range")
                parameters.setdefault("sampling", "Consecutive Timeline Frames")
                parameters.setdefault("include_end_frame", False)
                parameters.setdefault("use_full_grid", True)
                columns = max(int(parameters.get("columns", 8)), 1)
                rows = max(int(parameters.get("rows", 8)), 1)
                parameters.setdefault("frame_count", columns * rows)
        if version < 9:
            for node_data in data.get("nodes", []):
                if node_data.get("type") in {"shape.shape", "shape.polygon", "shape.polygon_burst", "pattern.tile_sampler"}:
                    node_data.setdefault("parameters", {}).setdefault("rasterization", "Pixel Exact")
        if version < 10:
            for node_data in data.get("nodes", []):
                if node_data.get("type") not in {MainWindow.IMAGE_OUTPUT_NODE_TYPE, MainWindow.TEXTURE_SET_NODE_TYPE}:
                    continue
                parameters = node_data.setdefault("parameters", {})
                # 0.43.4 and earlier configured Quick Export with numeric
                # suffixing by default. The new normal behaviour is to update
                # the files owned by the same output node in place.
                if parameters.get("_quick_export_collision", "Add numeric suffix") == "Add numeric suffix":
                    parameters["_quick_export_collision"] = "Replace existing"
        if version < 15:
            for node_data in data.get("nodes", []):
                if node_data.get("type") != "pattern.tile_sampler":
                    continue
                parameters = node_data.setdefault("parameters", {})
                if str(parameters.get("offset_mode", "")) == "None":
                    parameters["offset_mode"] = "Every Second Row"
                    parameters["row_offset"] = 0.0
                else:
                    try:
                        offset = float(parameters.get("row_offset", 0.0))
                        if offset < 0.0:
                            parameters["row_offset"] = offset % 1.0
                    except (TypeError, ValueError):
                        parameters["row_offset"] = 0.0
        if version < 16:
            for node_data in data.get("nodes", []):
                if node_data.get("type") != "pattern.tile_sampler":
                    continue
                parameters = node_data.setdefault("parameters", {})
                parameters.pop("tile_value", None)
                parameters.pop("_legacy_luminance_model", None)
        if version < 18:
            # Displacement is a property of the 3D inspection mesh, not one
            # authored Material branch. Preserve the appearance of an old graph
            # by moving the active material's legacy values into viewport state,
            # then remove the hidden per-material copies from every material node.
            moved_names = ("displacement_amount", "height_midpoint", "invert_height")
            nodes = [entry for entry in data.get("nodes", []) if isinstance(entry, dict)]
            nodes_by_uid = {str(entry.get("uid", "")): entry for entry in nodes if str(entry.get("uid", ""))}
            source_by_input = {
                (str(entry.get("target", "")), str(entry.get("input", ""))): str(entry.get("source", ""))
                for entry in data.get("connections", [])
                if isinstance(entry, dict)
            }

            def source(uid: str, input_name: str) -> str | None:
                value = source_by_input.get((str(uid), str(input_name)), "")
                return value or None

            def legacy_settings_source(uid: str | None, visited: set[str] | None = None) -> dict | None:
                if not uid or uid not in nodes_by_uid:
                    return None
                visited = set() if visited is None else set(visited)
                if uid in visited:
                    return None
                visited.add(uid)
                node_data = nodes_by_uid[uid]
                node_type = str(node_data.get("type", ""))
                parameters = node_data.get("parameters")
                parameters = parameters if isinstance(parameters, dict) else {}
                if node_type == MainWindow.MATERIAL_NODE_TYPE:
                    return parameters
                if node_type == "material.override":
                    if bool(parameters.get("override_material_settings", False)):
                        return parameters
                    return legacy_settings_source(source(uid, "Material"), visited)
                if node_type == "material.blend":
                    preferred = str(parameters.get("settings_source", "Background"))
                    fallback = "Foreground" if preferred == "Background" else "Background"
                    return (
                        legacy_settings_source(source(uid, f"{preferred} Material"), visited)
                        or legacy_settings_source(source(uid, f"{fallback} Material"), visited)
                    )
                if node_type == "material.switch":
                    choice = "B" if str(parameters.get("selected_material", "A")) == "B" else "A"
                    fallback = "A" if choice == "B" else "B"
                    return (
                        legacy_settings_source(source(uid, f"Material {choice}"), visited)
                        or legacy_settings_source(source(uid, f"Material {fallback}"), visited)
                    )
                if node_type == MainWindow.TEXTURE_SET_NODE_TYPE:
                    return legacy_settings_source(source(uid, "Material"), visited)
                if node_type == "graph.output":
                    return legacy_settings_source(source(uid, "Value"), visited)
                if node_type == "graph.send":
                    return legacy_settings_source(source(uid, "Input"), visited)
                if node_type == "graph.receive":
                    sender_uid = str(parameters.get("sender_uid", ""))
                    return legacy_settings_source(source(sender_uid, "Input"), visited)
                return None

            legacy_parameters = legacy_settings_source(str(data.get("active_node", "")) or None)
            if legacy_parameters is None:
                legacy_parameters = next((
                    entry.get("parameters")
                    for entry in nodes
                    if entry.get("type") in {MainWindow.MATERIAL_NODE_TYPE, "material.override"}
                    and isinstance(entry.get("parameters"), dict)
                    and any(name in entry["parameters"] for name in moved_names)
                ), None)

            viewport = data.get("viewport_3d")
            if not isinstance(viewport, dict):
                viewport = {}
                data["viewport_3d"] = viewport
            viewport_values = viewport.get("settings")
            if not isinstance(viewport_values, dict):
                # Very early viewport files stored settings flat. Keep those
                # values while moving them into the current nested structure.
                viewport_values = {
                    key: value for key, value in viewport.items()
                    if key not in {"settings", "camera"}
                }
                viewport["settings"] = viewport_values
            if isinstance(legacy_parameters, dict):
                for name in moved_names:
                    if name in legacy_parameters and name not in viewport_values:
                        viewport_values[name] = legacy_parameters[name]

            for entry in nodes:
                if entry.get("type") not in {MainWindow.MATERIAL_NODE_TYPE, "material.override"}:
                    continue
                parameters = entry.get("parameters")
                if not isinstance(parameters, dict):
                    continue
                for name in moved_names:
                    parameters.pop(name, None)
        migrate_project_resources(data)
        data["version"] = 20
        return data

    def _graph_dialog_directories(self) -> list[Path]:
        locations: list[Path] = []
        if self.current_path is not None:
            locations.append(self.current_path.parent)
        raw_recent = self.settings.value("files/recent_graph_directories", [], list)
        for value in raw_recent or []:
            if str(value):
                locations.append(Path(str(value)).expanduser())
        for location in (
            QStandardPaths.StandardLocation.DocumentsLocation,
            QStandardPaths.StandardLocation.DesktopLocation,
            QStandardPaths.StandardLocation.DownloadLocation,
        ):
            value = QStandardPaths.writableLocation(location)
            if value:
                locations.append(Path(value))
        locations.extend((Path.home(), Path.cwd()))
        unique: list[Path] = []
        seen: set[str] = set()
        for location in locations:
            try:
                resolved = location.expanduser().resolve()
            except Exception:
                continue
            key = str(resolved)
            if key in seen or not resolved.is_dir():
                continue
            seen.add(key)
            unique.append(resolved)
        return unique

    def _remember_graph_directory(self, path: Path) -> None:
        directory = path.expanduser().resolve().parent if path.suffix else path.expanduser().resolve()
        recent = [str(directory)]
        for existing in self._graph_dialog_directories():
            value = str(existing)
            if value != str(directory) and value not in recent:
                recent.append(value)
        self.settings.setValue("files/last_graph_directory", str(directory))
        self.settings.setValue("files/recent_graph_directories", recent[:8])

    def _choose_graph_path(self, *, save: bool) -> Path | None:
        remembered = Path(str(self.settings.value("files/last_graph_directory", "") or "")).expanduser()
        if self.current_path is not None:
            initial_directory = self.current_path.parent
        elif remembered.is_dir():
            initial_directory = remembered
        else:
            documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            initial_directory = Path(documents) if documents else Path.home()

        dialog = QFileDialog(self, "Save graph" if save else "Open graph", str(initial_directory))
        dialog.setNameFilters(
            ["VFX Texture Graph (*.vfxgraph)"]
            + ([] if save else ["VFX Texture Package (*.vfxpackage)", "JSON files (*.json)"])
        )
        dialog.selectNameFilter("VFX Texture Graph (*.vfxgraph)")
        dialog.setDefaultSuffix("vfxgraph")
        dialog.setAcceptMode(
            QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen
        )
        dialog.setFileMode(
            QFileDialog.FileMode.AnyFile if save else QFileDialog.FileMode.ExistingFile
        )
        dialog.setViewMode(QFileDialog.ViewMode.Detail)
        directories = self._graph_dialog_directories()
        dialog.setSidebarUrls([QUrl.fromLocalFile(str(path)) for path in directories[:10]])
        dialog.setHistory([str(path) for path in directories[:12]])
        if save:
            dialog.selectFile(self.current_path.name if self.current_path is not None else "Untitled.vfxgraph")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = dialog.selectedFiles()
        if not selected:
            return None
        path = Path(selected[0]).expanduser()
        if save and path.suffix.lower() != ".vfxgraph":
            path = path.with_suffix(".vfxgraph")
        self._remember_graph_directory(path)
        return path

    def _poll_linked_graph_assets(self) -> None:
        if self._loading:
            return
        all_changes: list[tuple[str, str]] = []
        for session in self._graph_sessions.values() or [self._active_graph_session()]:
            if session is None:
                continue
            changes = session.scene.refresh_linked_graph_assets()
            if changes:
                all_changes.extend(changes)
                self._update_graph_explorer_entry(session.uid)
        if not all_changes:
            return
        self.library_panel.rebuild()
        reloaded = sum(1 for _uid, state in all_changes if state == "reloaded")
        missing = sum(1 for _uid, state in all_changes if state == "missing")
        failed = sum(1 for _uid, state in all_changes if state == "error")
        parts = []
        if reloaded:
            parts.append(f"reloaded {reloaded} linked graph asset{'s' if reloaded != 1 else ''}")
        if missing:
            parts.append(f"{missing} missing source{'s' if missing != 1 else ''}")
        if failed:
            parts.append(f"{failed} reload failure{'s' if failed != 1 else ''}")
        if parts:
            self.statusBar().showMessage("Graph assets: " + ", ".join(parts), 5000)

    def _load_project_path(self, path: Path) -> None:
        data = self._migrate_project_data(json.loads(path.read_text(encoding="utf-8")))
        self._loading = True
        try:
            self.document = DocumentSettings.from_dict(data.get("document"))
            self.graph_asset = GraphAssetMetadata.from_dict(
                data.get("graph_asset"), default_name=path.stem, created_with=__version__
            )
            self.export_profiles = ExportProfileLibrary.from_dict(data.get("export_profiles"))
            self.graph_resources = GraphResourceLibrary.from_dict(data.get("resources"))
            self.current_frame = 0
            self.scene.default_tiling = self.document.default_tiling
            self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
            self.scene.canvas_default_size = (self.document.width, self.document.height)
            self.timeline_panel.set_document(self.document)
            self.timeline_panel.set_frame(0, emit=False)
            self._update_playback_interval()
            self.preview_3d_panel.load_project_state(data.get("viewport_3d"))
            self.scene.from_dict(data)
        finally:
            self._loading = False
        self.current_path = path
        self.scene.undo_stack.clear()
        self.scene.undo_stack.setClean()
        self._document_dirty = False
        self._recovered_dirty = False
        self.resolution_combo.blockSignals(True)
        self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
        self.resolution_combo.blockSignals(False)
        self._refresh_document_summary()
        self._set_dirty(False)
        self.graph_view.fitInView(
            self.scene.content_bounds().adjusted(-120, -120, 120, 120),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.graph_view._refresh_scene_bounds()
        session = self._active_graph_session()
        if session is not None:
            session.document = self.document
            session.graph_asset = self.graph_asset
            session.export_profiles = self.export_profiles
            session.graph_resources = self.graph_resources
            session.current_path = path.resolve()
            session.document_dirty = False
            session.recovered_dirty = False
            session.current_frame = 0
            session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
            self._update_graph_explorer_entry(session.uid)
        self._refresh_autosave_after_save()
        if session is not None:
            self._inspect_graph_session(session.uid)

    def _edit_graph_asset_thumbnail(self, source_path: str) -> None:
        path = Path(str(source_path or "")).expanduser()
        self._open_graph_asset_source(str(path))
        session = self._active_graph_session()
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if session is not None and session.current_path == resolved:
            self._inspect_graph_session(session.uid)
            self.statusBar().showMessage(
                "Use the Thumbnail section in the Inspector to capture, import or clear this asset thumbnail.",
                6000,
            )

    def _open_graph_asset_source(self, source_path: str) -> None:
        text = str(source_path or "")
        if text.startswith("session:"):
            self.activate_graph_session(text.split(":", 1)[1])
            return
        if text.startswith("embedded:"):
            self._open_embedded_graph_instance(text.split(":", 1)[1])
            return
        path = Path(text).expanduser()
        if not path.is_file():
            QMessageBox.warning(self, "Missing graph asset", f"The linked source could not be found:\n{path}")
            return
        resolved = path.resolve()
        for uid, session in self._graph_sessions.items():
            if session.current_path == resolved:
                self.activate_graph_session(uid)
                return
        try:
            self._open_project_path_in_new_session(resolved)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open graph asset", str(exc))

    def _open_embedded_graph_instance(self, node_uid: str) -> None:
        parent = self._active_graph_session()
        if parent is None:
            return
        node = parent.scene.nodes.get(str(node_uid))
        if node is None or node.definition.type_id != GRAPH_INSTANCE_TYPE:
            QMessageBox.warning(self, "Missing graph instance", "The embedded Graph Instance no longer exists.")
            return
        existing_uid = str(node.parameters.get("_asset_session_uid", "")).strip()
        if existing_uid in self._graph_sessions:
            self.activate_graph_session(existing_uid)
            return
        data = node.parameters.get("_asset_embedded_graph")
        if not isinstance(data, dict):
            data = node.parameters.get("_asset_cached_graph")
        if not isinstance(data, dict):
            QMessageBox.warning(
                self, "Embedded graph unavailable",
                "This Graph Instance has no editable embedded or cached graph revision.",
            )
            return
        try:
            data = self._migrate_project_data(deepcopy(data))
            document = DocumentSettings.from_dict(data.get("document"))
            scene = GraphScene(self.registry, self)
            scene.default_tiling = document.default_tiling
            scene.default_geometric_rasterization = document.default_geometric_rasterization
            scene.canvas_default_size = (document.width, document.height)
            scene.from_dict(data)
            scene.undo_stack.clear()
            scene.undo_stack.setClean()
            interface = dict(node.parameters.get("_asset_interface", {}))
            asset_name = str(interface.get("name") or node.definition.name or "Embedded Graph")
            session = self._register_graph_session(
                scene,
                document,
                display_name=f"{asset_name} (Embedded).vfxgraph",
                graph_asset=GraphAssetMetadata.from_dict(
                    data.get("graph_asset"), default_name=asset_name, created_with=__version__
                ),
                export_profiles=ExportProfileLibrary.from_dict(data.get("export_profiles")),
                graph_resources=GraphResourceLibrary.from_dict(data.get("resources")),
            )
            session.viewport_state = deepcopy(data.get("viewport_3d") or {})
            session.current_frame = 0
            node.parameters["_asset_mode"] = "Session"
            node.parameters["_asset_session_uid"] = session.uid
            node.parameters["_asset_status"] = "Open embedded graph · live"
            node.parameters["_asset_cached_graph"] = deepcopy(data)
            node.parameters["_asset_embedded_graph"] = deepcopy(data)
            node.set_error(None)
            self._update_graph_explorer_entry(parent.uid)
            self.activate_graph_session(session.uid)
            self.graph_view.fitInView(
                self.scene.content_bounds().adjusted(-120, -120, 120, 120),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self.statusBar().showMessage(
                f"Opened embedded graph {asset_name}. Save As converts parent instances to linked sources; closing embeds the current revision.",
                6000,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not open embedded graph", str(exc))

    def _open_project_path_in_new_session(self, path: Path) -> GraphDocumentSession:
        resolved = path.expanduser().resolve()
        for session in self._graph_sessions.values():
            if session.current_path == resolved:
                self.activate_graph_session(session.uid)
                return session
        scene = GraphScene(self.registry, self)
        placeholder_document = DocumentSettings()
        session = self._register_graph_session(
            scene, placeholder_document, current_path=resolved, display_name=resolved.name
        )
        self.activate_graph_session(session.uid)
        try:
            self._load_project_path(resolved)
            self._stash_active_graph_session()
            self._bind_linked_instances_to_open_sessions()
            self._update_graph_explorer_entry(session.uid)
            self.statusBar().showMessage(f"Opened {resolved.name}", 3500)
            return session
        except Exception:
            self._remove_graph_session_without_prompt(session.uid)
            raise

    def open_project(self) -> None:
        path = self._choose_graph_path(save=False)
        if path is None:
            return
        if path.suffix.lower() == PACKAGE_EXTENSION:
            self._open_vfxpackage_path(path)
            return
        try:
            self._open_project_path_in_new_session(path)
        except Exception as exc:
            self._loading = False
            QMessageBox.critical(self, "Could not open graph", str(exc))

    def open_external_path(self, path: str | Path) -> bool:
        """Open a graph or package supplied by the OS/command line."""
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            return False
        if candidate.suffix.lower() == PACKAGE_EXTENSION:
            return self._open_vfxpackage_path(candidate)
        if candidate.suffix.lower() == VFXEXPORT_EXTENSION:
            try:
                incoming = read_vfxexport(candidate)
                target, installed, action = install_vfxexport(candidate, conflict="ask")
            except ExportTemplateLibraryError as exc:
                if "already exists" in str(exc):
                    box = QMessageBox(self)
                    box.setWindowTitle("Export template already installed")
                    box.setText(f"{incoming.name} already exists in the User Export Templates library.")
                    update = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
                    side = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
                    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
                    box.exec()
                    if box.clickedButton() is cancel or box.clickedButton() is None:
                        return False
                    mode = "update" if box.clickedButton() is update else "side-by-side"
                    try:
                        target, installed, action = install_vfxexport(candidate, conflict=mode)
                    except ExportTemplateLibraryError as nested:
                        QMessageBox.warning(self, "Could not install export template", str(nested))
                        return False
                else:
                    QMessageBox.warning(self, "Could not install export template", str(exc))
                    return False
            QMessageBox.information(self, "Export template installed", f"{installed.name} was {action}.\n\n{target}")
            return True
        try:
            self._open_project_path_in_new_session(candidate.resolve())
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could not open graph", str(exc))
            return False

    def export_self_contained_graph(self) -> bool:
        """Export the active graph as one portable file without modifying it."""
        session = self._active_graph_session()
        if session is None:
            QMessageBox.information(self, "No graph", "Open or create a graph first.")
            return False
        self._stash_active_graph_session()

        if session.current_path is not None:
            initial_directory = session.current_path.parent
            initial_name = f"{session.current_path.stem}-self-contained.vfxgraph"
        else:
            remembered = Path(str(self.settings.value("files/last_graph_directory", "") or "")).expanduser()
            if remembered.is_dir():
                initial_directory = remembered
            else:
                documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                initial_directory = Path(documents) if documents else Path.home()
            base = re.sub(r"(?i)\.vfxgraph$", "", session.name) or "Untitled"
            initial_name = f"{base}-self-contained.vfxgraph"

        dialog = QFileDialog(self, "Export Self-Contained Graph", str(initial_directory / initial_name))
        dialog.setNameFilter("VFX Texture Graph (*.vfxgraph)")
        dialog.setDefaultSuffix("vfxgraph")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.selectFile(initial_name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        selected = dialog.selectedFiles()
        if not selected:
            return False
        destination = Path(selected[0]).expanduser()
        if destination.suffix.lower() != ".vfxgraph":
            destination = destination.with_suffix(".vfxgraph")
        if session.current_path is not None:
            try:
                if destination.resolve() == session.current_path.resolve():
                    QMessageBox.warning(
                        self,
                        "Choose a separate export file",
                        "Self-contained export is deliberately non-destructive. Choose a different filename so the open source graph is not replaced.",
                    )
                    return False
            except OSError:
                pass
        self._remember_graph_directory(destination)

        try:
            # Keep Session-mode instances intact long enough for the converter
            # to consume their current live cached revision. This ensures an
            # unsaved child edit is exported rather than an older disk copy.
            source_data = self._project_data_for_session(
                session, serialise_live_instances=False
            )
            portable, report = build_self_contained_graph(
                source_data, owner_path=session.current_path, app_version=__version__
            )
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(portable, indent=2), encoding="utf-8")
            written = json.loads(temporary.read_text(encoding="utf-8"))
            validate_self_contained_graph(written)
            temporary.replace(destination)
        except SelfContainedGraphError as exc:
            QMessageBox.warning(
                self,
                "Could not create self-contained graph",
                f"The source graph was not changed. Resolve the dependency below and try again.\n\n{exc}",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(self, "Could not create self-contained graph", str(exc))
            return False

        details = "\n".join(report.summary_lines())
        if report.warnings:
            details += "\n\nRecovery notes:\n" + "\n".join(
                f"• {warning}" for warning in report.warnings[:8]
            )
            if len(report.warnings) > 8:
                details += f"\n• {len(report.warnings) - 8} more recovery note(s)"
        QMessageBox.information(
            self,
            "Self-contained graph created",
            f"Created and validated:\n{destination}\n\n{details}\n\nThe open source graph was left unchanged.",
        )
        self.statusBar().showMessage(
            f"Exported portable graph {destination.name}", 5000
        )
        return True

    def _choose_vfxpackage_path(self, *, save: bool, title: str) -> Path | None:
        remembered = Path(str(self.settings.value("files/last_package_directory", "") or "")).expanduser()
        if self.current_path is not None:
            initial_directory = self.current_path.parent
        elif remembered.is_dir():
            initial_directory = remembered
        else:
            downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            initial_directory = Path(downloads) if downloads else Path.home()
        dialog = QFileDialog(self, title, str(initial_directory))
        dialog.setNameFilter("VFX Texture Package (*.vfxpackage)")
        dialog.setDefaultSuffix("vfxpackage")
        dialog.setAcceptMode(
            QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen
        )
        dialog.setFileMode(
            QFileDialog.FileMode.AnyFile if save else QFileDialog.FileMode.ExistingFile
        )
        if save:
            session = self._active_graph_session()
            base = session.current_path.stem if session and session.current_path else (
                re.sub(r"(?i)\.vfxgraph$", "", session.name) if session else "Graph Asset"
            )
            dialog.selectFile(f"{base or 'Graph Asset'}.vfxpackage")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = dialog.selectedFiles()
        if not selected:
            return None
        path = Path(selected[0]).expanduser()
        if save and path.suffix.lower() != PACKAGE_EXTENSION:
            path = path.with_suffix(PACKAGE_EXTENSION)
        self.settings.setValue("files/last_package_directory", str(path.resolve().parent))
        return path

    def _install_export_template_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Install Export Template",
            str(Path.home()),
            "VFX Export Template (*.vfxexport)",
        )
        if not path:
            return False
        try:
            incoming = read_vfxexport(path)
            try:
                target, installed, action = install_vfxexport(path, conflict="ask")
            except ExportTemplateLibraryError as exc:
                if "already exists" not in str(exc):
                    raise
                box = QMessageBox(self)
                box.setWindowTitle("Export template already installed")
                box.setText(
                    f"{incoming.name} {incoming.asset_version} has the same stable Template ID as an installed template."
                )
                box.setInformativeText("Update replaces the installed definition. Side by Side gives the incoming copy a new identity.")
                update = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
                side = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
                cancel = box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() is cancel or box.clickedButton() is None:
                    return False
                mode = "update" if box.clickedButton() is update else "side-by-side"
                target, installed, action = install_vfxexport(path, conflict=mode)
        except ExportTemplateLibraryError as exc:
            QMessageBox.warning(self, "Could not install export template", str(exc))
            return False
        QMessageBox.information(
            self,
            "Export template installed",
            f"{installed.name} {installed.asset_version} was {action}.\n\n{target}\n\nIt is now available when editing export targets or custom templates.",
        )
        return True

    def _install_package_export_templates(self, path: Path, info) -> tuple[int, int]:
        if not info.export_templates:
            return 0, 0
        templates = read_packaged_export_templates(path, info)
        installed = 0
        skipped = 0
        for template in templates:
            try:
                install_template_object(template, conflict="reject")
                installed += 1
            except ExportTemplateLibraryError as exc:
                if "already exists" not in str(exc):
                    skipped += 1
                    continue
                box = QMessageBox(self)
                box.setWindowTitle("Export template conflict")
                box.setText(
                    f"The package includes {template.name} {template.asset_version}, but a template with the same stable ID is already installed."
                )
                update = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
                side = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
                skip = box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() is update:
                    install_template_object(template, conflict="update")
                    installed += 1
                elif box.clickedButton() is side:
                    install_template_object(template, conflict="side-by-side")
                    installed += 1
                else:
                    skipped += 1
        return installed, skipped

    def export_vfxpackage(self) -> bool:
        """Create a validated installable package from the active graph."""
        session = self._active_graph_session()
        if session is None:
            QMessageBox.information(self, "No graph", "Open or create a graph first.")
            return False
        self._stash_active_graph_session()
        include_sources_default = str(
            self.settings.value("packages/include_image_sources", "true")
        ).strip().casefold() not in {"0", "false", "no", "off"}
        include_templates_default = str(
            self.settings.value("packages/include_export_templates", "true")
        ).strip().casefold() not in {"0", "false", "no", "off"}
        options = VFXPackageExportOptionsDialog(
            include_image_sources=include_sources_default,
            include_export_templates=include_templates_default,
            parent=self,
        )
        if options.exec() != QDialog.DialogCode.Accepted:
            return False
        include_image_sources = options.include_image_source_files
        include_export_templates = options.include_export_template_files
        self.settings.setValue(
            "packages/include_image_sources", bool(include_image_sources)
        )
        self.settings.setValue(
            "packages/include_export_templates", bool(include_export_templates)
        )
        destination = self._choose_vfxpackage_path(
            save=True, title="Export VFX Package"
        )
        if destination is None:
            return False
        try:
            source_data = self._project_data_for_session(
                session, serialise_live_instances=False
            )
            info, report = create_vfxpackage(
                destination,
                source_data,
                owner_path=session.current_path,
                app_version=__version__,
                registry=self.registry,
                include_image_sources=include_image_sources,
                include_export_templates=include_export_templates,
            )
        except (VFXPackageError, SelfContainedGraphError) as exc:
            QMessageBox.warning(
                self,
                "Could not create VFX package",
                "The source graph was not changed. Resolve the problem below and try again.\n\n"
                + str(exc),
            )
            return False
        except Exception as exc:
            QMessageBox.critical(self, "Could not create VFX package", str(exc))
            return False

        details = "\n".join(report.summary_lines())
        if report.warnings:
            details += "\n\nRecovery notes:\n" + "\n".join(
                f"• {warning}" for warning in report.warnings[:8]
            )
        QMessageBox.information(
            self,
            "VFX package created",
            f"Created and validated:\n{info.source_path}\n\n"
            f"{info.name} · version {info.asset_version}\n"
            f"{len(info.files)} packaged file{'s' if len(info.files) != 1 else ''}\n\n"
            f"Image source files: {len(info.image_sources) if include_image_sources else 0}\n"
            f"Mesh source files: {len(info.mesh_sources)}\n"
            f"Image fallback mode: embedded copies retained\n"
            f"Export templates: {len(info.export_templates)} included as .vfxexport files\n\n"
            f"{details}\n\nThe open source graph was left unchanged.",
        )
        self.statusBar().showMessage(
            f"Exported VFX package {info.source_path.name}", 5000
        )
        return True

    def open_vfxpackage(self) -> bool:
        path = self._choose_vfxpackage_path(save=False, title="Open VFX Package")
        if path is None:
            return False
        return self._open_vfxpackage_path(path)

    def install_vfxpackage(self) -> bool:
        path = self._choose_vfxpackage_path(save=False, title="Install VFX Package")
        if path is None:
            return False
        try:
            info = inspect_vfxpackage(path)
        except VFXPackageError as exc:
            QMessageBox.warning(self, "Invalid VFX package", str(exc))
            return False
        return self._install_vfxpackage_path(path, info)

    def _open_vfxpackage_path(self, path: str | Path) -> bool:
        package_path = Path(path).expanduser().resolve()
        try:
            info = inspect_vfxpackage(package_path)
            thumbnail = read_package_thumbnail(package_path, info)
            existing = installed_packages(
                default_graph_asset_directory(), asset_id=info.asset_id
            )
        except VFXPackageError as exc:
            QMessageBox.warning(
                self,
                "Invalid VFX package",
                f"VFX Texture Lab refused to open this package.\n\n{exc}",
            )
            return False
        except Exception as exc:
            QMessageBox.critical(self, "Could not inspect VFX package", str(exc))
            return False

        dialog = VFXPackageDialog(
            info,
            thumbnail_bytes=thumbnail,
            installed_versions=[entry.asset_version for entry in existing],
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if dialog.choice == VFXPackageDialog.OPEN_TEMPORARILY:
            return self._open_vfxpackage_temporarily(package_path, info)
        if dialog.choice == VFXPackageDialog.EXTRACT_EDITABLE:
            return self._extract_vfxpackage_editable(package_path, info)
        if dialog.choice == VFXPackageDialog.INSTALL_LIBRARY:
            return self._install_vfxpackage_path(package_path, info)
        return False

    def _open_vfxpackage_temporarily(self, path: Path, info) -> bool:
        if not self._ensure_package_custom_nodes(path, info, prompt=True):
            return False
        try:
            data = read_package_entry_graph(path, info)
            self._open_project_data_in_new_session(
                data, display_name=f"{info.name} (Package).vfxgraph"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not open VFX package", str(exc))
            return False
        self.statusBar().showMessage(
            "Opened package as an unsaved graph. Use Save As to create an editable copy.",
            7000,
        )
        return True

    @staticmethod
    def _package_folder_name(name: str) -> str:
        value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "").strip()).strip("-._")
        return value or "VFX-Package"

    def _extract_vfxpackage_editable(self, path: Path, info) -> bool:
        remembered = str(self.settings.value("files/last_package_extract_directory", "") or "")
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        initial = Path(remembered).expanduser() if remembered else (
            Path(documents) if documents else Path.home()
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Parent Folder for Editable Project",
            str(initial),
        )
        if not selected:
            return False
        parent = Path(selected).expanduser().resolve()
        destination = parent / self._package_folder_name(info.name)
        overwrite = False
        if destination.exists() and any(destination.iterdir()):
            answer = QMessageBox.question(
                self,
                "Replace existing extracted project?",
                f"The folder already contains files:\n{destination}\n\nReplace it with this package?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            overwrite = True
        try:
            _installed, entry = extract_vfxpackage(
                path, destination, overwrite=overwrite
            )
            self.settings.setValue("files/last_package_extract_directory", str(parent))
            if info.custom_nodes:
                custom_root = destination / "custom_nodes"
                self.package_manager.add_library(
                    custom_root, f"{info.name} Project Nodes"
                )
                self._reload_custom_nodes()
            self._open_project_path_in_new_session(entry)
        except Exception as exc:
            QMessageBox.critical(self, "Could not extract VFX package", str(exc))
            return False
        QMessageBox.information(
            self,
            "Editable project extracted",
            f"Extracted and validated:\n{destination}\n\nThe entry graph is now open as a normal editable project.",
        )
        return True

    def _ensure_package_custom_nodes(self, path: Path, info, *, prompt: bool) -> bool:
        if not info.custom_nodes:
            return True
        missing: list[dict] = []
        for record in info.custom_nodes:
            package_id = str(record.get("package_id") or "")
            definition = self.registry.get_optional(package_id)
            package = definition.package if definition is not None else None
            if (
                package is None
                or str(package.version) != str(record.get("version") or "")
                or str(package.revision) != str(record.get("revision") or "")
            ):
                missing.append(record)
        if not missing:
            return True
        if prompt:
            names = "\n".join(
                f"• {record.get('name') or record.get('package_id')} {record.get('version') or ''}"
                for record in missing
            )
            answer = QMessageBox.question(
                self,
                "Install bundled custom nodes?",
                "This graph requires custom node packages bundled inside the VFX package:\n\n"
                f"{names}\n\nInstall them into the managed Custom Node library before opening?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            with tempfile.TemporaryDirectory(prefix="vfxtl-package-nodes-") as temp_dir:
                archives = write_packaged_custom_node_archives(path, temp_dir, info)
                wanted = {str(record.get("package_id") or "") for record in missing}
                for record, archive in archives:
                    if str(record.get("package_id") or "") in wanted:
                        self.package_manager.install_archive(archive)
            self._reload_custom_nodes()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not install bundled custom nodes",
                str(exc),
            )
            return False
        return True

    def _install_vfxpackage_path(self, path: Path, info) -> bool:
        root = default_graph_asset_directory()
        existing = installed_packages(root, asset_id=info.asset_id)
        replace_directory = None
        side_by_side = False
        if existing:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Package already installed")
            versions = ", ".join(entry.asset_version for entry in existing)
            box.setText(
                f"{info.name} has the same Asset ID as an installed package.\n\n"
                f"Installed: {versions}\nIncoming: {info.asset_version}"
            )
            box.setInformativeText(
                "Update replaces one managed installation. Side by Side keeps both versions."
            )
            update_button = box.addButton("Update Installed", QMessageBox.ButtonRole.AcceptRole)
            side_button = box.addButton("Install Side by Side", QMessageBox.ButtonRole.ActionRole)
            cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_button or clicked is None:
                return False
            if clicked is update_button:
                selected_existing = existing[0]
                if len(existing) > 1:
                    labels = [
                        f"{entry.name} {entry.asset_version} — {entry.source_path.name}"
                        for entry in existing
                    ]
                    chosen, ok = QInputDialog.getItem(
                        self,
                        "Choose installed package",
                        "Installation to update:",
                        labels,
                        0,
                        False,
                    )
                    if not ok:
                        return False
                    selected_existing = existing[labels.index(chosen)]
                replace_directory = selected_existing.source_path
            elif clicked is side_button:
                side_by_side = True

        if not self._ensure_package_custom_nodes(path, info, prompt=False):
            return False
        install_templates = False
        if info.export_templates:
            answer = QMessageBox.question(
                self,
                "Install included export templates?",
                f"This package includes {len(info.export_templates)} reusable export template(s).\n\nInstall them into your User Export Templates library?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            install_templates = answer == QMessageBox.StandardButton.Yes
        try:
            installed_info, entry = install_package_archive(
                path,
                root,
                replace_directory=replace_directory,
                side_by_side=side_by_side,
            )
            self.library_panel.rebuild()
            template_installed, template_skipped = (
                self._install_package_export_templates(path, info) if install_templates else (0, 0)
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not install VFX package", str(exc))
            return False
        QMessageBox.information(
            self,
            "VFX package installed",
            f"Installed {installed_info.name} {installed_info.asset_version} into the managed Graph Asset library.\n\n"
            f"Entry graph:\n{entry}"
            + (f"\n\nExport templates installed: {template_installed}" if install_templates else "")
            + (f"\nTemplates skipped: {template_skipped}" if install_templates and template_skipped else ""),
        )
        self.statusBar().showMessage(
            f"Installed Graph Asset package {installed_info.name}", 5000
        )
        return True

    def _open_project_data_in_new_session(self, data: dict, *, display_name: str) -> GraphDocumentSession:
        """Open validated graph data as a clean unsaved Explorer document."""
        migrated = self._migrate_project_data(deepcopy(data))
        scene = GraphScene(self.registry, self)
        document = DocumentSettings.from_dict(migrated.get("document"))
        metadata = GraphAssetMetadata.from_dict(
            migrated.get("graph_asset"),
            default_name=Path(display_name).stem,
            created_with=__version__,
        )
        session = self._register_graph_session(
            scene,
            document,
            current_path=None,
            display_name=display_name,
            graph_asset=metadata,
            export_profiles=ExportProfileLibrary.from_dict(migrated.get("export_profiles")),
            graph_resources=GraphResourceLibrary.from_dict(migrated.get("resources")),
        )
        self.activate_graph_session(session.uid)
        self._loading = True
        try:
            self.document = document
            self.graph_asset = metadata
            self.export_profiles = ExportProfileLibrary.from_dict(migrated.get("export_profiles"))
            self.graph_resources = GraphResourceLibrary.from_dict(migrated.get("resources"))
            self.current_frame = 0
            self.scene.default_tiling = document.default_tiling
            self.scene.default_geometric_rasterization = document.default_geometric_rasterization
            self.scene.canvas_default_size = (document.width, document.height)
            self.timeline_panel.set_document(document)
            self.timeline_panel.set_frame(0, emit=False)
            self._update_playback_interval()
            self.preview_3d_panel.load_project_state(migrated.get("viewport_3d"))
            self.scene.from_dict(migrated)
        finally:
            self._loading = False
        self.current_path = None
        self.scene.undo_stack.clear()
        self.scene.undo_stack.setClean()
        self._document_dirty = False
        self._recovered_dirty = False
        session.document = self.document
        session.graph_asset = self.graph_asset
        session.export_profiles = self.export_profiles
        session.graph_resources = self.graph_resources
        session.current_path = None
        session.document_dirty = False
        session.recovered_dirty = False
        session.current_frame = 0
        session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
        self.resolution_combo.blockSignals(True)
        self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
        self.resolution_combo.blockSignals(False)
        self._refresh_document_summary()
        self._update_graph_explorer_entry(session.uid)
        self._update_dirty_state()
        self.graph_view.fitInView(
            self.scene.content_bounds().adjusted(-120, -120, 120, 120),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.graph_view._refresh_scene_bounds()
        self._inspect_graph_session(session.uid)
        return session

    def save_project(self) -> bool:
        if self.current_path is None:
            return self.save_project_as()
        return self._write_project(self.current_path)

    def save_project_as(self) -> bool:
        path = self._choose_graph_path(save=True)
        if path is None:
            return False
        self.current_path = path
        return self._write_project(path)

    def _write_project(self, path: Path) -> bool:
        try:
            session = self._active_graph_session()
            if session is not None:
                session.current_path = path.expanduser().resolve()
                session.document = self.document
                session.graph_asset = self.graph_asset
                session.document_dirty = self._document_dirty
                session.recovered_dirty = self._recovered_dirty
                session.current_frame = self.current_frame
                session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
                data = self._project_data_for_session(session)
            else:
                data = self._project_data()
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(path)
            self.current_path = path.resolve()
            self.scene.undo_stack.setClean()
            self._document_dirty = False
            self._recovered_dirty = False
            if session is not None:
                session.current_path = self.current_path
                session.document_dirty = False
                session.recovered_dirty = False
                session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
                self._update_graph_explorer_entry(session.uid)
            self._refresh_autosave_after_save()
            self._set_dirty(False)
            self.statusBar().showMessage(f"Saved {path.name}", 3500)
            if session is not None:
                self._bind_linked_instances_to_open_sessions()
                self._propagate_live_graph_source(session.uid)
            try:
                from .graph_asset_library import graph_asset_directories
                if any(self.current_path.is_relative_to(folder) for folder in graph_asset_directories(self.settings)):
                    self.library_panel.rebuild()
            except Exception:
                pass
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could not save graph", str(exc))
            return False

    def _project_data(self) -> dict:
        session = self._active_graph_session()
        if session is not None:
            session.document = self.document
            session.graph_asset = self.graph_asset
            session.export_profiles = self.export_profiles
            session.graph_resources = self.graph_resources
            session.current_path = self.current_path
            session.document_dirty = self._document_dirty
            session.recovered_dirty = self._recovered_dirty
            session.current_frame = self.current_frame
            session.viewport_state = deepcopy(self.preview_3d_panel.project_state())
            return self._project_data_for_session(session)
        self.graph_resources.capture_scene(self.scene)
        data = self.scene.to_dict()
        data["version"] = 20
        data["document"] = self.document.to_dict()
        data["graph_asset"] = self.graph_asset.to_dict()
        data["export_profiles"] = self.export_profiles.to_dict()
        self.graph_resources.capture_serialized_nodes(data.get("nodes", []))
        data["resources"] = self.graph_resources.to_dict()
        self.graph_resources.compact_serialized_nodes(data.get("nodes", []))
        data["viewport_3d"] = self.preview_3d_panel.project_state()
        return data

    def _any_graph_session_dirty(self) -> bool:
        return any(session.dirty for session in self._graph_sessions.values())

    def _schedule_autosave(self) -> None:
        if self._loading:
            return
        self._update_dirty_state()
        if self._any_graph_session_dirty():
            self.autosave_timer.start()

    def _write_autosave(self) -> None:
        if self._loading:
            return
        self._stash_active_graph_session()
        dirty_sessions = [session for session in self._graph_sessions.values() if session.dirty]
        if not dirty_sessions:
            self._remove_autosave()
            return
        try:
            timestamp = time.time()
            graphs = []
            for session in dirty_sessions:
                data = self._project_data_for_session(session)
                metadata = {
                    "timestamp": timestamp,
                    "original_path": str(session.current_path) if session.current_path else "",
                    "display_name": session.name,
                    "session_uid": session.uid,
                    "app_version": __version__,
                }
                data["_autosave"] = deepcopy(metadata)
                graphs.append({
                    "uid": session.uid,
                    "display_name": session.name,
                    "original_path": metadata["original_path"],
                    "data": data,
                })
            bundle = {
                "format": "vfx-texture-lab-autosave-session",
                "version": 1,
                "_autosave": {
                    "timestamp": timestamp,
                    "app_version": __version__,
                    "active_session_uid": self._active_graph_session_uid or "",
                    "graph_count": len(graphs),
                },
                "graphs": graphs,
            }
            temporary = self._autosave_path.with_suffix(self._autosave_path.suffix + ".tmp")
            temporary.write_text(json.dumps(bundle), encoding="utf-8")
            temporary.replace(self._autosave_path)
            self.recover_action.setEnabled(True)
        except Exception as exc:
            self.statusBar().showMessage(f"Autosave failed: {exc}", 6000)

    def _refresh_autosave_after_save(self) -> None:
        if self._any_graph_session_dirty():
            self._write_autosave()
        else:
            self._remove_autosave()

    def _remove_autosave(self) -> None:
        try:
            self._autosave_path.unlink(missing_ok=True)
        except OSError:
            pass
        if hasattr(self, "recover_action"):
            self.recover_action.setEnabled(False)

    def _read_autosave(self) -> dict | None:
        if not self._autosave_path.is_file():
            return None
        try:
            return json.loads(self._autosave_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._remove_autosave()
            return None

    @staticmethod
    def _autosave_graph_entries(payload: dict) -> list[dict]:
        if payload.get("format") == "vfx-texture-lab-autosave-session":
            return [
                dict(entry) for entry in payload.get("graphs", ())
                if isinstance(entry, dict) and isinstance(entry.get("data"), dict)
            ]
        if isinstance(payload, dict):
            metadata = dict(payload.get("_autosave", {}))
            return [{
                "uid": str(metadata.get("session_uid", "legacy")),
                "display_name": str(metadata.get("display_name", "Recovered Graph.vfxgraph")),
                "original_path": str(metadata.get("original_path", "")),
                "data": payload,
            }]
        return []

    @staticmethod
    def _autosave_entry_is_stale(entry: dict) -> bool:
        data = dict(entry.get("data", {}))
        metadata = dict(data.get("_autosave", {}))
        timestamp = float(metadata.get("timestamp", 0.0) or 0.0)
        original_text = str(entry.get("original_path") or metadata.get("original_path") or "")
        if not original_text:
            return False
        original = Path(original_text).expanduser()
        try:
            return original.is_file() and original.stat().st_mtime >= timestamp
        except OSError:
            return False

    def _offer_recovery(self) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName().lower() == "offscreen":
            return
        payload = self._read_autosave()
        if payload is None:
            return
        entries = [
            entry for entry in self._autosave_graph_entries(payload)
            if not self._autosave_entry_is_stale(entry)
        ]
        if not entries:
            self._remove_autosave()
            return
        timestamp = max(
            (float(dict(entry["data"].get("_autosave", {})).get("timestamp", 0.0) or 0.0) for entry in entries),
            default=0.0,
        )
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)) if timestamp else "an earlier session"
        count = len(entries)
        answer = QMessageBox.question(
            self,
            "Recover autosaved graphs?",
            f"VFX Texture Lab found {count} autosaved graph{'s' if count != 1 else ''} from {when}. Restore them into Graph Explorer now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._restore_autosave_entries(entries)
        else:
            self._remove_autosave()

    def _recover_autosave_manually(self) -> None:
        payload = self._read_autosave()
        if payload is None:
            QMessageBox.information(self, "No autosave", "There are no recoverable autosaved graphs.")
            return
        entries = [
            entry for entry in self._autosave_graph_entries(payload)
            if not self._autosave_entry_is_stale(entry)
        ]
        if not entries:
            self._remove_autosave()
            QMessageBox.information(self, "No autosave", "All autosaved graphs have already been saved more recently.")
            return
        self._restore_autosave_entries(entries)

    def _restore_autosave_entries(self, entries: list[dict]) -> None:
        recovered: list[str] = []
        self._remove_autosave()
        for entry in entries:
            data = entry.get("data")
            if not isinstance(data, dict):
                continue
            display_name = str(entry.get("display_name") or "Recovered Graph.vfxgraph")
            self._restore_autosave_data(deepcopy(data), display_name=display_name)
            recovered.append(display_name)
        if recovered:
            self.autosave_timer.start()
            self.statusBar().showMessage(
                f"Recovered {len(recovered)} graph{'s' if len(recovered) != 1 else ''} into Graph Explorer. Save them to keep the recovered work.",
                8000,
            )

    def _restore_autosave_data(self, data: dict, *, display_name: str | None = None) -> None:
        # Recovery is another open document in a multi-graph session; it must
        # never overwrite a graph that was just restored into Explorer.
        active = self._active_graph_session()
        if active is not None and (
            active.current_path is not None or active.dirty or len(self._graph_sessions) > 1
        ):
            self._create_new_graph_session()
        data = self._migrate_project_data(data)
        metadata = dict(data.get("_autosave", {}))
        self._loading = True
        try:
            self.document = DocumentSettings.from_dict(data.get("document"))
            default_asset_name = Path(display_name or "Recovered Graph").stem
            self.graph_asset = GraphAssetMetadata.from_dict(
                data.get("graph_asset"), default_name=default_asset_name, created_with=__version__
            )
            self.export_profiles = ExportProfileLibrary.from_dict(data.get("export_profiles"))
            self.graph_resources = GraphResourceLibrary.from_dict(data.get("resources"))
            self.current_frame = 0
            self.scene.default_tiling = self.document.default_tiling
            self.scene.default_geometric_rasterization = self.document.default_geometric_rasterization
            self.scene.canvas_default_size = (self.document.width, self.document.height)
            self.timeline_panel.set_document(self.document)
            self.timeline_panel.set_frame(0, emit=False)
            self._update_playback_interval()
            self.preview_3d_panel.load_project_state(data.get("viewport_3d"))
            self.scene.from_dict(data)
        finally:
            self._loading = False
        original = str(metadata.get("original_path", ""))
        candidate_path = Path(original).expanduser().resolve() if original else None
        duplicate_open = bool(
            candidate_path is not None
            and any(
                session.uid != self._active_graph_session_uid
                and session.current_path == candidate_path
                for session in self._graph_sessions.values()
            )
        )
        self.current_path = None if duplicate_open else candidate_path
        self.scene.undo_stack.clear()
        self.scene.undo_stack.setClean()
        self._document_dirty = False
        self._recovered_dirty = True
        self.resolution_combo.blockSignals(True)
        self.resolution_combo.setCurrentText(str(self.document.preview_max_dimension))
        self.resolution_combo.blockSignals(False)
        self._refresh_document_summary()
        session = self._active_graph_session()
        if session is not None:
            session.document = self.document
            session.graph_asset = self.graph_asset
            session.export_profiles = self.export_profiles
            session.graph_resources = self.graph_resources
            session.current_path = self.current_path
            session.document_dirty = False
            session.recovered_dirty = True
            if self.current_path is None:
                base_name = display_name or str(metadata.get("display_name", "Recovered Graph.vfxgraph"))
                session.display_name = f"Recovered {Path(base_name).name}"
            self._update_graph_explorer_entry(session.uid)
        self._update_dirty_state()
        self.graph_view.fitInView(
            self.scene.content_bounds().adjusted(-120, -120, 120, 120),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.graph_view._refresh_scene_bounds()
        self._schedule_preview()
        self.statusBar().showMessage("Recovered autosaved graph. Save it to keep the recovered work.", 7000)

    def _selected_group(self) -> GroupFrameItem | None:
        groups = self.scene.selected_groups()
        return groups[0] if len(groups) == 1 else None

    def _save_selected_group(self) -> None:
        group = self._selected_group()
        if group is None:
            QMessageBox.information(self, "Select one group", "Select a single group frame or collapsed group node first.")
            return
        self._save_group_to_library(group)

    def _save_group_to_library(self, group: GroupFrameItem) -> None:
        try:
            data = self.scene.group_to_asset(group)
        except ValueError as exc:
            QMessageBox.information(self, "Cannot save group", str(exc))
            return

        folder = user_node_directory()
        suggested = folder / f"{slugify_node_name(group.name)}.vfxnode"
        filename, _selected = QFileDialog.getSaveFileName(
            self,
            "Save reusable user node",
            str(suggested),
            "VFX User Node (*.vfxnode)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".vfxnode":
            path = path.with_suffix(".vfxnode")
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.library_panel.rebuild()
            self.statusBar().showMessage(f"Saved reusable node {path.name}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save user node", str(exc))

    def _open_user_library(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_node_directory())))

    def export_active_image(self) -> None:
        self.export_outputs()

    def _expanded_export_snapshot(
        self, snapshot: GraphSnapshot, node_uids: list[str] | tuple[str, ...]
    ) -> GraphSnapshot:
        expanded = snapshot
        for uid in node_uids:
            if uid not in expanded.nodes:
                continue
            expanded, _uid, _output = self.evaluator._expand_graph_instances(
                expanded, str(uid), "Image"
            )
        return expanded

    def _export_output_choices(self, snapshot: GraphSnapshot, output_nodes: list) -> list[ExportOutputChoice]:
        choices: list[ExportOutputChoice] = []
        for node in output_nodes:
            parameters = node.parameters
            name = str(parameters.get("name", node.definition.name)).strip() or node.definition.name
            preset = str(parameters.get("export_preset", "Auto from data type"))
            if node.definition.type_id == self.TEXTURE_SET_NODE_TYPE:
                preset = effective_export_template(parameters).name
            resolution = str(parameters.get("export_resolution", "Document"))
            kind = "Texture Set" if node.definition.type_id == self.TEXTURE_SET_NODE_TYPE else "Single Image"
            planned_snapshot = self._expanded_export_snapshot(snapshot, [node.uid])
            graph_name, graph_version = self._export_graph_context()
            planned = build_export_artifacts(
                planned_snapshot, [node.uid], self.document,
                graph_name=graph_name, graph_version=graph_version,
            )
            if planned:
                names = ", ".join(artifact.filename for artifact in planned[:4])
                if len(planned) > 4:
                    names += f", … +{len(planned) - 4}"
                summary = f"{preset} · {resolution} · {len(planned)} file{'s' if len(planned) != 1 else ''}: {names}"
            else:
                summary = f"{preset} · {resolution} · no connected exportable inputs"
            warnings = tuple(
                dict.fromkeys(
                    warning
                    for artifact in planned
                    for warning in artifact.warnings
                )
            )
            details = tuple(
                f"{artifact.relative_path}  ·  {artifact.options.format_name} {artifact.options.bit_depth}-bit  ·  "
                f"{artifact.options.channels} / {artifact.options.colour_encoding}  ·  {artifact.width} × {artifact.height}"
                for artifact in planned
            )
            choices.append(
                ExportOutputChoice(
                    uid=node.uid,
                    name=name,
                    kind=kind,
                    summary=summary,
                    enabled=bool(parameters.get("export_enabled", True)) and bool(planned),
                    filenames=tuple(artifact.relative_path for artifact in planned),
                    file_details=details,
                    warnings=warnings,
                )
            )
        return choices

    def _export_graph_context(self) -> tuple[str, str]:
        graph_name = str(getattr(self.graph_asset, "name", "") or (self.current_path.stem if self.current_path else "Graph"))
        graph_version = str(getattr(self.graph_asset, "version", "") or "1.0.0")
        return graph_name, graph_version

    def _multi_target_export_artifacts(
        self, snapshot: GraphSnapshot, node_uids: list[str], profile: ExportProfileSet
    ):
        graph_name, graph_version = self._export_graph_context()
        return build_multi_target_artifacts(
            snapshot, node_uids, self.document, profile,
            graph_name=graph_name, graph_version=graph_version,
        )

    def export_outputs(
        self,
        preferred_uids: list[str] | None = None,
        *,
        only_uids: set[str] | None = None,
        quick_setup_uid: str | None = None,
    ) -> None:
        output_nodes = [
            node for node in self.scene.nodes.values()
            if node.definition.type_id in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}
            and (not only_uids or node.uid in only_uids)
        ]
        if not output_nodes:
            QMessageBox.information(
                self,
                "No export outputs",
                "Add a Single Image Output or Texture Set Output node to define what should be written to disk.",
            )
            return

        snapshot = GraphSnapshot.from_scene(self.scene)
        choices = self._export_output_choices(snapshot, output_nodes)
        selected = set(preferred_uids or ())
        if not selected:
            selected = {
                node.uid for node in self.scene.selected_nodes()
                if node.definition.type_id in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}
                and (not only_uids or node.uid in only_uids)
            }
        if (
            not selected
            and self.scene.active_node is not None
            and self.scene.active_node.definition.type_id in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}
            and (not only_uids or self.scene.active_node.uid in only_uids)
        ):
            selected.add(self.scene.active_node.uid)

        quick_node = self.scene.nodes.get(str(quick_setup_uid or ""))
        quick_directory = ""
        quick_collision = "Replace existing"
        quick_open_folder = False
        if quick_node is not None:
            quick_directory = str(quick_node.parameters.get("_quick_export_directory", "")).strip()
            quick_collision = str(quick_node.parameters.get("_quick_export_collision", "Replace existing"))
            quick_open_folder = bool(quick_node.parameters.get("_quick_export_open_folder", False))

        configured_directory = quick_directory or str(self.settings.value("export/last_directory", ""))
        default_directory = (
            Path(configured_directory) if configured_directory
            else (self.current_path.parent if self.current_path else Path.home() / "Pictures")
        )
        remembered_open_folder = str(
            self.settings.value("export/open_folder_when_complete", "false")
        ).lower() in {"1", "true", "yes"}
        planning_snapshot = self._expanded_export_snapshot(snapshot, [node.uid for node in output_nodes])
        dialog_profiles = self.export_profiles
        if quick_node is not None and isinstance(quick_node.parameters.get("_quick_export_profile"), dict):
            quick_profile = ExportProfileSet.from_dict(quick_node.parameters.get("_quick_export_profile"))
            profiles = list(self.export_profiles.profiles)
            if quick_profile.profile_id not in {profile.profile_id for profile in profiles}:
                profiles.append(quick_profile)
            dialog_profiles = ExportProfileLibrary(quick_profile.profile_id, tuple(profiles))
        dialog = ExportDialog(
            choices,
            selected or None,
            default_directory,
            default_collision=quick_collision if quick_node is not None else "Replace existing",
            default_open_folder=quick_open_folder if quick_node is not None else remembered_open_folder,
            profile_library=dialog_profiles,
            plan_callback=lambda uids, profile: self._multi_target_export_artifacts(
                planning_snapshot, uids, profile
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request = dialog.request()
        updated_profiles = ExportProfileLibrary.from_dict(request.profile_library)
        if updated_profiles.to_dict() != self.export_profiles.to_dict():
            self.export_profiles = updated_profiles
            session = self._active_graph_session()
            if session is not None:
                session.export_profiles = updated_profiles
            self._mark_document_dirty()
        self.settings.setValue("export/last_directory", str(request.directory))
        self.settings.setValue("export/open_folder_when_complete", bool(request.open_folder))
        snapshot = self._expanded_export_snapshot(snapshot, request.node_uids)
        artifacts = self._multi_target_export_artifacts(snapshot, request.node_uids, request.profile())
        if not artifacts:
            QMessageBox.information(
                self,
                "Nothing to export",
                "The selected outputs are disabled or do not have any connected maps to write.",
            )
            return

        if not self._confirm_export_filename_conflicts(artifacts):
            return
        exported, errors, cancelled, skipped = self._execute_export_request(snapshot, artifacts, request)
        if quick_node is not None and exported and not errors and not cancelled:
            self._store_quick_export_settings(quick_node, request)
        self._report_export_result(request, exported, errors, cancelled, skipped)

    def _store_quick_export_settings(self, node, request: ExportRequest) -> None:
        if node is None or node.definition.type_id not in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}:
            return

        values = {
            "_quick_export_configured": True,
            "_quick_export_directory": str(request.directory),
            "_quick_export_collision": str(request.collision),
            "_quick_export_open_folder": bool(request.open_folder),
            "_quick_export_profile": request.profile().to_dict(),
            "_quick_export_profile_name": request.profile().name,
        }

        def apply() -> None:
            changed = False
            for name, value in values.items():
                if node.parameters.get(name) != value:
                    node.parameters[name] = value
                    changed = True
            if changed:
                self.scene._touch()

        self.scene.perform_action("Configure Quick Export", apply)
        if self.parameters_panel.item is node:
            QTimer.singleShot(0, lambda n=node: self.parameters_panel.set_item(n))

    def _edit_export_template(self, node_uid: str) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None or node.definition.type_id != self.TEXTURE_SET_NODE_TYPE:
            return
        dialog = ExportTemplateDialog(effective_export_template(node.parameters), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        template = dialog.result_template()

        def apply() -> None:
            node.parameters["_custom_export_template"] = template.to_dict()
            node.parameters["export_preset"] = CUSTOM_TEMPLATE_NAME
            self.scene._touch()

        self.scene.perform_action("Edit Export Template", apply)
        if self.parameters_panel.item is node:
            QTimer.singleShot(0, lambda n=node: self.parameters_panel.set_item(n))
        self.statusBar().showMessage(
            f"Using custom export template ‘{template.name}’ with {len(template.files)} file definition(s)",
            6000,
        )

    def _texture_set_quick_export(self, node_uid: str, force_setup: bool = False) -> None:
        """Quick-export either output-node type; name retained for signal compatibility."""
        node = self.scene.nodes.get(str(node_uid))
        if node is None or node.definition.type_id not in {self.IMAGE_OUTPUT_NODE_TYPE, self.TEXTURE_SET_NODE_TYPE}:
            return
        directory_text = str(node.parameters.get("_quick_export_directory", "")).strip()
        configured = bool(node.parameters.get("_quick_export_configured", False) and directory_text)
        if force_setup or not configured:
            self.export_outputs(
                [node.uid],
                only_uids={node.uid},
                quick_setup_uid=node.uid,
            )
            return

        directory = Path(directory_text).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.export_outputs(
                [node.uid],
                only_uids={node.uid},
                quick_setup_uid=node.uid,
            )
            return

        snapshot = GraphSnapshot.from_scene(self.scene)
        snapshot = self._expanded_export_snapshot(snapshot, [node.uid])
        profile = ExportProfileSet.from_dict(node.parameters.get("_quick_export_profile"))
        artifacts = self._multi_target_export_artifacts(snapshot, [node.uid], profile)
        if not artifacts:
            QMessageBox.information(
                self,
                "Nothing to export",
                (
                    "This Texture Set Output has no connected exportable maps."
                    if node.definition.type_id == self.TEXTURE_SET_NODE_TYPE
                    else "This Single Image Output has no connected image to export."
                ),
            )
            return
        request = ExportRequest(
            node_uids=[node.uid],
            directory=directory,
            collision=str(node.parameters.get("_quick_export_collision", "Replace existing")),
            open_folder=bool(node.parameters.get("_quick_export_open_folder", False)),
            profile_library=ExportProfileLibrary(profile.profile_id, (profile,)).to_dict(),
            profile_id=profile.profile_id,
        )
        if not self._confirm_export_filename_conflicts(artifacts):
            return
        exported, errors, cancelled, skipped = self._execute_export_request(snapshot, artifacts, request)
        self._report_export_result(request, exported, errors, cancelled, skipped)

    def _geometry_export(self, node_uid: str, force_setup: bool = False) -> None:
        node = self.scene.nodes.get(str(node_uid))
        if node is None or node.definition.type_id != "output.geometry":
            return
        snapshot = GraphSnapshot.from_scene(self.scene)
        result = self._geometry_evaluation_session(snapshot, final=True).evaluate(node.uid, "Geometry")
        if result.error or result.geometry is None:
            QMessageBox.warning(
                self,
                "Geometry export failed",
                result.error or "The Geometry Output has no connected mesh.",
            )
            return

        configured_path = str(node.parameters.get("_quick_export_path", "")).strip()
        destination = Path(configured_path).expanduser() if configured_path else None
        if force_setup or destination is None:
            output_name = str(node.parameters.get("name", "Geometry") or "Geometry")
            pattern = str(node.parameters.get("export_filename", "{name}") or "{name}")
            filename = pattern.replace("{name}", output_name)
            filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" .") or "Geometry"
            if not filename.lower().endswith(".obj"):
                filename += ".obj"
            start_directory = (
                destination.parent if destination is not None
                else (self.current_path.parent if self.current_path else Path.home() / "Documents")
            )
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Export Geometry",
                str(start_directory / filename),
                "Wavefront OBJ (*.obj)",
            )
            if not selected:
                return
            destination = Path(selected).expanduser()

        try:
            written = export_obj(
                result.geometry,
                destination,
                include_uvs=bool(node.parameters.get("include_uvs", True)),
                include_normals=bool(node.parameters.get("include_normals", True)),
                flip_v=bool(node.parameters.get("flip_v", False)),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Geometry export failed", f"{type(exc).__name__}: {exc}")
            return

        remembered = str(written)
        def apply() -> None:
            changed = False
            for name, value in {
                "_quick_export_configured": True,
                "_quick_export_path": remembered,
            }.items():
                if node.parameters.get(name) != value:
                    node.parameters[name] = value
                    changed = True
            if changed:
                self.scene._touch()

        self.scene.perform_action("Configure Geometry Export", apply)
        if self.parameters_panel.item is node:
            QTimer.singleShot(0, lambda n=node: self.parameters_panel.set_item(n))
        self.statusBar().showMessage(
            f"Exported {result.geometry.vertex_count:,} vertices and {result.geometry.triangle_count:,} triangles to {written}",
            7000,
        )

    def _confirm_export_filename_conflicts(self, artifacts) -> bool:
        conflicts = export_filename_conflicts(list(artifacts))
        if not conflicts:
            return True

        lines: list[str] = []
        for filename, group in list(conflicts.items())[:8]:
            owners = ", ".join(dict.fromkeys(artifact.owner_name for artifact in group))
            lines.append(f"• {filename} ← {owners}")
        if len(conflicts) > 8:
            lines.append(f"• …and {len(conflicts) - 8} more")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Duplicate export filenames")
        box.setText("Two or more planned export files would use the same filename.")
        box.setInformativeText(
            "VFX Texture Lab will append a stable output-node tag to only the conflicting files, so repeated exports "
            "overwrite the same safe paths instead of creating new _2, _3, … copies. Rename the output nodes or their "
            "file-name templates for cleaner filenames.\n\n" + "\n".join(lines)
        )
        continue_button = box.addButton("Export with safe names", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(continue_button)
        box.exec()
        return box.clickedButton() is continue_button

    def _execute_export_request(
        self,
        snapshot: GraphSnapshot,
        artifacts,
        request: ExportRequest,
    ) -> tuple[list[Path], list[str], bool, int]:
        self._cancel_interactive_previews()
        unique_source_keys = {
            (source.node_uid, source.output_name, artifact.width, artifact.height)
            for artifact in artifacts
            for _source_name, source in artifact.sources
        }
        total_steps = max(len(unique_source_keys) + len(artifacts), 1)
        progress = QProgressDialog("Preparing graph exports…", "Cancel", 0, total_steps, self)
        progress.setWindowTitle("Export Outputs")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        exported: list[Path] = []
        errors: list[str] = []
        skipped = 0
        reserved: set[str] = set()
        step = 0
        cancelled = False
        evaluation_cache: dict[tuple[str, str, int, int], np.ndarray] = {}
        evaluation_failures: dict[tuple[str, str, int, int], str] = {}

        def pump_export_progress(_current: int, _total: int, message: str) -> None:
            if message:
                progress.setLabelText(str(message))
            QApplication.processEvents()

        planned_filenames = disambiguated_export_filenames(list(artifacts))
        for artifact, planned_filename in zip(artifacts, planned_filenames, strict=True):
            if progress.wasCanceled():
                cancelled = True
                break
            destination = resolve_destination(request.directory, planned_filename, request.collision, reserved)
            if destination is None:
                skipped += 1
                step += 1
                progress.setValue(min(step, total_steps))
                continue

            images: dict[str, np.ndarray] = {}
            failed = False
            for source_name, source in artifact.sources:
                if progress.wasCanceled():
                    cancelled = True
                    failed = True
                    break
                cache_key = (source.node_uid, source.output_name, artifact.width, artifact.height)
                if cache_key in evaluation_failures:
                    errors.append(f"{artifact.label}: {evaluation_failures[cache_key]}")
                    failed = True
                    break
                cached = evaluation_cache.get(cache_key)
                if cached is not None:
                    images[source_name] = cached
                    continue

                progress.setLabelText(
                    f"Evaluating shared source for {artifact.label} · {source_name} at "
                    f"{artifact.width} × {artifact.height}…"
                )
                QApplication.processEvents()
                result = self.evaluator.evaluate(
                    source.node_uid,
                    artifact.width,
                    artifact.height,
                    snapshot=snapshot,
                    cancel_check=progress.wasCanceled,
                    progress_callback=pump_export_progress,
                    precision=self.document.texture_precision,
                    colour_space=self.document.colour_space,
                    render_mode="final",
                    output_name=source.output_name,
                    collect_traces=False,
                    **self._animation_context(),
                )
                step += 1
                progress.setValue(min(step, total_steps))
                if progress.wasCanceled():
                    cancelled = True
                    failed = True
                    break
                if result.error or result.image is None:
                    message = result.error or "no image was produced"
                    evaluation_failures[cache_key] = message
                    errors.append(f"{artifact.label}: {message}")
                    failed = True
                    break
                evaluation_cache[cache_key] = result.image
                images[source_name] = result.image
            if cancelled:
                break
            if failed:
                step += 1
                progress.setValue(min(step, total_steps))
                continue

            try:
                if artifact.operation == "template_pack":
                    image = pack_template_channels(
                        artifact.width,
                        artifact.height,
                        images,
                        artifact.channel_bindings,
                        normal_directx=artifact.normal_directx,
                    )
                else:
                    image = next(iter(images.values()))
                progress.setLabelText(f"Writing {destination.relative_to(request.directory)}…")
                QApplication.processEvents()
                export_image(destination, image, artifact.options)
                exported.append(destination)
            except Exception as exc:
                errors.append(f"{artifact.label}: {exc}")
            step += 1
            progress.setValue(min(step, total_steps))

        progress.close()
        if request.open_folder and exported:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(request.directory)))
        return exported, errors, cancelled, skipped

    def _report_export_result(
        self,
        request: ExportRequest,
        exported: list[Path],
        errors: list[str],
        cancelled: bool,
        skipped: int,
    ) -> None:
        if errors:
            preview = "\n".join(f"• {message}" for message in errors[:8])
            if len(errors) > 8:
                preview += f"\n• …and {len(errors) - 8} more"
            QMessageBox.warning(
                self,
                "Export completed with errors",
                f"Exported {len(exported)} file(s); {len(errors)} failed.\n\n{preview}",
            )
        elif cancelled:
            self.statusBar().showMessage(f"Export cancelled after {len(exported)} file(s)", 6000)
        else:
            suffix = f" · skipped {skipped}" if skipped else ""
            self.statusBar().showMessage(
                f"Exported {len(exported)} file{'s' if len(exported) != 1 else ''} to {request.directory}{suffix}",
                7000,
            )

    def _frame_all_nodes(self) -> None:
        bounds = self.scene.content_bounds()
        if not bounds.isEmpty():
            self.graph_view.fitInView(
                bounds.adjusted(-90, -90, 90, 90),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    def _toggle_selected_bypass(self) -> None:
        nodes = self.scene.selected_nodes()
        if len(nodes) == 1 and self.scene.node_is_bypassable(nodes[0]):
            self.scene.toggle_node_bypass(nodes[0])

    def _frame_selected(self) -> None:
        selected = self.scene.selectedItems()
        if selected:
            bounds = selected[0].sceneBoundingRect()
            for item in selected[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.graph_view.fitInView(bounds.adjusted(-120, -120, 120, 120), Qt.AspectRatioMode.KeepAspectRatio)
        elif self.scene.items():
            self.graph_view.fitInView(
                self.scene.content_bounds().adjusted(-120, -120, 120, 120),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    # ------------------------------------------------------------------
    # Public custom-node packages and library locations
    # ------------------------------------------------------------------
    @staticmethod
    def _package_definition_signatures(definitions: dict[str, object]) -> dict[str, tuple[str, str]]:
        signatures: dict[str, tuple[str, str]] = {}
        for type_id, definition in definitions.items():
            package = getattr(definition, "package", None)
            revision = str(getattr(package, "revision", "") or "")
            try:
                interface = json.dumps(definition.snapshot(), sort_keys=True, separators=(",", ":"))
            except Exception:
                interface = repr(definition)
            signatures[str(type_id)] = (revision, interface)
        return signatures

    def _reload_custom_nodes(self, checked: bool = False, *, initial: bool = False) -> None:
        del checked
        previous = self.registry.package_definitions()
        previous_signatures = self._package_definition_signatures(previous)
        definitions = self.package_manager.discover(self.evaluator.gpu_backend, previous)
        definitions_changed = previous_signatures != self._package_definition_signatures(definitions)
        self.registry.replace_package_definitions(definitions.values())
        if not initial:
            # Merely adding/removing a folder containing graph assets must not
            # reconstruct live graph sockets. Rebind only when an actual custom
            # node definition changed, but always refresh the library so newly
            # registered .vfxgraph files appear immediately.
            if definitions_changed:
                self.evaluator.gpu_cache.clear()
                self.evaluator.cpu_cache.clear()
                sessions = list(getattr(self, "_graph_sessions", {}).values())
                scenes = [session.scene for session in sessions] or [self.scene]
                for scene in scenes:
                    scene.rebind_registry_definitions()
                self._schedule_preview()
            if hasattr(self, "library_panel"):
                self.library_panel.rebuild()
            errors = sum(1 for item in self.package_manager.diagnostics() if item.severity == "error")
            warnings = sum(1 for item in self.package_manager.diagnostics() if item.severity == "warning")
            action = "Reloaded" if definitions_changed else "Refreshed libraries; found"
            message = f"{action} {len(definitions)} custom/public node package{'s' if len(definitions) != 1 else ''}"
            if errors or warnings:
                message += f" · {errors} error(s) · {warnings} warning(s)"
            self.statusBar().showMessage(message, 6500)

    def _custom_node_files_changed(self, paths: list[str]) -> None:
        names = ", ".join(Path(path).name for path in paths[:3])
        if len(paths) > 3:
            names += f" and {len(paths) - 3} more"
        self.statusBar().showMessage(f"Custom node source changed: {names or 'library contents'} · hot reloading…", 3000)
        self._reload_custom_nodes()

    def _show_custom_node_libraries(self) -> None:
        dialog = CustomNodeLibrariesDialog(self.package_manager, self)
        dialog.rescanRequested.connect(self._reload_custom_nodes)
        dialog.exec()

    def _show_custom_node_diagnostics(self) -> None:
        dialog = CustomNodeDiagnosticsDialog(self.package_manager, self)
        dialog.reloadRequested.connect(self._reload_custom_nodes)
        dialog.exec()

    def _install_custom_node_package(self) -> None:
        filename, _selected = QFileDialog.getOpenFileName(
            self,
            "Install custom node package",
            str(Path.home()),
            "VFX Node Packages (*.vfxnodepkg *.zip);;All files (*)",
        )
        if not filename:
            return
        try:
            target = self.package_manager.install_archive(filename)
        except Exception as exc:
            QMessageBox.critical(self, "Could not install custom node", str(exc))
            return
        self._reload_custom_nodes()
        QMessageBox.information(
            self,
            "Custom node installed",
            f"Installed into the managed node folder:\n{target}",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About VFX Texture Lab",
            f"<b>VFX Texture Lab {__version__}</b><br><br>"
            "A focused, open-source procedural texture graph for VFX artists.<br><br>"
            "0.53.0.4 fixes intermittent graph-canvas wheel zoom lockups after opening or framing unusually large graphs.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._workspace_save_timer.stop()
        self._save_workspace_layout()
        previous = self._active_graph_session_uid
        for uid, session in list(self._graph_sessions.items()):
            if session.dirty and not self._confirm_close_graph_session(session):
                if previous and previous in self._graph_sessions:
                    self.activate_graph_session(previous)
                event.ignore()
                return
        saved_paths = [
            str(session.current_path) for session in self._graph_sessions.values()
            if session.current_path is not None
        ]
        self.settings.setValue("session/open_graph_paths", saved_paths)
        active = self._active_graph_session()
        self.settings.setValue("session/active_graph_path", str(active.current_path) if active and active.current_path else "")
        self.settings.sync()
        self.playback_timer.stop()
        self.preview_timer.stop()
        self.geometry_preview_timer.stop()
        self.material_preview_timer.stop()
        self.material_present_timer.stop()
        self.eval_controller.cancel()
        self.geometry_controller.cancel()
        self.playback_controller.cancel()
        self.material_controller.cancel()
        self.evaluator.clear_cache()
        self._remove_autosave()
        event.accept()

