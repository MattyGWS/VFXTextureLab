from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "vfx_texture_lab/three_d/panel.py").read_text()

assert "self.status.setWordWrap(False)" in source
assert "self.status.setFixedHeight" in source
assert "elidedText" in source
assert "self._last_summary" in source
assert "self._set_status_text(self._last_summary)" in source

print("3D status layout test passed")
