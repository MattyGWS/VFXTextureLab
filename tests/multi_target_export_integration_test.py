from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile

root = Path(tempfile.mkdtemp(prefix="vfx-multi-target-integration-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ["XDG_DATA_HOME"] = str(root / "data")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from vfx_texture_lab.export_plan import ExportArtifact, ExportSource
from vfx_texture_lab.export_profiles import ExportProfileLibrary, ExportProfileSet
from vfx_texture_lab.exporting import ExportOptions
from vfx_texture_lab.main_window import MainWindow
from vfx_texture_lab.ui.export_dialog import ExportRequest


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.periodic_autosave_timer.stop()
    window.graph_asset_watch_timer.stop()
    app.processEvents()

    profile = ExportProfileSet.from_dict(
        {
            "name": "Studio Multi Target",
            "targets": [
                {"name": "Unreal", "template_name": "Unreal ORM", "subfolder": "Unreal"},
                {"name": "Archive", "template_name": "Generic PBR Separate", "subfolder": "Archive"},
            ],
        }
    )
    window.export_profiles = ExportProfileLibrary(profile.profile_id, (profile,))
    session = window._active_graph_session()
    assert session is not None
    session.export_profiles = window.export_profiles
    payload = window._project_data_for_session(session)
    restored = ExportProfileLibrary.from_dict(payload.get("export_profiles"))
    assert restored.active_profile().name == "Studio Multi Target"
    assert len(restored.active_profile().targets) == 2

    calls: list[tuple] = []
    image = np.full((8, 8, 4), 0.4, dtype=np.float32)

    class Evaluator:
        def evaluate(self, node_uid, width, height, **kwargs):
            calls.append((node_uid, kwargs.get("output_name"), width, height))
            return SimpleNamespace(error="", image=image)

    original_evaluator = window.evaluator
    window.evaluator = Evaluator()
    source = ExportSource("shared-source", "Image")
    options = ExportOptions("PNG", 8, "RGBA", "Red", "Linear")
    artifacts = [
        ExportArtifact(
            owner_uid="set",
            owner_name="Material",
            label="Unreal · Material",
            filename="Material.png",
            width=8,
            height=8,
            options=options,
            sources=(("Image", source),),
            relative_directory="Unreal",
            target_name="Unreal",
        ),
        ExportArtifact(
            owner_uid="set",
            owner_name="Material",
            label="Archive · Material",
            filename="Material.png",
            width=8,
            height=8,
            options=options,
            sources=(("Image", source),),
            relative_directory="Archive",
            target_name="Archive",
        ),
    ]
    request = ExportRequest(
        node_uids=["set"],
        directory=root / "exports",
        collision="Replace existing",
        open_folder=False,
        profile_library=window.export_profiles.to_dict(),
        profile_id=profile.profile_id,
    )
    exported, errors, cancelled, skipped = window._execute_export_request(
        SimpleNamespace(), artifacts, request
    )
    assert not errors and not cancelled and skipped == 0
    assert len(exported) == 2
    assert (root / "exports/Unreal/Material.png").is_file()
    assert (root / "exports/Archive/Material.png").is_file()
    assert len(calls) == 1, calls

    window.evaluator = original_evaluator
    for graph_session in window._graph_sessions.values():
        graph_session.scene.undo_stack.clear()
        graph_session.scene.undo_stack.setClean()
        graph_session.document_dirty = False
        graph_session.recovered_dirty = False
    window.close()
    app.processEvents()
    print(
        "Multi-target export integration test passed: graph JSON profile persistence, target subfolders and "
        "one shared source evaluation reused across several production targets."
    )


if __name__ == "__main__":
    main()
