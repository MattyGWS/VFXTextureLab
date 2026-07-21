from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="vfxtl-package-custom-data-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.vfx_package import create_vfxpackage, inspect_vfxpackage


def main() -> None:
    QCoreApplication.setOrganizationName("VFXTextureLabTests")
    QCoreApplication.setApplicationName("VFX Texture Lab Package Custom Node Tests")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    package_source = Path(__file__).resolve().parents[1] / "examples" / "custom_node_template"
    library = window.package_manager.add_library(package_source, "Package Fixture Nodes")
    window._reload_custom_nodes()
    definition = window.registry.get_optional("com.example.sine_waves")
    assert definition is not None and definition.package is not None
    assert definition.package.source_kind == "library"

    scene = window.scene
    custom = scene.create_node("com.example.sine_waves", QPointF(0, 0), record_undo=False)
    output = scene.create_node(
        "graph.output",
        QPointF(280, 0),
        parameters={"name": "Pattern", "primary_preview": True},
        record_undo=False,
    )
    assert scene.add_connection(
        custom.output_ports["Value"], output.input_ports["Value"], record_undo=False
    ) is not None
    window.graph_asset.name = "Bundled Custom Node Fixture"
    window.graph_asset.asset_id = "bundled-custom-node-fixture"
    window._stash_active_graph_session()
    session = window._active_graph_session()
    data = window._project_data_for_session(session, serialise_live_instances=False)

    root = Path(tempfile.mkdtemp(prefix="vfxtl-package-custom-"))
    package_path = root / "custom.vfxpackage"
    info, _report = create_vfxpackage(
        package_path,
        data,
        owner_path=session.current_path,
        app_version="0.44.3",
        registry=window.registry,
    )
    info = inspect_vfxpackage(package_path)
    assert len(info.custom_nodes) == 1
    assert info.custom_nodes[0]["package_id"] == "com.example.sine_waves"

    # Remove the source library to simulate a recipient who does not have the node.
    window.package_manager.remove_library(library.uid)
    window._reload_custom_nodes()
    missing = window.registry.get_optional("com.example.sine_waves")
    assert missing is None or missing.package is None

    # Package installation uses the same managed custom-node installer as normal .vfxnodepkg files.
    assert window._ensure_package_custom_nodes(package_path, info, prompt=False)
    restored = window.registry.get_optional("com.example.sine_waves")
    assert restored is not None and restored.package is not None
    assert restored.package.source_kind == "managed"
    assert restored.package.version == "1.0.0"

    window.close()
    del app
    print(
        "vfxpackage custom-node test passed: external package collection, manifest inventory, "
        "recipient-side managed installation and registry reload"
    )


if __name__ == "__main__":
    main()
