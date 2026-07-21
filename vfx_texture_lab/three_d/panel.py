from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from rendercanvas.qt import QRenderWidget
except Exception:  # pragma: no cover - handled by the unavailable fallback.
    QRenderWidget = QWidget  # type: ignore[misc,assignment]

from ..ui.parameters import AngleDial, ParameterGroupWidget

from .evaluation import MaterialEvaluationResult
from .renderer import ThreeDRenderer
from .settings import (
    CAMERA_VIEW_OPTIONS,
    ANTI_ALIASING_OPTIONS,
    DEBUG_VIEW_OPTIONS,
    DISPLACEMENT_SETTING_NAMES,
    ENVIRONMENT_PRESET_OPTIONS,
    GEOMETRY_QUALITY_OPTIONS,
    LIGHTING_PRESET_OPTIONS,
    PREVIEW_MESH_OPTIONS,
    PROJECTION_OPTIONS,
    QUALITY_FROM_LEGACY_RESOLUTION,
    TEXTURE_RESOLUTION_OPTIONS,
    TONE_MAPPING_OPTIONS,
    TILE_PREVIEW_OPTIONS,
    VIEWPORT_DEFAULTS,
    VIEWPORT_SETTING_NAMES,
    WIREFRAME_OPTIONS,
    viewport_settings,
)


def _renderer_colour(value: Any, fallback: str = "#2d2938ff") -> QColor:
    text = str(value or fallback).strip()
    if text.startswith("#") and len(text) in (7, 9):
        try:
            red = int(text[1:3], 16)
            green = int(text[3:5], 16)
            blue = int(text[5:7], 16)
            alpha = int(text[7:9], 16) if len(text) == 9 else 255
            return QColor(red, green, blue, alpha)
        except ValueError:
            pass
    colour = QColor(text)
    return colour if colour.isValid() else _renderer_colour(fallback, "#2d2938ff")


def _renderer_colour_text(colour: QColor) -> str:
    return f"#{colour.red():02x}{colour.green():02x}{colour.blue():02x}{colour.alpha():02x}"


class PreviewCanvas(QRenderWidget):
    cameraChanged = Signal()

    def __init__(self, gpu_backend, parent=None) -> None:
        try:
            super().__init__(parent, size=(640, 420), update_mode="ondemand", max_fps=60.0, present_method="bitmap")
        except TypeError:
            # QWidget fallback when rendercanvas is unavailable.
            QWidget.__init__(self, parent)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._last_position = QPoint()
        self._drag_mode = ""
        self.renderer = ThreeDRenderer(self, gpu_backend)
        if self.renderer.available and hasattr(self, "request_draw"):
            self.request_draw(self._draw_frame)

    def _draw_frame(self) -> None:
        try:
            self.renderer.draw()
        except Exception:
            # The panel reports renderer.error. Never let a driver/shader issue
            # tear down the Qt event loop.
            return

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = "pan" if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else "orbit"
            self._last_position = event.position().toPoint()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag_mode = "pan"
            self._last_position = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode:
            current = event.position().toPoint()
            delta = current - self._last_position
            self._last_position = current
            if self._drag_mode == "pan":
                self.renderer.pan(delta.x(), delta.y())
            else:
                self.renderer.orbit(delta.x(), delta.y())
            self.cameraChanged.emit()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton) and self._drag_mode:
            self._drag_mode = ""
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.renderer.dolly(event.angleDelta().y())
        self.cameraChanged.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_F, Qt.Key.Key_Home):
            self.renderer.reset_camera()
            self.cameraChanged.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.renderer.available:
            QTimer.singleShot(0, self.renderer.request_draw)


