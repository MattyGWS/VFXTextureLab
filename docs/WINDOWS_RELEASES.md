# Automated Windows builds and releases

The repository builds Windows x64 packages on a clean GitHub Windows runner. Development can remain entirely on Linux; PyInstaller and Inno Setup never need to be installed locally.

## Outputs

Every successful workflow run produces:

- `VFXTextureLab-<version>-Windows-x64-Portable.zip`
- `VFXTextureLab-<version>-Windows-x64-Setup.exe`
- `VFXTextureLab-<version>-Windows-x64-SHA256.txt`
- Source, frozen-build, and installed-application smoke-test reports

The installer is per-user by default, creates an uninstaller, offers a desktop shortcut, and associates `.vfxgraph`, `.vfxpackage`, `.vfxexport`, and `.vfxnodepkg` files with VFX Texture Lab.

## Test build from Linux

1. Push the desired commit to GitHub.
2. Open **Actions → Build Windows app**.
3. Choose **Run workflow**.
4. Leave **test-build** selected.
5. Download the artifact from the completed workflow run.

No tag or GitHub Release is created. Workflow artifacts are retained for 14 days.

## Draft a public release

The normal maintainer path from Linux is the guarded one-command script:

```bash
./tools/publish_windows_release.sh
```

Before running it, set the same new version in `pyproject.toml` and
`vfx_texture_lab/__init__.py`, then add a matching `## <version>` section to
`CHANGELOG.md`. The script shows all pending files, commits them as
`Release <version>`, pushes `main`, starts the draft-release workflow, waits for
the Windows build and installer smoke tests, verifies all three release assets,
then asks once more before making the release public.

Use `--yes` only when an unattended publication is genuinely intended.

The equivalent manual route is:

1. Set the same version in `pyproject.toml` and `vfx_texture_lab/__init__.py`.
2. Add a matching `## <version>` section to `CHANGELOG.md`.
3. Push the final commit.
4. Run **Build Windows app** with **draft-release** selected.
5. Test the generated installer from the workflow artifact.
6. Open the draft in **Releases** and choose **Publish release** when approved.

The workflow creates the matching `v<version>` tag and draft release, derives the release notes from `CHANGELOG.md`, and attaches both packages plus their SHA-256 checksums.

Pushing an existing matching version tag also runs draft-release mode automatically. A tag that does not match the project version fails the workflow instead of publishing incorrectly named binaries.

## What the workflow validates

Before producing downloadable files, the workflow checks that:

- project and package versions match;
- PySide6, Pillow, NumPy, rendercanvas, wgpu, and both wgpu backends import;
- at least 100 WGSL files are present;
- all bundled environment archives open;
- bundled declarative node manifests parse;
- the complete built-in node registry loads;
- the frozen directory contains Qt's Windows platform plugin and a wgpu-native DLL;
- the actual frozen `.exe` passes the same non-interactive checks;
- the generated installer can install, launch its packaged self-test, and uninstall silently on a clean runner path.

A missing DLL or runtime asset therefore fails on GitHub rather than becoming a broken downloadable installer.

## Local Windows build, when needed

The official path is GitHub Actions. For diagnosing a packaging problem on a Windows machine:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install . "pyinstaller>=6.15,<7"
.\.venv\Scripts\python tools\windows_release.py prepare `
  --version-info packaging\windows\generated_version_info.txt `
  --release-notes build\release-notes.md `
  --metadata-json build\release-metadata.json
.\.venv\Scripts\pyinstaller --noconfirm --clean packaging\windows\VFXTextureLab.spec
.\.venv\Scripts\python tools\windows_release.py verify `
  --dist "dist\VFX Texture Lab" `
  --smoke-json build\frozen-smoke.json
```

Compile `packaging/windows/VFXTextureLab.iss` with Inno Setup after setting the four `VFXTL_*` environment variables used by the GitHub workflow.

## Signing

The current output is unsigned and may trigger Microsoft Defender SmartScreen while the project has no established signing reputation. Code signing can be added later without changing the PyInstaller or installer layout.
