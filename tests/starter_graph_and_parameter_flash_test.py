from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    params = (root / "vfx_texture_lab/ui/parameters.py").read_text()
    main_window = (root / "vfx_texture_lab/main_window.py").read_text()

    # Parameter rebuilding must use a hidden atomic widget swap rather than
    # deleting visible form rows, which could flash native X11 child windows.
    assert "new_host = QWidget(self.scroll.viewport())" in params
    assert "new_host.hide()" in params
    assert "detached = self.scroll.takeWidget()" in params
    assert "self.scroll.setWidget(new_host)" in params
    assert "while self.form.rowCount()" not in params
    assert "CompactSpinBox(self)" in params
    assert "CompactDoubleSpinBox(self)" in params
    assert "QToolButton(row)" in params

    start = main_window.index("    def _create_starter_graph")
    end = main_window.index("    def _undo_clean_changed", start)
    starter = main_window[start:end]
    assert "terrain.hydraulic_erosion" not in starter
    assert "terrain.thermal_erosion" not in starter
    assert starter.count('create_node("generator.constant"') == 3
    assert 'metallic.parameters["value"] = 0.0' in starter
    assert 'specular.parameters["value"] = 0.0' in starter
    assert 'material_output.input_ports["Metallic"]' in starter
    assert 'material_output.input_ports["Specular Level"]' in starter

    print("starter graph and parameter flash regression passed")


if __name__ == "__main__":
    main()
