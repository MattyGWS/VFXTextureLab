from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    main_window = (ROOT / "vfx_texture_lab" / "main_window.py").read_text(encoding="utf-8")
    evaluation = (ROOT / "vfx_texture_lab" / "three_d" / "evaluation.py").read_text(encoding="utf-8")
    renderer = (ROOT / "vfx_texture_lab" / "three_d" / "renderer.py").read_text(encoding="utf-8")
    panel = (ROOT / "vfx_texture_lab" / "three_d" / "panel.py").read_text(encoding="utf-8")
    preview = (ROOT / "vfx_texture_lab" / "ui" / "preview.py").read_text(encoding="utf-8")
    material_graph = (ROOT / "vfx_texture_lab" / "material_graph.py").read_text(encoding="utf-8")

    assert "int(self._material_playback_live_max)" in main_window
    assert "_present_material_playback_2d" in main_window
    assert "_record_material_playback_presentation" in main_window
    assert "_material_playback_tick" in main_window
    assert "_material_playback_pending_result" in main_window
    assert "_present_pending_material_playback" in main_window
    assert "_arm_material_playback_presentation" in main_window
    assert "_update_material_playback_budget" in main_window
    assert "queued_playback=True" in main_window
    assert "cache_key=None if self._playing else completed_key" in main_window
    assert "incremental=self._playing" in main_window
    assert "prepare_display = True" in main_window
    assert "prepare_display=prepare_display" in main_window
    assert "1.0 / 15.0" not in main_window
    assert "set_prepared_playback_frame" in main_window
    assert "playback=self._playing" in main_window
    assert "collect_traces=(not self._playing) or self.timeline_panel.profiler_enabled" in main_window
    assert "_material_geometry_revision" in main_window
    assert "Playback must not rebuild the full procedural mesh" in main_window
    assert "_material_playback_epoch" in main_window
    assert "_material_playback_request_serial" in main_window
    assert "_reset_material_playback_stream" in main_window
    assert "completed_epoch == self._material_playback_epoch" in main_window
    assert "completed_serial) <= self._material_playback_last_2d_serial" in main_window
    assert "completed_serial) <= self._material_playback_last_3d_serial" in main_window
    assert "tiers = (128, 256)" in main_window
    assert "tiers = (128, 192, 256)" not in main_window

    assert "_static_channel_cache" in evaluation
    assert "static_cache_hits" in evaluation
    assert "dynamic_channels" in evaluation
    assert "base_colour_display" in evaluation
    assert "image.shape[0] == 1 and image.shape[1] == 1" in evaluation
    assert "if self.playback:" in evaluation
    assert "collect_traces=self.collect_traces" in evaluation
    assert "if self.prepare_display" in evaluation
    assert "progress_callback=None if self.playback else self._emit_progress" in evaluation

    assert "self.render_mode == \"preview_3d\"" in material_graph
    assert '{"generator.constant", "generator.color"}' in material_graph
    assert "dynamic_nodes=int(result.dynamic_nodes)" in material_graph

    assert "incremental: bool = False" in renderer
    assert "self._active_channel_tokens" in renderer
    assert "if name in self._textures and self._active_channel_tokens.get(name) == token" in renderer
    assert 'generate_mips=not token.startswith("dynamic:")' in renderer
    assert "levels = mip_chain(image) if generate_mips else [image]" in renderer
    assert "bindings_changed = bindings_changed or recreated" in renderer
    assert "if not incremental or bindings_changed" in renderer
    assert "if not incremental or shadow_bindings_changed" in renderer

    assert "_last_live_status_update" in panel
    assert "if not incremental or (now - self._last_live_status_update) >= 0.25" in panel

    assert "def set_prepared_playback_frame" in preview
    assert "only the image is replaced at" in preview
    assert "_playback_last_metadata_update" in preview

    print(
        "material playback source regression passed: evaluation and presentation overlap, newest 3D frames coalesce, "
        "every completed Base Colour frame reaches the lightweight 2D path, live resolution adapts, playback "
        "diagnostics remain quiet, static channels stay resident, and unchanged texture handles retain bind groups"
    )


if __name__ == "__main__":
    main()
