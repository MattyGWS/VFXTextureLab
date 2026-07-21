from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from vfx_texture_lab.export_templates import builtin_template
from vfx_texture_lab.ui.export_dialog import ExportDialog, ExportOutputChoice
from vfx_texture_lab.ui.export_template_dialog import ExportTemplateDialog


def main() -> None:
    app = QApplication.instance() or QApplication([])

    editor = ExportTemplateDialog(builtin_template("Unreal ORM"))
    assert editor.file_list.count() == 6
    assert editor.result_template().name == "Custom Unreal ORM"
    assert "Ready" in editor.validation.text()

    editor.file_list.setCurrentRow(editor.file_list.count() - 1)
    assert editor.map_name.text() == "ORM"
    assert editor.layout_combo.currentText() == "RGB"
    assert editor.channel_rows["R"][1].currentText() == "Ambient Occlusion"
    assert editor.channel_rows["G"][1].currentText() == "Roughness"
    assert editor.channel_rows["B"][1].currentText() == "Metallic"

    editor._duplicate_file()
    assert editor.file_list.count() == 7
    assert "Copy" in editor.file_name.text()
    editor._remove_file()
    assert editor.file_list.count() == 6

    editor.builtin_combo.setCurrentText("VFX RGBA Masks")
    editor._load_builtin()
    assert editor.file_list.count() == 1
    assert editor.map_name.text() == "Masks"
    assert editor.layout_combo.currentText() == "RGBA"
    editor.close()

    choices = [
        ExportOutputChoice(
            "a",
            "Material",
            "Texture Set",
            "Unreal ORM · 2 files",
            True,
            ("shared.png", "Material_ORM.png"),
            (
                "shared.png  ·  PNG 8-bit  ·  RGBA / sRGB  ·  1024 × 1024",
                "Material_ORM.png  ·  PNG 8-bit  ·  RGB / Linear  ·  1024 × 1024",
            ),
            ("Height is being exported at 8-bit precision.",),
        ),
        ExportOutputChoice(
            "b",
            "Mask",
            "Single Image",
            "Linear Data · 1 file",
            True,
            ("shared.png",),
            ("shared.png  ·  PNG 16-bit  ·  Grayscale / Linear  ·  1024 × 1024",),
            (),
        ),
    ]
    export = ExportDialog(choices, None, Path.home())
    assert export.outputs.count() == 2
    assert export.preflight.count() == 4
    assert "warning" in export.hint.text().lower()
    assert export.preflight.item(0).text().startswith("⚠")
    export._set_all_checked(False)
    assert "Select one or more" in export.preflight.item(0).text()
    export.close()

    app.processEvents()
    print(
        "Export template UI test passed: built-in customisation, file add/duplicate/remove, source assignments, "
        "built-in reload and selected-output preflight warnings/collisions."
    )


if __name__ == "__main__":
    main()
