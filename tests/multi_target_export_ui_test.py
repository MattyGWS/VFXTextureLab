from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile

root = Path(tempfile.mkdtemp(prefix="vfx-multi-target-ui-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.export_profiles import ExportProfileLibrary, ExportProfileSet, ExportTarget
from vfx_texture_lab.exporting import ExportOptions
from vfx_texture_lab.ui.export_dialog import ExportDialog, ExportOutputChoice


def artifact(path: str, target: str):
    folder, _, filename = path.rpartition("/")
    return SimpleNamespace(
        relative_path=path,
        relative_directory=folder,
        filename=filename,
        target_name=target,
        label=f"{target} · Material",
        width=1024,
        height=1024,
        options=ExportOptions("PNG", 8, "RGBA", "Red", "Linear"),
        warnings=(),
    )


def main() -> None:
    app = QApplication.instance() or QApplication([])
    profile = ExportProfileSet.from_dict(
        {
            "name": "Unreal + Source",
            "targets": [
                {"name": "Unreal", "template_name": "Unreal ORM", "subfolder": "Unreal"},
                {"name": "Source", "template_name": "Generic PBR Separate", "subfolder": "Source"},
            ],
        }
    )
    library = ExportProfileLibrary(profile.profile_id, (profile,))

    def plan(_uids, selected_profile):
        result = []
        for target in selected_profile.targets:
            if target.enabled:
                result.append(artifact(f"{target.name}/Material.png", target.name))
        return result

    choices = [ExportOutputChoice("set", "Material", "Texture Set", "Current layout", True)]
    dialog = ExportDialog(
        choices,
        {"set"},
        root,
        profile_library=library,
        plan_callback=plan,
    )
    assert dialog.profile_combo.currentText() == "Unreal + Source"
    assert dialog.targets.count() == 2
    assert dialog.preflight.count() == 2
    assert "2 file(s)" in dialog.hint.text()

    dialog.targets.item(1).setCheckState(Qt.CheckState.Unchecked)
    app.processEvents()
    assert dialog.preflight.count() == 1
    request = dialog.request()
    assert request.profile().name == "Unreal + Source"
    assert sum(target.enabled for target in request.profile().targets) == 1
    dialog.close()
    app.processEvents()

    print(
        "Multi-target export UI test passed: graph-local profile selection, target checkboxes, dynamic planned-file "
        "preflight and request serialization."
    )


if __name__ == "__main__":
    main()
