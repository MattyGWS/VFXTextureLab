# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
VERSION_INFO = PROJECT_ROOT / "packaging" / "windows" / "generated_version_info.txt"
ICON = PROJECT_ROOT / "packaging" / "windows" / "VFXTextureLab.ico"

if not VERSION_INFO.is_file():
    raise FileNotFoundError(
        "Run tools/windows_release.py prepare before PyInstaller so Windows version metadata exists."
    )
if not ICON.is_file():
    raise FileNotFoundError(f"Missing Windows application icon: {ICON}")

# Keep these directories intact because the application deliberately loads WGSL,
# environment maps, and declarative custom-node packages at runtime.
datas = [
    (str(PROJECT_ROOT / "vfx_texture_lab" / "shaders"), "vfx_texture_lab/shaders"),
    (
        str(PROJECT_ROOT / "vfx_texture_lab" / "assets" / "environments"),
        "vfx_texture_lab/assets/environments",
    ),
    (
        str(PROJECT_ROOT / "vfx_texture_lab" / "node_packages"),
        "vfx_texture_lab/node_packages",
    ),
    (str(PROJECT_ROOT / "vfx_texture_lab" / "assets" / "app_icon.png"), "vfx_texture_lab/assets"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / "CHANGELOG.md"), "."),
]
datas += copy_metadata("vfx-texture-lab")

# wgpu 0.31 supplies its own PyInstaller hook, which collects resources, native
# libraries, and the default backend. The explicit backend imports below are a
# second guard against a future hook/import change. rendercanvas chooses its Qt
# implementation dynamically, so include that backend explicitly.
hiddenimports = [
    "rendercanvas.qt",
    "wgpu.backends.auto",
    "wgpu.backends.wgpu_native",
]

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "windows" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VFX Texture Lab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION_INFO),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VFX Texture Lab",
    contents_directory="_internal",
)