class SquareCanvasHost(QWidget):
    """Keep the render canvas at the largest square that fits the dock."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.canvas: QWidget | None = None
        self.setMinimumSize(250, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_canvas(self, canvas: QWidget) -> None:
        self.canvas = canvas
        canvas.setParent(self)
        self._layout_canvas()

    def _layout_canvas(self) -> None:
        if self.canvas is None:
            return
        side = max(min(self.width(), self.height()), 1)
        left = (self.width() - side) // 2
        top = (self.height() - side) // 2
        self.canvas.setGeometry(left, top, side, side)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_canvas()


class ThreeDPreviewPanel(QWidget):
    """Dockable square 3D preview with project-owned presentation settings."""

    textureResolutionChanged = Signal()
    viewportSettingsChanged = Signal()
    settingsRequested = Signal()

    def __init__(self, gpu_backend, parent=None, *, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        # QSettings is retained only for API compatibility with older callers.
        # Viewport and camera state now belong to the graph document itself.
        self._settings_store = settings or QSettings()
        self._viewport_settings = viewport_settings()
        self._syncing_settings = False
        self._loading_project_state = False
        self._active_output = False
        self._geometry_inspection = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 7, 7, 7)
        outer.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("3D Preview")
        self.title.setObjectName("sectionTitle")
        toolbar.addWidget(self.title, 1)

        self.view_combo = self._combo(CAMERA_VIEW_OPTIONS)
        self.view_combo.setToolTip("Choose the camera orientation")
        self.view_combo.setMinimumContentsLength(10)
        self.view_combo.currentTextChanged.connect(self.set_view)
        toolbar.addWidget(self.view_combo)

        frame = QToolButton()
        frame.setText("Frame")
        frame.setToolTip("Reset and frame the preview mesh (F / Home)")
        frame.clicked.connect(self.reset_view)
        toolbar.addWidget(frame)
        self.settings_button = QToolButton()
        self.settings_button.setText("Settings…")
        self.settings_button.setToolTip("Inspect 3D viewport settings in the Parameters panel")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        toolbar.addWidget(self.settings_button)
        capture = QPushButton("Screenshot…")
        capture.clicked.connect(self.save_screenshot)
        toolbar.addWidget(capture)
        outer.addLayout(toolbar)

        # The settings editor lives in the Parameters inspector rather than
        # consuming render space inside this dock. Keep it safely parked here
        # whenever another graph item is being inspected.
        self._settings_parking = QWidget(self)
        self._settings_parking.hide()
        self.settings_frame = self._build_settings_frame()
        self.settings_frame.setParent(self._settings_parking)

        self.canvas_host = SquareCanvasHost(self)
        self.canvas = PreviewCanvas(gpu_backend, self.canvas_host)
        self.canvas_host.set_canvas(self.canvas)
        self.canvas.renderer.update_viewport(self._viewport_settings)
        self._default_camera_state = dict(self.canvas.renderer.camera_state())
        self.canvas.cameraChanged.connect(self._camera_changed)
        outer.addWidget(self.canvas_host, 1)

        self._turntable_timer = QTimer(self)
        self._turntable_timer.setInterval(33)
        self._turntable_timer.timeout.connect(self._turntable_step)
        self._update_turntable_timer()

        self.help_label = QLabel(
            "Left drag: orbit · Shift+left or middle drag: pan · Wheel: zoom · F/Home: frame mesh"
        )
        self.help_label.setObjectName("muted")
        self.help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.help_label.setWordWrap(True)
        outer.addWidget(self.help_label)

        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(False)
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status.setFixedHeight(self.status.fontMetrics().lineSpacing() + 6)
        outer.addWidget(self.status)
        self._last_result: MaterialEvaluationResult | None = None
        self._last_cache_key: str | None = None
        self._geometry_previous_result: MaterialEvaluationResult | None = None
        self._geometry_previous_cache_key: str | None = None
        self._last_summary = "Double-click a Material node to evaluate it in 3D."
        self._status_full_text = self._last_summary
        self._last_live_status_update = 0.0
        if not self.canvas.renderer.available:
            self._last_summary = (
                "3D preview is unavailable because WebGPU could not initialise. "
                + (self.canvas.renderer.error or "No compatible adapter was found.")
            )
        self._set_status_text(self._last_summary)

    def _save_viewport_setting(self, name: str, value: Any) -> None:
        del name, value
        if not self._loading_project_state:
            self.viewportSettingsChanged.emit()

    def _camera_changed(self) -> None:
        if hasattr(self, "view_combo") and self.view_combo.currentText() != "Free":
            self.view_combo.blockSignals(True)
            try:
                self.view_combo.setCurrentText("Free")
            finally:
                self.view_combo.blockSignals(False)
        if not self._loading_project_state:
            self.viewportSettingsChanged.emit()

    def _turntable_step(self) -> None:
        speed = float(self._viewport_settings.get("turntable_speed", 20.0))
        self.canvas.renderer.rotate_degrees(speed * self._turntable_timer.interval() / 1000.0)

    def _update_turntable_timer(self) -> None:
        if not hasattr(self, "_turntable_timer"):
            return
        should_run = bool(self._viewport_settings.get("turntable", False)) and self.canvas.renderer.available
        if should_run and not self._turntable_timer.isActive():
            self._turntable_timer.start()
        elif not should_run and self._turntable_timer.isActive():
            self._turntable_timer.stop()

    @staticmethod
    def _combo(options: tuple[str, ...]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(options)
        return combo

    @staticmethod
    def _spin(minimum: float, maximum: float, step: float, decimals: int = 2) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setKeyboardTracking(False)
        return spin

    def _linked_float_control(
        self,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int = 2,
        *,
        suffix: str = "",
    ) -> tuple[QWidget, QDoubleSpinBox, QSlider]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        slider = QSlider(Qt.Orientation.Horizontal)
        scale = max(int(round(1.0 / step)), 1)
        slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
        spin = self._spin(minimum, maximum, step, decimals)
        spin.setSuffix(suffix)
        spin.setMinimumWidth(82)

        def slider_changed(value: int) -> None:
            target = value / scale
            if abs(spin.value() - target) > step * 0.25:
                spin.setValue(target)

        def spin_changed(value: float) -> None:
            target = int(round(value * scale))
            if slider.value() != target:
                slider.setValue(target)

        slider.valueChanged.connect(slider_changed)
        spin.valueChanged.connect(spin_changed)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return container, spin, slider

    def _linked_int_control(
        self,
        minimum: int,
        maximum: int,
        step: int = 1,
        *,
        suffix: str = "",
    ) -> tuple[QWidget, QSpinBox, QSlider]:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(minimum), int(maximum))
        slider.setSingleStep(max(int(step), 1))
        spin = QSpinBox()
        spin.setRange(int(minimum), int(maximum))
        spin.setSingleStep(max(int(step), 1))
        spin.setKeyboardTracking(False)
        spin.setSuffix(suffix)
        spin.setMinimumWidth(82)

        def slider_changed(value: int) -> None:
            if spin.value() != value:
                spin.setValue(value)

        def spin_changed(value: int) -> None:
            if slider.value() != value:
                slider.setValue(value)

        slider.valueChanged.connect(slider_changed)
        spin.valueChanged.connect(spin_changed)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return container, spin, slider

    @staticmethod
    def _set_widgets_visible(widgets: tuple[QWidget, ...], visible: bool) -> None:
        for widget in widgets:
            widget.setVisible(bool(visible))

    def _toggle_section(self, checkbox: QCheckBox, rows: tuple[tuple[str, QWidget], ...]) -> tuple[QWidget, QFrame]:
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0,0,0,0); section_layout.setSpacing(4)
        section_layout.addWidget(checkbox)
        body = QFrame(); body.setObjectName("parameterGroupBody")
        body_layout = QGridLayout(body)
        body_layout.setContentsMargins(18,0,0,2); body_layout.setHorizontalSpacing(8); body_layout.setVerticalSpacing(6)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for row,(title,control) in enumerate(rows):
            body_layout.addWidget(QLabel(title),row,0); body_layout.addWidget(control,row,1)
        body_layout.setColumnStretch(1,1); section_layout.addWidget(body)
        return section, body

    def _add_settings_group(self, title: str, page: QWidget, *, expanded: bool = True) -> ParameterGroupWidget:
        group = ParameterGroupWidget(title, expanded=expanded, parent=self.settings_groups_host)
        page.setParent(group.body)
        group.addRow(page)
        self.settings_groups_layout.addWidget(group)
        self.settings_groups[title] = group
        return group

    def _build_settings_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewSettings")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(0)
        self.settings_groups_host = QWidget(frame)
        self.settings_groups_layout = QVBoxLayout(self.settings_groups_host)
        self.settings_groups_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_groups_layout.setSpacing(5)
        self.settings_groups: dict[str, ParameterGroupWidget] = {}
        outer.addWidget(self.settings_groups_host)

        # Mesh and material-map presentation.
        mesh_page = QWidget()
        mesh_layout = QGridLayout(mesh_page)
        mesh_layout.setContentsMargins(8, 7, 8, 7)
        mesh_layout.setHorizontalSpacing(8)
        mesh_layout.setVerticalSpacing(6)
        mesh_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.mesh_combo = self._combo(PREVIEW_MESH_OPTIONS)
        self.mesh_quality_combo = self._combo(GEOMETRY_QUALITY_OPTIONS)
        self.wireframe_combo = self._combo(WIREFRAME_OPTIONS)
        self.wireframe_combo.setToolTip(
            "Auto shows shaded wireframe while inspecting Geometry nodes; Always overlays it on every preview mesh."
        )
        self.tile_combo = self._combo(("1 × 1", "3 × 3"))
        self.material_tiling_control, self.material_tiling_spin, self.material_tiling_slider = self._linked_int_control(
            1, 32, 1, suffix="×"
        )
        self.material_tiling_control.setToolTip(
            "Repeat the material maps across the selected mesh without duplicating the mesh itself."
        )
        self.texture_resolution_combo = self._combo(TEXTURE_RESOLUTION_OPTIONS)
        self.mesh_title = QLabel("Preview mesh")
        self.quality_title = QLabel("Geometry quality")
        self.wireframe_title = QLabel("Wireframe")
        self.material_tiling_title = QLabel("Material tiling")
        self.tiling_title = QLabel("Terrain tiling")
        self.map_resolution_title = QLabel("Material maps")
        mesh_layout.addWidget(self.mesh_title, 0, 0)
        mesh_layout.addWidget(self.mesh_combo, 0, 1)
        mesh_layout.addWidget(self.quality_title, 1, 0)
        mesh_layout.addWidget(self.mesh_quality_combo, 1, 1)
        mesh_layout.addWidget(self.wireframe_title, 2, 0)
        mesh_layout.addWidget(self.wireframe_combo, 2, 1)
        mesh_layout.addWidget(self.material_tiling_title, 3, 0)
        mesh_layout.addWidget(self.material_tiling_control, 3, 1)
        mesh_layout.addWidget(self.tiling_title, 4, 0)
        mesh_layout.addWidget(self.tile_combo, 4, 1)
        mesh_layout.addWidget(self.map_resolution_title, 5, 0)
        mesh_layout.addWidget(self.texture_resolution_combo, 5, 1)
        self.custom_mesh_label = QLabel("No custom mesh selected")
        self.custom_mesh_label.setObjectName("muted")
        self.custom_mesh_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.custom_mesh_button = QPushButton("Choose glTF / GLB…")
        self.custom_mesh_button.clicked.connect(self._choose_custom_mesh)
        self.custom_mesh_title = QLabel("Custom mesh")
        mesh_layout.addWidget(self.custom_mesh_title, 6, 0)
        custom_row = QWidget()
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(6)
        custom_layout.addWidget(self.custom_mesh_label, 1)
        custom_layout.addWidget(self.custom_mesh_button)
        self.custom_mesh_row = custom_row
        mesh_layout.addWidget(custom_row, 6, 1)
        mesh_layout.setColumnStretch(1, 1)
        self._add_settings_group("Mesh", mesh_page, expanded=True)

        # Height displacement is viewport presentation, not authored material
        # metadata. These controls update renderer uniforms directly and never
        # invalidate or re-evaluate the material graph.
        displacement_page = QWidget()
        displacement_layout = QGridLayout(displacement_page)
        displacement_layout.setContentsMargins(8, 7, 8, 7)
        displacement_layout.setHorizontalSpacing(8)
        displacement_layout.setVerticalSpacing(6)
        displacement_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.displacement_amount_control, self.displacement_amount_spin, self.displacement_amount_slider = self._linked_float_control(
            -5.0, 5.0, 0.01, 2
        )
        self.displacement_amount_control.setToolTip(
            "Scale the current Height texture along the preview mesh normals. This is a renderer-only control."
        )
        self.height_midpoint_control, self.height_midpoint_spin, self.height_midpoint_slider = self._linked_float_control(
            0.0, 1.0, 0.01, 2
        )
        self.height_midpoint_control.setToolTip(
            "Height value treated as the undisplaced surface. Values below and above move in opposite directions."
        )
        self.invert_height_checkbox = QCheckBox("Invert height")
        self.invert_height_checkbox.setToolTip(
            "Reverse the direction of the current Height texture for 3D preview displacement."
        )
        displacement_layout.addWidget(QLabel("Displacement amount"), 0, 0)
        displacement_layout.addWidget(self.displacement_amount_control, 0, 1)
        displacement_layout.addWidget(QLabel("Height midpoint"), 1, 0)
        displacement_layout.addWidget(self.height_midpoint_control, 1, 1)
        displacement_layout.addWidget(self.invert_height_checkbox, 2, 0, 1, 2)
        displacement_layout.setColumnStretch(1, 1)
        self._add_settings_group("Displacement", displacement_page, expanded=True)

        # Camera presentation and navigation.
        camera_page = QWidget()
        camera_layout = QGridLayout(camera_page)
        camera_layout.setContentsMargins(8, 7, 8, 7)
        camera_layout.setHorizontalSpacing(8)
        camera_layout.setVerticalSpacing(6)
        camera_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.projection_combo = self._combo(PROJECTION_OPTIONS)
        self.fov_control, self.fov_spin, self.fov_slider = self._linked_float_control(
            15.0, 100.0, 1.0, 0, suffix="°"
        )
        self.fov_title = QLabel("Field of view")
        self.turntable_checkbox = QCheckBox("Turntable")
        self.turntable_control, self.turntable_speed_spin, self.turntable_speed_slider = self._linked_float_control(
            2.0, 90.0, 1.0, 0, suffix="°/s"
        )
        camera_layout.addWidget(QLabel("Projection"), 0, 0)
        camera_layout.addWidget(self.projection_combo, 0, 1)
        camera_layout.addWidget(self.fov_title, 1, 0)
        camera_layout.addWidget(self.fov_control, 1, 1)
        self.turntable_section, self.turntable_body = self._toggle_section(self.turntable_checkbox, (("Speed", self.turntable_control),))
        camera_layout.addWidget(self.turntable_section, 2, 0, 1, 2)
        camera_layout.setColumnStretch(1, 1)
        self._add_settings_group("Camera", camera_page, expanded=False)

        # Lighting and image-based environment controls.
        light_page = QWidget()
        light_layout = QGridLayout(light_page)
        light_layout.setContentsMargins(8, 7, 8, 7)
        light_layout.setHorizontalSpacing(8)
        light_layout.setVerticalSpacing(6)
        light_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lighting_preset_combo = self._combo(LIGHTING_PRESET_OPTIONS)
        self.environment_preset_combo = self._combo(ENVIRONMENT_PRESET_OPTIONS)
        self.environment_control, self.environment_spin, self.environment_slider = self._linked_float_control(
            0.0, 10.0, 0.05, 2
        )
        self.environment_rotation_dial = AngleDial(
            value=0.0,
            minimum=0.0,
            maximum=360.0,
            default=0.0,
            normal_step=1.0,
            fine_step=1.0,
            coarse_step=15.0,
            wrap=True,
            wrap_minimum=0.0,
            wrap_maximum=360.0,
        )
        self.environment_rotation_dial.setFixedSize(64, 64)
        self.environment_rotation_spin = self._spin(0.0, 359.0, 1.0, 0)
        self.environment_rotation_spin.setSuffix("°")
        environment_rotation_row = QWidget()
        environment_rotation_layout = QHBoxLayout(environment_rotation_row)
        environment_rotation_layout.setContentsMargins(0, 3, 0, 3)
        environment_rotation_row.setMinimumHeight(72)
        environment_rotation_layout.addWidget(self.environment_rotation_dial)
        environment_rotation_layout.addWidget(self.environment_rotation_spin)
        environment_rotation_layout.addStretch(1)
        self.sun_control, self.sun_spin, self.sun_slider = self._linked_float_control(0.0, 20.0, 0.1, 1)
        self.sun_azimuth_dial = AngleDial(
            value=135.0,
            minimum=0.0,
            maximum=360.0,
            default=135.0,
            normal_step=1.0,
            fine_step=1.0,
            coarse_step=15.0,
            wrap=True,
            wrap_minimum=0.0,
            wrap_maximum=360.0,
        )
        self.sun_azimuth_dial.setFixedSize(64, 64)
        self.sun_azimuth_spin = self._spin(0.0, 359.0, 1.0, 0)
        self.sun_azimuth_spin.setSuffix("°")
        azimuth_row = QWidget()
        azimuth_layout = QHBoxLayout(azimuth_row)
        azimuth_layout.setContentsMargins(0, 3, 0, 3)
        azimuth_row.setMinimumHeight(72)
        azimuth_layout.addWidget(self.sun_azimuth_dial)
        azimuth_layout.addWidget(self.sun_azimuth_spin)
        azimuth_layout.addStretch(1)
        self.sun_elevation_control, self.sun_elevation_spin, self.sun_elevation_slider = self._linked_float_control(
            -89.0, 89.0, 1.0, 0, suffix="°"
        )
        self.shadow_checkbox = QCheckBox("Directional shadows")
        self.shadow_control, self.shadow_strength_spin, self.shadow_strength_slider = self._linked_float_control(
            0.0, 1.0, 0.01, 2
        )
        light_layout.addWidget(QLabel("Preset"), 0, 0)
        light_layout.addWidget(self.lighting_preset_combo, 0, 1)
        light_layout.addWidget(QLabel("Environment"), 1, 0)
        light_layout.addWidget(self.environment_preset_combo, 1, 1)
        light_layout.addWidget(QLabel("Environment rotation"), 2, 0)
        light_layout.addWidget(environment_rotation_row, 2, 1)
        light_layout.addWidget(QLabel("Environment intensity"), 3, 0)
        light_layout.addWidget(self.environment_control, 3, 1)
        light_layout.addWidget(QLabel("Sun intensity"), 4, 0)
        light_layout.addWidget(self.sun_control, 4, 1)
        light_layout.addWidget(QLabel("Sun azimuth"), 5, 0)
        light_layout.addWidget(azimuth_row, 5, 1)
        light_layout.addWidget(QLabel("Sun elevation"), 6, 0)
        light_layout.addWidget(self.sun_elevation_control, 6, 1)
        self.shadow_section, self.shadow_body = self._toggle_section(self.shadow_checkbox, (("Strength", self.shadow_control),))
        light_layout.addWidget(self.shadow_section, 7, 0, 1, 2)
        light_layout.setColumnStretch(1, 1)
        self._add_settings_group("Lighting", light_page, expanded=True)

        # Display/debug presentation.
        display_page = QWidget()
        display_layout = QGridLayout(display_page)
        display_layout.setContentsMargins(8, 7, 8, 7)
        display_layout.setHorizontalSpacing(8)
        display_layout.setVerticalSpacing(6)
        display_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.debug_view_combo = self._combo(DEBUG_VIEW_OPTIONS)
        self.environment_background_checkbox = QCheckBox("Show environment background")
        self.background_title = QLabel("Background colour")
        self.background_button = QPushButton("Background…")
        self.background_button.setToolTip("Fallback background colour shown behind transparent areas and behind the environment background blend")
        self.background_button.clicked.connect(self._choose_background)
        self.background_control, self.background_brightness_spin, self.background_brightness_slider = self._linked_float_control(
            0.0, 1.0, 0.01, 2
        )
        self.grid_checkbox = QCheckBox("Surface grid")
        self.uv_grid_checkbox = QCheckBox("UV grid overlay")
        display_layout.addWidget(QLabel("View mode"), 0, 0)
        display_layout.addWidget(self.debug_view_combo, 0, 1)
        display_layout.addWidget(self.background_title, 1, 0)
        display_layout.addWidget(self.background_button, 1, 1)
        self.environment_background_section, self.environment_background_body = self._toggle_section(
            self.environment_background_checkbox, (("Visibility", self.background_control),))
        display_layout.addWidget(self.environment_background_section, 2, 0, 1, 2)
        self.grid_row_title = QLabel("Overlays")
        grid_row = QWidget()
        grid_layout = QHBoxLayout(grid_row)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(self.grid_checkbox)
        grid_layout.addWidget(self.uv_grid_checkbox)
        grid_layout.addStretch(1)
        self.grid_row = grid_row
        display_layout.addWidget(self.grid_row_title, 3, 0)
        display_layout.addWidget(grid_row, 3, 1)
        display_layout.setColumnStretch(1, 1)
        self._add_settings_group("Display", display_page, expanded=False)

        # HDR output quality and optional VFX-friendly post effects.
        quality_page = QWidget()
        quality_layout = QGridLayout(quality_page)
        quality_layout.setContentsMargins(8,7,8,7); quality_layout.setHorizontalSpacing(8); quality_layout.setVerticalSpacing(6)
        quality_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tone_mapping_combo = self._combo(TONE_MAPPING_OPTIONS)
        self.exposure_control, self.exposure_spin, self.exposure_slider = self._linked_float_control(-5.0,5.0,0.05,2,suffix=" EV")
        self.anti_aliasing_combo = self._combo(ANTI_ALIASING_OPTIONS)
        self.bloom_checkbox = QCheckBox("Bloom")
        self.bloom_intensity_control, self.bloom_intensity_spin, self.bloom_intensity_slider = self._linked_float_control(0.0,3.0,0.01,2)
        self.bloom_threshold_control, self.bloom_threshold_spin, self.bloom_threshold_slider = self._linked_float_control(0.0,8.0,0.05,2)
        self.bloom_radius_control, self.bloom_radius_spin, self.bloom_radius_slider = self._linked_float_control(1.0,32.0,0.5,1,suffix=" px")
        self.bloom_section, self.bloom_body = self._toggle_section(self.bloom_checkbox, (("Intensity",self.bloom_intensity_control),("Threshold",self.bloom_threshold_control),("Radius",self.bloom_radius_control)))
        self.sharpen_checkbox = QCheckBox("Sharpen")
        self.sharpen_control, self.sharpen_strength_spin, self.sharpen_strength_slider = self._linked_float_control(0.0,1.0,0.01,2)
        self.sharpen_section, self.sharpen_body = self._toggle_section(self.sharpen_checkbox, (("Strength",self.sharpen_control),))
        self.vignette_checkbox = QCheckBox("Vignette")
        self.vignette_control, self.vignette_strength_spin, self.vignette_strength_slider = self._linked_float_control(0.0,1.0,0.01,2)
        self.vignette_section, self.vignette_body = self._toggle_section(self.vignette_checkbox, (("Strength",self.vignette_control),))
        quality_layout.addWidget(QLabel("Tone mapping"),0,0); quality_layout.addWidget(self.tone_mapping_combo,0,1)
        quality_layout.addWidget(QLabel("Exposure"),1,0); quality_layout.addWidget(self.exposure_control,1,1)
        quality_layout.addWidget(QLabel("Anti-aliasing"),2,0); quality_layout.addWidget(self.anti_aliasing_combo,2,1)
        quality_layout.addWidget(self.bloom_section,3,0,1,2); quality_layout.addWidget(self.sharpen_section,4,0,1,2); quality_layout.addWidget(self.vignette_section,5,0,1,2)
        quality_layout.setColumnStretch(1,1)
        self._add_settings_group("Quality", quality_page, expanded=True)

        self.mesh_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("preview_mesh", value))
        self.mesh_quality_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("mesh_quality", value))
        self.wireframe_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("wireframe", value))
        self.tile_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("tile_preview", value))
        self.material_tiling_spin.valueChanged.connect(lambda value: self._set_viewport_value("material_tiling", value))
        self.texture_resolution_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("texture_resolution", value))
        self.displacement_amount_spin.valueChanged.connect(
            lambda value: self._set_viewport_value("displacement_amount", value)
        )
        self.height_midpoint_spin.valueChanged.connect(
            lambda value: self._set_viewport_value("height_midpoint", value)
        )
        self.invert_height_checkbox.toggled.connect(
            lambda value: self._set_viewport_value("invert_height", value)
        )
        self.projection_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("camera_projection", value))
        self.fov_spin.valueChanged.connect(lambda value: self._set_viewport_value("camera_fov", value))
        self.turntable_checkbox.toggled.connect(lambda value: self._set_viewport_value("turntable", value))
        self.turntable_speed_spin.valueChanged.connect(lambda value: self._set_viewport_value("turntable_speed", value))
        self.lighting_preset_combo.currentTextChanged.connect(self._apply_lighting_preset)
        self.environment_preset_combo.currentTextChanged.connect(lambda value: self._set_lighting_value("environment_preset", value))
        self.environment_rotation_dial.valueEdited.connect(
            lambda value: self.environment_rotation_spin.setValue(float(value) % 360.0)
        )
        self.environment_rotation_spin.valueChanged.connect(self._environment_rotation_changed)
        self.environment_spin.valueChanged.connect(lambda value: self._set_lighting_value("environment_intensity", value))
        self.sun_spin.valueChanged.connect(lambda value: self._set_lighting_value("sun_intensity", value))
        self.sun_azimuth_dial.valueEdited.connect(
            lambda value: self.sun_azimuth_spin.setValue(float(value) % 360.0)
        )
        self.sun_azimuth_spin.valueChanged.connect(self._sun_azimuth_changed)
        self.sun_elevation_spin.valueChanged.connect(lambda value: self._set_lighting_value("sun_elevation", value))
        self.shadow_checkbox.toggled.connect(lambda value: self._set_viewport_value("shadows", value))
        self.shadow_strength_spin.valueChanged.connect(lambda value: self._set_viewport_value("shadow_strength", value))
        self.environment_background_checkbox.toggled.connect(lambda value: self._set_viewport_value("show_environment", value))
        self.background_brightness_spin.valueChanged.connect(lambda value: self._set_viewport_value("background_brightness", value))
        self.grid_checkbox.toggled.connect(lambda value: self._set_viewport_value("show_grid", value))
        self.uv_grid_checkbox.toggled.connect(lambda value: self._set_viewport_value("show_uv_grid", value))
        self.debug_view_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("debug_view", value))
        self.tone_mapping_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("tone_mapping", value))
        self.exposure_spin.valueChanged.connect(lambda value: self._set_viewport_value("exposure", value))
        self.anti_aliasing_combo.currentTextChanged.connect(lambda value: self._set_viewport_value("anti_aliasing", value))
        self.bloom_checkbox.toggled.connect(lambda value: self._set_viewport_value("bloom", value))
        self.bloom_intensity_spin.valueChanged.connect(lambda value: self._set_viewport_value("bloom_intensity", value))
        self.bloom_threshold_spin.valueChanged.connect(lambda value: self._set_viewport_value("bloom_threshold", value))
        self.bloom_radius_spin.valueChanged.connect(lambda value: self._set_viewport_value("bloom_radius", value))
        self.sharpen_checkbox.toggled.connect(lambda value: self._set_viewport_value("sharpen", value))
        self.sharpen_strength_spin.valueChanged.connect(lambda value: self._set_viewport_value("sharpen_strength", value))
        self.vignette_checkbox.toggled.connect(lambda value: self._set_viewport_value("vignette", value))
        self.vignette_strength_spin.valueChanged.connect(lambda value: self._set_viewport_value("vignette_strength", value))

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QPushButton("Reset Viewport Defaults")
        reset_button.setToolTip("Restore this project's 3D viewport to the application defaults")
        reset_button.clicked.connect(lambda: self.reset_project_state(mark_dirty=True))
        reset_row.addWidget(reset_button)
        outer.addLayout(reset_row)

        self._sync_viewport_widgets()
        return frame

    def _sync_viewport_widgets(self) -> None:
        self._syncing_settings = True
        try:
            mapping = (
                (self.mesh_combo, "preview_mesh"),
                (self.mesh_quality_combo, "mesh_quality"),
                (self.wireframe_combo, "wireframe"),
                (self.tile_combo, "tile_preview"),
                (self.texture_resolution_combo, "texture_resolution"),
                (self.projection_combo, "camera_projection"),
                (self.lighting_preset_combo, "lighting_preset"),
                (self.environment_preset_combo, "environment_preset"),
                (self.debug_view_combo, "debug_view"),
                (self.tone_mapping_combo, "tone_mapping"),
                (self.anti_aliasing_combo, "anti_aliasing"),
            )
            for widget, name in mapping:
                index = widget.findText(str(self._viewport_settings[name]))
                if index >= 0:
                    widget.setCurrentIndex(index)
            self.material_tiling_spin.setValue(int(self._viewport_settings["material_tiling"]))
            self.displacement_amount_spin.setValue(float(self._viewport_settings["displacement_amount"]))
            self.height_midpoint_spin.setValue(float(self._viewport_settings["height_midpoint"]))
            self.invert_height_checkbox.setChecked(bool(self._viewport_settings["invert_height"]))
            self.fov_spin.setValue(float(self._viewport_settings["camera_fov"]))
            self.turntable_checkbox.setChecked(bool(self._viewport_settings["turntable"]))
            self.turntable_speed_spin.setValue(float(self._viewport_settings["turntable_speed"]))
            environment_rotation = float(self._viewport_settings["environment_rotation"]) % 360.0
            self.environment_rotation_spin.setValue(environment_rotation)
            self.environment_rotation_dial.set_value(environment_rotation)
            self.environment_spin.setValue(float(self._viewport_settings["environment_intensity"]))
            self.sun_spin.setValue(float(self._viewport_settings["sun_intensity"]))
            azimuth = float(self._viewport_settings["sun_azimuth"]) % 360.0
            self.sun_azimuth_spin.setValue(azimuth)
            self.sun_azimuth_dial.set_value(azimuth)
            self.sun_elevation_spin.setValue(float(self._viewport_settings["sun_elevation"]))
            self.shadow_checkbox.setChecked(bool(self._viewport_settings["shadows"]))
            self.shadow_strength_spin.setValue(float(self._viewport_settings["shadow_strength"]))
            self.environment_background_checkbox.setChecked(bool(self._viewport_settings["show_environment"]))
            self.background_brightness_spin.setValue(float(self._viewport_settings["background_brightness"]))
            self.exposure_spin.setValue(float(self._viewport_settings["exposure"]))
            self.bloom_checkbox.setChecked(bool(self._viewport_settings["bloom"]))
            self.bloom_intensity_spin.setValue(float(self._viewport_settings["bloom_intensity"]))
            self.bloom_threshold_spin.setValue(float(self._viewport_settings["bloom_threshold"]))
            self.bloom_radius_spin.setValue(float(self._viewport_settings["bloom_radius"]))
            self.sharpen_checkbox.setChecked(bool(self._viewport_settings["sharpen"]))
            self.sharpen_strength_spin.setValue(float(self._viewport_settings["sharpen_strength"]))
            self.vignette_checkbox.setChecked(bool(self._viewport_settings["vignette"]))
            self.vignette_strength_spin.setValue(float(self._viewport_settings["vignette_strength"]))
            self.grid_checkbox.setChecked(bool(self._viewport_settings["show_grid"]))
            self.uv_grid_checkbox.setChecked(bool(self._viewport_settings["show_uv_grid"]))
            custom_path = str(self._viewport_settings.get("custom_mesh", ""))
            self.custom_mesh_label.setText(Path(custom_path).name if custom_path else "No custom mesh selected")
            self.custom_mesh_label.setToolTip(custom_path)
            self._update_background_button()
            self._update_contextual_controls()
        finally:
            self._syncing_settings = False

    def _update_contextual_controls(self) -> None:
        mesh_name = str(self._viewport_settings.get("preview_mesh", ""))
        custom = mesh_name == "Custom Mesh"
        terrain = mesh_name == "Terrain Plane"
        plane = mesh_name in {"Terrain Plane", "Flat Plane"}
        self._set_widgets_visible((self.quality_title, self.mesh_quality_combo), not custom)
        self._set_widgets_visible((self.tiling_title, self.tile_combo), terrain)
        self._set_widgets_visible((self.custom_mesh_title, self.custom_mesh_row), custom)
        self._set_widgets_visible((self.grid_row_title, self.grid_row), True)
        self.grid_checkbox.setVisible(plane)
        self.fov_title.setVisible(str(self._viewport_settings.get("camera_projection")) == "Perspective")
        self.fov_control.setVisible(str(self._viewport_settings.get("camera_projection")) == "Perspective")
        self.turntable_body.setVisible(bool(self._viewport_settings.get("turntable", False)))
        self.environment_background_body.setVisible(bool(self._viewport_settings.get("show_environment", True)))
        self.shadow_body.setVisible(bool(self._viewport_settings.get("shadows", True)))
        self.bloom_body.setVisible(bool(self._viewport_settings.get("bloom", True)))
        self.sharpen_body.setVisible(bool(self._viewport_settings.get("sharpen", False)))
        self.vignette_body.setVisible(bool(self._viewport_settings.get("vignette", False)))

    # Backward-compatible private name used by the 0.31 tests.
    def _update_custom_mesh_visibility(self) -> None:
        self._update_contextual_controls()

    def _set_lighting_value(self, name: str, value: Any) -> None:
        if not self._syncing_settings and self._viewport_settings.get("lighting_preset") != "Custom":
            self._viewport_settings["lighting_preset"] = "Custom"
            self._viewport_settings["lighting_mode"] = "Lit"
            self._save_viewport_setting("lighting_preset", "Custom")
            self._save_viewport_setting("lighting_mode", "Lit")
            self._syncing_settings = True
            try:
                self.lighting_preset_combo.setCurrentText("Custom")
            finally:
                self._syncing_settings = False
        self._set_viewport_value(name, value)

    def _environment_rotation_changed(self, value: float) -> None:
        dial_value = float(value) % 360.0
        if abs(float(self.environment_rotation_dial.value) - dial_value) > 1.0e-9:
            self.environment_rotation_dial.set_value(dial_value)
        self._set_lighting_value("environment_rotation", dial_value)

    def _sun_azimuth_changed(self, value: float) -> None:
        dial_value = float(value) % 360.0
        if abs(float(self.sun_azimuth_dial.value) - dial_value) > 1.0e-9:
            self.sun_azimuth_dial.set_value(dial_value)
        self._set_lighting_value("sun_azimuth", dial_value)

    def _apply_lighting_preset(self, name: str) -> None:
        if self._syncing_settings:
            return
        presets = {
            "VFX Studio": ("Lit", "Cayley Interior", 301.0, 0.20, 2.5, 328.0, 35.0),
            "Studio": ("Lit", "Studio Small 02", 0.0, 0.28, 2.5, 135.0, 42.0),
            "Soft": ("Lit", "Overcast Soil", 20.0, 0.30, 0.8, 120.0, 55.0),
            "Dramatic": ("Lit", "Cayley Interior", 210.0, 0.24, 5.0, 225.0, 24.0),
            "Flat": ("Lit", "Overcast Soil", 0.0, 0.35, 0.0, 135.0, 42.0),
            "Unlit": ("Unlit", "Studio Small 02", 0.0, 1.0, 0.0, 135.0, 42.0),
        }
        self._viewport_settings["lighting_preset"] = name
        self._save_viewport_setting("lighting_preset", name)
        if name not in presets:
            return
        mode, environment_preset, environment_rotation, environment, sun, azimuth, elevation = presets[name]
        values = {
            "lighting_mode": mode,
            "environment_preset": environment_preset,
            "environment_rotation": environment_rotation,
            "environment_intensity": environment,
            "sun_intensity": sun,
            "sun_azimuth": azimuth,
            "sun_elevation": elevation,
        }
        if name == "VFX Studio":
            values.update({"shadows": True, "shadow_strength": 0.77})
        self._viewport_settings.update(values)
        for key, value in values.items():
            self._save_viewport_setting(key, value)
        self._sync_viewport_widgets()
        self.canvas.renderer.update_viewport(self._viewport_settings)

    def _update_background_button(self) -> None:
        colour = _renderer_colour(self._viewport_settings.get("background", "#2d2938ff"))
        foreground = "#111111" if colour.lightnessF() > 0.62 else "#ffffff"
        self.background_button.setStyleSheet(
            f"QPushButton {{ background-color: {colour.name(QColor.NameFormat.HexRgb)}; color: {foreground}; }}"
        )

    def _set_viewport_value(self, name: str, value: Any, *, persist: bool = True) -> None:
        if self._syncing_settings or name not in VIEWPORT_SETTING_NAMES:
            return
        previous = self._viewport_settings.get(name)
        if previous == value:
            return
        self._viewport_settings[name] = value
        if persist:
            self._save_viewport_setting(name, value)
        if name == "preview_mesh":
            self._update_custom_mesh_visibility()
        if name in {"camera_projection", "turntable", "show_environment", "shadows", "bloom", "sharpen", "vignette"}:
            self._update_contextual_controls()
        if name == "turntable":
            self._update_turntable_timer()
        if name == "background":
            self._update_background_button()
        if name in DISPLACEMENT_SETTING_NAMES:
            self.canvas.renderer.update_viewport_uniforms(self._viewport_settings)
        else:
            self.canvas.renderer.update_viewport(self._viewport_settings)
        if name == "texture_resolution":
            self.textureResolutionChanged.emit()

    def set_viewport_setting(self, name: str, value: Any, *, persist: bool = True) -> None:
        if name not in VIEWPORT_SETTING_NAMES:
            raise KeyError(name)
        self._viewport_settings[name] = value
        self._sync_viewport_widgets()
        if persist:
            self._save_viewport_setting(name, value)
        if name in DISPLACEMENT_SETTING_NAMES:
            self.canvas.renderer.update_viewport_uniforms(self._viewport_settings)
        else:
            self.canvas.renderer.update_viewport(self._viewport_settings)
        if name == "turntable":
            self._update_turntable_timer()
        if name == "texture_resolution":
            self.textureResolutionChanged.emit()

    def viewport_setting(self, name: str) -> Any:
        return self._viewport_settings.get(name, VIEWPORT_DEFAULTS.get(name))

    def viewport_settings(self) -> dict[str, Any]:
        return dict(self._viewport_settings)

    def settings_widget(self) -> QWidget:
        """Return the persistent viewport editor for temporary inspection."""
        return self.settings_frame

    def park_settings_widget(self, widget: QWidget | None = None) -> None:
        editor = widget or self.settings_frame
        editor.hide()
        editor.setParent(self._settings_parking)

    def project_state(self) -> dict[str, Any]:
        """Serialisable viewport state owned by the current graph document."""
        camera = dict(self.canvas.renderer.camera_state())
        camera["view"] = self.view_combo.currentText() or "Free"
        return {
            "settings": dict(self._viewport_settings),
            "camera": camera,
        }

    def load_project_state(self, state: Mapping[str, Any] | None) -> None:
        """Restore one document's viewport state, or defaults when absent."""
        self._loading_project_state = True
        try:
            raw = dict(state or {})
            settings_data = raw.get("settings")
            if not isinstance(settings_data, Mapping):
                # Accept early development files that stored the settings flat.
                settings_data = raw if any(name in raw for name in VIEWPORT_SETTING_NAMES) else None
            self._viewport_settings = viewport_settings(settings_data)
            self._sync_viewport_widgets()
            self.canvas.renderer.update_viewport(self._viewport_settings)
            camera_data = raw.get("camera")
            if not isinstance(camera_data, Mapping):
                camera_data = self._default_camera_state
            self.canvas.renderer.restore_camera_state(dict(camera_data))
            view_name = str(camera_data.get("view", "Free"))
            if view_name not in CAMERA_VIEW_OPTIONS:
                view_name = "Free"
            self.view_combo.blockSignals(True)
            try:
                self.view_combo.setCurrentText(view_name)
            finally:
                self.view_combo.blockSignals(False)
            self._update_turntable_timer()
        finally:
            self._loading_project_state = False

    def reset_project_state(self, *, mark_dirty: bool = False) -> None:
        previous = self.project_state() if mark_dirty else None
        self.load_project_state(None)
        if mark_dirty and previous != self.project_state():
            self.viewportSettingsChanged.emit()

    def adopt_legacy_output_settings(self, parameters: dict[str, Any]) -> bool:
        legacy = {name: parameters[name] for name in VIEWPORT_SETTING_NAMES if name in parameters}
        removed_preview_flag = "preview_enabled" in parameters
        if not legacy and not removed_preview_flag:
            return False
        if legacy:
            if "mesh_quality" not in legacy and "mesh_resolution" in legacy:
                legacy["mesh_quality"] = QUALITY_FROM_LEGACY_RESOLUTION.get(
                    str(legacy["mesh_resolution"]), "High"
                )
            self._viewport_settings.update(legacy)
            self._sync_viewport_widgets()
            for name, value in legacy.items():
                self._save_viewport_setting(name, value)
            self.canvas.renderer.update_viewport(self._viewport_settings)
        for name in (*legacy, "preview_enabled"):
            parameters.pop(name, None)
        return True

    def _choose_custom_mesh(self) -> None:
        current = str(self._viewport_settings.get("custom_mesh", ""))
        start = str(Path(current).parent) if current else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose 3D preview mesh",
            start,
            "glTF mesh (*.gltf *.glb)",
        )
        if not filename:
            return
        self.set_viewport_setting("custom_mesh", filename)

    def _choose_background(self) -> None:
        initial = _renderer_colour(self._viewport_settings.get("background", "#2d2938ff"))
        colour = QColorDialog.getColor(
            initial,
            self,
            "Choose 3D preview background",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not colour.isValid():
            return
        self.set_viewport_setting("background", _renderer_colour_text(colour))

    def _set_status_text(self, message: str) -> None:
        self._status_full_text = str(message or "")
        self.status.setToolTip(self._status_full_text)
        available_width = max(self.status.width() - 4, 80)
        self.status.setText(
            self.status.fontMetrics().elidedText(
                self._status_full_text,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, lambda: self._set_status_text(self._status_full_text))

    @property
    def available(self) -> bool:
        return self.canvas.renderer.available

    def set_active_output(self, active: bool, name: str | None = None) -> None:
        self._active_output = bool(active)
        if active:
            if name:
                self.title.setText(name)
            self._set_status_text(self._last_summary)
            return
        if self._last_result is None:
            self._set_status_text("Double-click a Material node to evaluate it in 3D.")
        else:
            self._set_status_text(
                f"{self._last_summary} · paused; double-click a Material node to refresh"
            )

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        if busy:
            self._set_status_text(message or "Evaluating 3D material…")
        else:
            self._set_status_text(self._last_summary)

    def set_result(
        self,
        result: MaterialEvaluationResult,
        *,
        cache_key: str | None = None,
        incremental: bool = False,
    ) -> bool:
        self._geometry_inspection = False
        self._geometry_previous_result = None
        self._geometry_previous_cache_key = None
        self._last_result = result
        self._last_cache_key = cache_key
        if not incremental:
            self.title.setText(result.output_name or "3D Preview")
        try:
            reused = self.canvas.renderer.update_material(
                result.textures,
                result.connected,
                result.settings,
                cache_key=cache_key,
                channel_tokens=result.channel_tokens,
                incremental=incremental,
            )
            summary = self.canvas.renderer.mesh_summary
            source_detail = ""
            if (result.evaluation_width, result.evaluation_height) != (result.width, result.height):
                source_detail = f" · evaluated from {result.evaluation_width} × {result.evaluation_height} graph cache"
            reuse_detail = " · renderer textures reused" if reused else ""
            self._last_summary = (
                f"{summary} · {result.width} × {result.height} material maps{source_detail} · "
                f"frame {result.frame_number} · {result.backend_summary} · {result.elapsed_ms:.1f} ms{reuse_detail}"
            )
            now = time.perf_counter()
            if not incremental or (now - self._last_live_status_update) >= 0.25:
                self._last_live_status_update = now
                self.title.setText(result.output_name or "3D Preview")
                self._set_status_text(self._last_summary)
            return reused
        except Exception as exc:
            self.set_error(f"{type(exc).__name__}: {exc}")
            return False

    def activate_cached_result(self, result: MaterialEvaluationResult, cache_key: str) -> bool:
        self._geometry_inspection = False
        self._geometry_previous_result = None
        self._geometry_previous_cache_key = None
        self._last_cache_key = cache_key
        try:
            if not self.canvas.renderer.activate_cached_material(
                cache_key, result.connected, result.settings
            ):
                return False
            self._last_result = result
            self.title.setText(result.output_name or "3D Preview")
            summary = self.canvas.renderer.mesh_summary
            source_detail = ""
            if (result.evaluation_width, result.evaluation_height) != (result.width, result.height):
                source_detail = f" · evaluated from {result.evaluation_width} × {result.evaluation_height} graph cache"
            self._last_summary = (
                f"{summary} · {result.width} × {result.height} material maps{source_detail} · "
                f"frame {result.frame_number} · preview cache · renderer textures reused"
            )
            self._set_status_text(self._last_summary)
            return True
        except Exception as exc:
            self.set_error(f"{type(exc).__name__}: {exc}")
            return False

    def set_geometry_override(self, mesh, *, name: str | None = None) -> None:
        """Use graph geometry while retaining the current material textures."""
        self._geometry_inspection = False
        self.canvas.renderer.set_geometry_override(mesh, inspection=False)
        if name and self._active_output:
            self.title.setText(str(name))
        if self._last_result is not None:
            self._last_summary = (
                f"{self.canvas.renderer.mesh_summary} · material preview geometry override"
            )
            self._set_status_text(self._last_summary)

    def clear_geometry_override(self) -> None:
        was_inspection = self._geometry_inspection
        previous_result = self._geometry_previous_result
        previous_cache_key = self._geometry_previous_cache_key
        self._geometry_inspection = False
        self._geometry_previous_result = None
        self._geometry_previous_cache_key = None
        self.canvas.renderer.clear_geometry_override()
        if was_inspection and previous_result is not None:
            self.set_result(previous_result, cache_key=previous_cache_key)
        elif was_inspection:
            self._last_result = None
            self._last_cache_key = None
            self.title.setText("3D Preview")
            self._last_summary = "Double-click a Material node to evaluate it in 3D."
            self._set_status_text(self._last_summary)

    def show_geometry(self, mesh, *, name: str | None = None) -> None:
        """Display procedural geometry with neutral shaded inspection material."""
        if not self._geometry_inspection:
            self._geometry_previous_result = self._last_result
            self._geometry_previous_cache_key = self._last_cache_key
        self._geometry_inspection = True
        self._active_output = True
        self.canvas.renderer.set_geometry_override(mesh, inspection=True)
        # Empty texture input asks the renderer for its established neutral PBR
        # defaults.  This gives useful shaded faces and studio lighting without
        # pretending the geometry owns a material.
        self.canvas.renderer.update_material(
            {}, frozenset(),
            {
                "name": str(name or getattr(mesh, "name", "Geometry")),
                "surface_mode": "Opaque",
                "two_sided": True,
                "emissive_intensity": 1.0,
                "normal_strength": 1.0,
                "normal_y": "OpenGL (+Y)",
                "derive_normals": False,
            },
        )
        self.title.setText(str(name or getattr(mesh, "name", "Geometry")))
        self._last_summary = (
            f"{self.canvas.renderer.mesh_summary} · shaded + wireframe geometry inspection · "
            "UVs and vertex normals present"
        )
        self._set_status_text(self._last_summary)

    def set_material_cache_budget_mb(self, budget_mb: int) -> None:
        self.canvas.renderer.set_material_cache_budget_mb(budget_mb)

    def material_cache_stats(self):
        return self.canvas.renderer.material_cache_stats()

    def clear_material_cache(self) -> None:
        self.canvas.renderer.clear_material_cache()

    def set_error(self, message: str) -> None:
        self._last_summary = f"3D preview error: {message}"
        self._set_status_text(self._last_summary)

    def clear_output(self) -> None:
        self._last_result = None
        self._last_cache_key = None
        self._geometry_previous_result = None
        self._geometry_previous_cache_key = None
        self.title.setText("3D Preview")
        self._last_summary = "Double-click a Material node to evaluate it in 3D."
        self._set_status_text(self._last_summary)

    def reset_view(self) -> None:
        self.canvas.renderer.reset_camera()
        self._camera_changed()

    def set_view(self, view: str) -> None:
        self.canvas.renderer.set_view(view)
        if not self._loading_project_state:
            self.viewportSettingsChanged.emit()

    def capture_image(self) -> QImage:
        """Return the current square viewport without opening a file dialogue."""
        if not self._active_output or (self._last_result is None and not self._geometry_inspection):
            return QImage()
        pixmap = self.canvas.grab()
        return pixmap.toImage() if not pixmap.isNull() else QImage()

    def save_screenshot(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save 3D preview screenshot",
            str(Path.home() / "vfx_texture_lab_3d_preview.png"),
            "PNG image (*.png)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".png"):
            filename += ".png"
        pixmap = self.canvas.grab()
        if not pixmap.save(filename, "PNG"):
            self.set_error("Could not save the screenshot")
