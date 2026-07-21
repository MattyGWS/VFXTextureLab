from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..export_profiles import ExportProfileLibrary, ExportProfileSet, ExportTarget
from .export_target_dialog import ExportTargetDialog


@dataclass(frozen=True, slots=True)
class ExportOutputChoice:
    uid: str
    name: str
    kind: str
    summary: str
    enabled: bool = True
    filenames: tuple[str, ...] = ()
    file_details: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class ExportRequest:
    node_uids: list[str]
    directory: Path
    collision: str
    open_folder: bool
    profile_library: dict[str, Any] | None = None
    profile_id: str = ""

    def profile(self) -> ExportProfileSet:
        library = ExportProfileLibrary.from_dict(self.profile_library)
        if self.profile_id:
            library = library.with_active(self.profile_id)
        return library.active_profile()


class ExportDialog(QDialog):
    """Batch export centre with graph-local production profile sets."""

    def __init__(
        self,
        outputs: list[ExportOutputChoice],
        preferred_uids: set[str] | None,
        default_directory: Path,
        *,
        default_collision: str = "Replace existing",
        default_open_folder: bool = False,
        profile_library: ExportProfileLibrary | dict | None = None,
        plan_callback: Callable[[list[str], ExportProfileSet], list[Any]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Outputs")
        self.resize(920, 900)
        self._plan_callback = plan_callback
        self._planned_artifacts: list[Any] = []
        library = (
            profile_library
            if isinstance(profile_library, ExportProfileLibrary)
            else ExportProfileLibrary.from_dict(profile_library)
        )
        self._profiles = list(library.profiles)
        self._active_profile_id = library.active_profile_id

        outer = QVBoxLayout(self)

        heading = QLabel("Graph Outputs")
        heading.setObjectName("sectionTitle")
        outer.addWidget(heading)
        note = QLabel(
            "Choose the output endpoints, then publish every selected Texture Set Output through one or more "
            "production targets. Single Image Outputs are exported once using their own settings."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        outer.addWidget(note)

        controls = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_none = QPushButton("Select None")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        controls.addWidget(select_all)
        controls.addWidget(select_none)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.outputs = QListWidget()
        self._choices = {choice.uid: choice for choice in outputs}
        preferred = set(preferred_uids or ())
        for choice in outputs:
            item = QListWidgetItem(f"{choice.name}   ·   {choice.kind}\n{choice.summary}")
            item.setData(Qt.ItemDataRole.UserRole, choice.uid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = choice.uid in preferred if preferred else choice.enabled
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            if not choice.enabled:
                item.setToolTip("Not selected by default. The endpoint may be disabled or have no connected exportable inputs.")
            self.outputs.addItem(item)
        self.outputs.itemChanged.connect(self._update_preflight)
        self.outputs.setMinimumHeight(165)
        outer.addWidget(self.outputs, 1)

        profile_heading = QLabel("Export Profile Set")
        profile_heading.setObjectName("sectionTitle")
        outer.addWidget(profile_heading)
        profile_note = QLabel(
            "A profile set groups the targets you commonly publish together—for example Unreal, source-quality maps "
            "and a mobile pack. Profiles are saved inside this graph."
        )
        profile_note.setWordWrap(True)
        profile_note.setObjectName("muted")
        outer.addWidget(profile_note)

        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        profile_row.addWidget(self.profile_combo, 1)
        for label, callback in (
            ("New…", self._new_profile),
            ("Duplicate", self._duplicate_profile),
            ("Rename…", self._rename_profile),
            ("Delete", self._delete_profile),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            profile_row.addWidget(button)
        outer.addLayout(profile_row)

        target_row = QHBoxLayout()
        self.targets = QListWidget()
        self.targets.itemChanged.connect(self._target_checked)
        self.targets.itemDoubleClicked.connect(lambda _item: self._edit_target())
        self.targets.setMinimumHeight(135)
        target_row.addWidget(self.targets, 1)
        target_buttons = QVBoxLayout()
        for label, callback in (
            ("Add Target…", self._add_target),
            ("Edit…", self._edit_target),
            ("Duplicate", self._duplicate_target),
            ("Remove", self._remove_target),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            target_buttons.addWidget(button)
        target_buttons.addStretch(1)
        target_row.addLayout(target_buttons)
        outer.addLayout(target_row)

        preflight_heading = QLabel("Planned Files")
        preflight_heading.setObjectName("sectionTitle")
        outer.addWidget(preflight_heading)
        self.preflight = QListWidget()
        self.preflight.setMinimumHeight(180)
        self.preflight.setAlternatingRowColors(True)
        outer.addWidget(self.preflight, 1)

        form = QFormLayout()
        directory_row = QHBoxLayout()
        self.directory = QLineEdit(str(default_directory))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_directory)
        directory_row.addWidget(self.directory, 1)
        directory_row.addWidget(browse)
        form.addRow("Output folder", directory_row)

        self.collision = QComboBox()
        self.collision.addItems(("Replace existing", "Add numeric suffix", "Skip existing"))
        if default_collision in {self.collision.itemText(index) for index in range(self.collision.count())}:
            self.collision.setCurrentText(default_collision)
        form.addRow("Existing files", self.collision)

        self.open_folder = QCheckBox("Open output folder when complete")
        self.open_folder.setChecked(bool(default_open_folder))
        form.addRow("After export", self.open_folder)
        outer.addLayout(form)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        outer.addWidget(self.hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export Selected")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._reload_profiles()
        self._update_preflight()

    # ------------------------------------------------------------------
    # Output endpoint selection
    # ------------------------------------------------------------------
    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.outputs.blockSignals(True)
        try:
            for index in range(self.outputs.count()):
                self.outputs.item(index).setCheckState(state)
        finally:
            self.outputs.blockSignals(False)
        self._update_preflight()

    def selected_uids(self) -> list[str]:
        return [
            str(self.outputs.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.outputs.count())
            if self.outputs.item(index).checkState() == Qt.CheckState.Checked
        ]

    # ------------------------------------------------------------------
    # Profile and target editing
    # ------------------------------------------------------------------
    def _current_profile_index(self) -> int:
        for index, profile in enumerate(self._profiles):
            if profile.profile_id == self._active_profile_id:
                return index
        return 0

    def _current_profile(self) -> ExportProfileSet:
        if not self._profiles:
            profile = ExportProfileSet.default()
            self._profiles.append(profile)
            self._active_profile_id = profile.profile_id
        return self._profiles[self._current_profile_index()]

    def _replace_current_profile(self, profile: ExportProfileSet) -> None:
        index = self._current_profile_index()
        self._profiles[index] = profile
        self._active_profile_id = profile.profile_id
        self._reload_profiles()

    def _reload_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        try:
            self.profile_combo.clear()
            for profile in self._profiles:
                self.profile_combo.addItem(profile.name, profile.profile_id)
            index = self.profile_combo.findData(self._active_profile_id)
            self.profile_combo.setCurrentIndex(max(index, 0))
        finally:
            self.profile_combo.blockSignals(False)
        self._load_targets()

    def _profile_changed(self, index: int) -> None:
        if index >= 0:
            self._active_profile_id = str(self.profile_combo.itemData(index))
            self._load_targets()
            self._update_preflight()

    def _load_targets(self) -> None:
        self.targets.blockSignals(True)
        try:
            self.targets.clear()
            for target in self._current_profile().targets:
                summary = target.template_name
                overrides = [
                    value for value in (
                        target.resolution,
                        target.normal_convention,
                        target.texture_format,
                    )
                    if value != "Output setting"
                ]
                if overrides:
                    summary += " · " + " · ".join(overrides)
                folder = target.subfolder.strip() or "Export root"
                item = QListWidgetItem(f"{target.name}\n{summary} · {folder}")
                item.setData(Qt.ItemDataRole.UserRole, target.target_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if target.enabled else Qt.CheckState.Unchecked)
                self.targets.addItem(item)
        finally:
            self.targets.blockSignals(False)
        if self.targets.count() and self.targets.currentRow() < 0:
            self.targets.setCurrentRow(0)

    def _target_checked(self, item: QListWidgetItem) -> None:
        target_id = str(item.data(Qt.ItemDataRole.UserRole))
        profile = self._current_profile()
        targets = tuple(
            replace(target, enabled=item.checkState() == Qt.CheckState.Checked)
            if target.target_id == target_id else target
            for target in profile.targets
        )
        self._profiles[self._current_profile_index()] = replace(profile, targets=targets)
        self._update_preflight()

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New export profile", "Profile name:", text="Production Targets")
        if not ok or not name.strip():
            return
        profile = ExportProfileSet.from_dict({"name": name.strip(), "targets": [ExportTarget.current().to_dict()]})
        self._profiles.append(profile)
        self._active_profile_id = profile.profile_id
        self._reload_profiles()
        self._update_preflight()

    def _duplicate_profile(self) -> None:
        profile = self._current_profile().duplicate()
        self._profiles.append(profile)
        self._active_profile_id = profile.profile_id
        self._reload_profiles()
        self._update_preflight()

    def _rename_profile(self) -> None:
        profile = self._current_profile()
        name, ok = QInputDialog.getText(self, "Rename export profile", "Profile name:", text=profile.name)
        if not ok or not name.strip():
            return
        self._replace_current_profile(replace(profile, name=name.strip()))
        self._update_preflight()

    def _delete_profile(self) -> None:
        if len(self._profiles) <= 1:
            self.hint.setText("At least one export profile must remain.")
            return
        profile = self._current_profile()
        answer = QMessageBox.question(self, "Delete export profile", f"Delete ‘{profile.name}’?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = self._current_profile_index()
        del self._profiles[index]
        self._active_profile_id = self._profiles[max(0, index - 1)].profile_id
        self._reload_profiles()
        self._update_preflight()

    def _selected_target(self) -> ExportTarget | None:
        item = self.targets.currentItem()
        if item is None:
            return None
        target_id = str(item.data(Qt.ItemDataRole.UserRole))
        return next((target for target in self._current_profile().targets if target.target_id == target_id), None)

    def _add_target(self) -> None:
        dialog = ExportTargetDialog(ExportTarget.from_dict({"name": "New Target", "subfolder": "{target}"}), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = self._current_profile()
        self._replace_current_profile(replace(profile, targets=profile.targets + (dialog.result_target(),)))
        self.targets.setCurrentRow(self.targets.count() - 1)
        self._update_preflight()

    def _edit_target(self) -> None:
        selected = self._selected_target()
        if selected is None:
            return
        dialog = ExportTargetDialog(selected, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.result_target()
        profile = self._current_profile()
        targets = tuple(updated if target.target_id == selected.target_id else target for target in profile.targets)
        self._replace_current_profile(replace(profile, targets=targets))
        for row in range(self.targets.count()):
            if self.targets.item(row).data(Qt.ItemDataRole.UserRole) == updated.target_id:
                self.targets.setCurrentRow(row)
                break
        self._update_preflight()

    def _duplicate_target(self) -> None:
        selected = self._selected_target()
        if selected is None:
            return
        profile = self._current_profile()
        duplicate = selected.duplicate()
        targets = list(profile.targets)
        try:
            index = targets.index(selected) + 1
        except ValueError:
            index = len(targets)
        targets.insert(index, duplicate)
        self._replace_current_profile(replace(profile, targets=tuple(targets)))
        self.targets.setCurrentRow(index)
        self._update_preflight()

    def _remove_target(self) -> None:
        selected = self._selected_target()
        if selected is None:
            return
        profile = self._current_profile()
        if len(profile.targets) <= 1:
            self.hint.setText("A profile must contain at least one target.")
            return
        targets = tuple(target for target in profile.targets if target.target_id != selected.target_id)
        self._replace_current_profile(replace(profile, targets=targets))
        self._update_preflight()

    # ------------------------------------------------------------------
    # Dynamic planned-file preflight
    # ------------------------------------------------------------------
    def _update_preflight(self, *_args) -> None:
        if not hasattr(self, "preflight"):
            return
        self.preflight.clear()
        selected = self.selected_uids()
        self._planned_artifacts = []

        if self._plan_callback is not None and selected:
            try:
                self._planned_artifacts = list(self._plan_callback(selected, self._current_profile()))
            except Exception as exc:
                self.preflight.addItem(f"⚠ Could not plan exports: {exc}")
                self.hint.setText("The selected profile could not be validated.")
                return

        if self._plan_callback is not None:
            if not selected:
                self.preflight.addItem("Select one or more graph outputs to preview their files.")
                self.hint.setText("")
                return
            if not self._planned_artifacts:
                self.preflight.addItem("No connected exportable inputs were found for the selected outputs and targets.")
                self.hint.setText("The current output/target selection produces no files.")
                return
            counts: dict[str, int] = {}
            for artifact in self._planned_artifacts:
                path = str(getattr(artifact, "relative_path", getattr(artifact, "filename", "")))
                counts[path.casefold()] = counts.get(path.casefold(), 0) + 1
            warnings = 0
            for artifact in self._planned_artifacts:
                path = str(getattr(artifact, "relative_path", artifact.filename))
                duplicate = counts.get(path.casefold(), 0) > 1
                detail = (
                    f"{path}  ·  {artifact.options.format_name} {artifact.options.bit_depth}-bit  ·  "
                    f"{artifact.options.channels} / {artifact.options.colour_encoding}  ·  "
                    f"{artifact.width} × {artifact.height}"
                )
                item = QListWidgetItem(("⚠ " if duplicate else "") + detail)
                if duplicate:
                    item.setToolTip("Another selected target resolves to the same path. Stable suffixes will be added before export.")
                    warnings += 1
                self.preflight.addItem(item)
                for warning in getattr(artifact, "warnings", ()):
                    self.preflight.addItem(QListWidgetItem(f"△ {artifact.label}: {warning}"))
                    warnings += 1
            target_count = sum(1 for target in self._current_profile().targets if target.enabled)
            if warnings:
                self.hint.setText(
                    f"Preflight: {len(self._planned_artifacts)} planned file(s) across {target_count} enabled target(s), "
                    f"{warnings} warning(s)."
                )
            else:
                self.hint.setText(
                    f"Preflight ready: {len(self._planned_artifacts)} file(s) across {target_count} enabled target(s). "
                    "Shared graph sources will be evaluated only once per resolution."
                )
            return

        # Compatibility fallback for callers/tests without a dynamic planner.
        filename_counts: dict[str, int] = {}
        for uid in selected:
            choice = self._choices.get(uid)
            if choice is None:
                continue
            for filename in choice.filenames:
                key = str(filename).casefold()
                filename_counts[key] = filename_counts.get(key, 0) + 1
        warning_count = 0
        file_count = 0
        for uid in selected:
            choice = self._choices.get(uid)
            if choice is None:
                continue
            for index, detail in enumerate(choice.file_details):
                filename = choice.filenames[index] if index < len(choice.filenames) else detail
                duplicate = filename_counts.get(str(filename).casefold(), 0) > 1
                item = QListWidgetItem(("⚠ " if duplicate else "") + detail)
                self.preflight.addItem(item)
                file_count += 1
                warning_count += int(duplicate)
            for warning in choice.warnings:
                self.preflight.addItem(QListWidgetItem(f"△ {choice.name}: {warning}"))
                warning_count += 1
        if not selected:
            self.preflight.addItem("Select one or more graph outputs to preview their files.")
            self.hint.setText("")
        elif not file_count:
            self.preflight.addItem("No connected exportable inputs were found for the selected outputs.")
            self.hint.setText("The selected outputs currently produce no files.")
        elif warning_count:
            self.hint.setText(f"Preflight: {file_count} planned file(s), {warning_count} warning(s).")
        else:
            self.hint.setText(f"Preflight ready: {file_count} planned file(s).")

    # ------------------------------------------------------------------
    # Destination and result
    # ------------------------------------------------------------------
    def _browse_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose export folder", self.directory.text())
        if selected:
            self.directory.setText(selected)

    def _validate_and_accept(self) -> None:
        if not self.selected_uids():
            self.hint.setText("Choose at least one Single Image Output or Texture Set Output.")
            return
        selected_texture_sets = any(
            self._choices.get(uid) is not None and self._choices[uid].kind == "Texture Set"
            for uid in self.selected_uids()
        )
        if selected_texture_sets and not any(target.enabled for target in self._current_profile().targets):
            self.hint.setText("Enable at least one export target for the selected Texture Set Outputs.")
            return
        directory = Path(self.directory.text()).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.hint.setText(f"Cannot create output folder: {exc}")
            return
        self.accept()

    def profile_library(self) -> ExportProfileLibrary:
        return ExportProfileLibrary(self._active_profile_id, tuple(self._profiles))

    def request(self) -> ExportRequest:
        return ExportRequest(
            node_uids=self.selected_uids(),
            directory=Path(self.directory.text()).expanduser(),
            collision=self.collision.currentText(),
            open_folder=self.open_folder.isChecked(),
            profile_library=self.profile_library().to_dict(),
            profile_id=self._active_profile_id,
        )
