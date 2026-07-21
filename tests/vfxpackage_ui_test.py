from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="vfxtl-package-ui-data-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.ui.vfx_package import (
    VFXPackageDialog,
    VFXPackageExportOptionsDialog,
)
from vfx_texture_lab.vfx_package import create_vfxpackage, inspect_vfxpackage


def main() -> None:
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("VFX Texture Lab Package Tests")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    session = window._active_graph_session()
    assert session is not None
    window._stash_active_graph_session()
    data = window._project_data_for_session(session, serialise_live_instances=False)
    data["graph_asset"]["name"] = "Package UI Fixture"
    data["graph_asset"]["asset_id"] = "package-ui-fixture"

    root = Path(tempfile.mkdtemp(prefix="vfxtl-package-ui-"))
    package_path = root / "fixture.vfxpackage"
    info, _report = create_vfxpackage(
        package_path,
        data,
        owner_path=session.current_path,
        app_version="0.44.3",
        registry=window.registry,
    )
    inspected = inspect_vfxpackage(package_path)
    assert inspected.name == "Package UI Fixture"

    dialog = VFXPackageDialog(inspected, parent=window)
    button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "Open Temporarily" in button_texts
    assert "Extract as Editable Project…" in button_texts
    assert "Install to Asset Library" in button_texts
    dialog.close()

    options = VFXPackageExportOptionsDialog(parent=window)
    option_labels = {box.text() for box in options.findChildren(QCheckBox)}
    assert "Include source image files in the package" in option_labels
    assert options.include_image_source_files is True
    options.close()

    assert window._open_vfxpackage_temporarily(package_path, info)
    opened = window._active_graph_session()
    assert opened is not None
    assert opened.current_path is None
    assert opened.graph_asset.asset_id == "package-ui-fixture"
    assert "Package" in opened.display_name
    assert not opened.dirty

    window._inspect_graph_session(opened.uid)
    inspector_buttons = {
        button.text() for button in window.parameters_panel.findChildren(QPushButton)
    }
    assert "Export VFX Package…" in inspector_buttons
    assert window.export_vfxpackage_action.text() == "Export VFX Package…"
    assert window.open_vfxpackage_action.text() == "Open VFX Package…"
    assert window.install_vfxpackage_action.text() == "Install VFX Package…"

    window.close()
    del app
    print(
        "vfxpackage UI test passed: package actions, details dialog, clean temporary open "
        "and Inspector export entry point"
    )


if __name__ == "__main__":
    main()
