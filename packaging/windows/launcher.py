"""PyInstaller entry point for VFX Texture Lab.

Keep this tiny and outside the package so PyInstaller starts the application in
exactly the same way as the installed console entry point.
"""

from vfx_texture_lab.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
