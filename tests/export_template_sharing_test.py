from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Keep this regression away from the real user's library.
DATA_ROOT = Path(tempfile.mkdtemp(prefix="vfxtl-export-sharing-data-"))
os.environ["XDG_DATA_HOME"] = str(DATA_ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.export_templates import ExportTemplate, builtin_template, clone_as_custom
from vfx_texture_lab.export_template_library import (
    ExportTemplateLibraryError,
    installed_export_templates,
    install_vfxexport,
    read_vfxexport,
    write_vfxexport,
)
from vfx_texture_lab.ui.export_target_dialog import ExportTargetDialog
from vfx_texture_lab.vfx_package import (
    create_vfxpackage,
    inspect_vfxpackage,
    read_packaged_export_templates,
)


def authored_template(version: str = "2.3.0") -> ExportTemplate:
    raw = clone_as_custom(builtin_template("Unreal ORM"), name="Studio Unreal").to_dict()
    raw.update(
        template_id="template.studio-unreal",
        description="Our production Unreal packing layout.",
        author="Pipeline Team",
        asset_version=version,
        target="Unreal Engine 5",
    )
    return ExportTemplate.from_dict(raw)


def graph_with_template(template: ExportTemplate) -> dict:
    return {
        "format": "vfx-texture-lab-graph",
        "version": 16,
        "document": {},
        "graph_asset": {
            "asset_id": "asset.export-sharing",
            "name": "Export Sharing Fixture",
            "version": "1.0.0",
        },
        "nodes": [
            {
                "uid": "texture-output",
                "type": "output.texture_set",
                "parameters": {
                    "export_preset": "Custom Template",
                    "_custom_export_template": template.to_dict(),
                },
            }
        ],
        "connections": [],
        "groups": [],
        "export_profiles": {
            "format": "vfx-texture-lab-export-profiles",
            "version": 1,
            "active_profile_id": "profile.fixture",
            "profiles": [
                {
                    "profile_id": "profile.fixture",
                    "name": "Fixture",
                    "targets": [
                        {
                            "target_id": "target.fixture",
                            "name": "Unreal",
                            "template_name": template.name,
                            "custom_template": template.to_dict(),
                        }
                    ],
                }
            ],
        },
    }


def main() -> None:
    app = QApplication.instance() or QApplication([])
    root = Path(tempfile.mkdtemp(prefix="vfxtl-export-sharing-"))

    template = authored_template()
    shared = write_vfxexport(root / "Studio-Unreal", template)
    assert shared.suffix == ".vfxexport"
    loaded = read_vfxexport(shared)
    assert loaded.template_id == "template.studio-unreal"
    assert loaded.author == "Pipeline Team"
    assert loaded.asset_version == "2.3.0"
    assert loaded.target == "Unreal Engine 5"

    target, installed, action = install_vfxexport(shared)
    assert target.is_file() and action == "installed"
    assert len(installed_export_templates()) == 1
    try:
        install_vfxexport(shared)
    except ExportTemplateLibraryError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Stable-ID conflict was not detected")

    updated_file = write_vfxexport(root / "Studio-Unreal-Updated", authored_template("2.4.0"))
    target2, updated, action2 = install_vfxexport(updated_file, conflict="update")
    assert target2 == target and action2 == "updated" and updated.asset_version == "2.4.0"
    _side_path, side, side_action = install_vfxexport(updated_file, conflict="side-by-side")
    assert side_action == "side-by-side"
    assert side.template_id != updated.template_id
    assert len(installed_export_templates()) == 2

    dialog = ExportTargetDialog()
    choices = {dialog.template.itemText(i) for i in range(dialog.template.count())}
    assert "Studio Unreal" in choices
    dialog.template.setCurrentText("Studio Unreal")
    target_result = dialog.result_target()
    assert target_result.custom_template
    assert target_result.custom_template["template_id"] == "template.studio-unreal"
    dialog.close()

    package = root / "sharing.vfxpackage"
    info, _report = create_vfxpackage(
        package,
        graph_with_template(template),
        owner_path=root / "sharing.vfxgraph",
        app_version="0.45.2",
        include_export_templates=True,
    )
    assert len(info.export_templates) == 1
    inspected = inspect_vfxpackage(package)
    assert inspected.export_templates[0]["template_id"] == template.template_id
    packaged = read_packaged_export_templates(package, inspected)
    assert len(packaged) == 1 and packaged[0].name == template.name

    compact = root / "sharing-compact.vfxpackage"
    compact_info, _ = create_vfxpackage(
        compact,
        graph_with_template(template),
        owner_path=root / "sharing.vfxgraph",
        app_version="0.45.2",
        include_export_templates=False,
    )
    assert not compact_info.export_templates

    main_window = (ROOT / "vfx_texture_lab/main_window.py").read_text(encoding="utf-8")
    editor_ui = (ROOT / "vfx_texture_lab/ui/export_template_dialog.py").read_text(encoding="utf-8")
    package_ui = (ROOT / "vfx_texture_lab/ui/vfx_package.py").read_text(encoding="utf-8")
    assert "Install Export Template…" in main_window
    assert "Import .vfxexport…" in editor_ui
    assert "Install in User Templates" in editor_ui
    assert "Include graph-local export templates" in package_ui

    print(
        "Export template sharing test passed: metadata, .vfxexport round-trip, stable-ID conflict handling, "
        "installed-target discovery, graph-local snapshots and optional .vfxpackage inclusion."
    )


if __name__ == "__main__":
    main()
