from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    shader = (ROOT / "vfx_texture_lab" / "shaders" / "preview_3d.wgsl").read_text(encoding="utf-8")
    renderer = (ROOT / "vfx_texture_lab" / "three_d" / "renderer.py").read_text(encoding="utf-8")

    start = shader.index("fn vs_wireframe")
    end = shader.index("@fragment", start)
    wireframe_vertex = shader[start:end]
    assert "uniforms.view_proj * world" in wireframe_vertex
    assert "clip_position.z -=" not in wireframe_vertex
    assert "clip_position.z +=" not in wireframe_vertex
    assert "clip_position.w" not in wireframe_vertex

    pipeline_start = renderer.index("def _wireframe_pipeline")
    pipeline_end = renderer.index("def _ensure_post_pipeline", pipeline_start)
    wireframe_pipeline = renderer[pipeline_start:pipeline_end]
    assert '"depth_write_enabled": False' in wireframe_pipeline
    assert '"depth_compare": "less-equal"' in wireframe_pipeline

    print("wireframe depth regression test passed")


if __name__ == "__main__":
    main()
