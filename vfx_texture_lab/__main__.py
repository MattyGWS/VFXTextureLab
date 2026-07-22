from __future__ import annotations

import ctypes
import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .theme import build_stylesheet, resolve_theme, set_active_theme


def _package_smoke_arguments(arguments: list[str]) -> tuple[bool, bool, Path | None]:
    if "--package-smoke-test" not in arguments:
        return False, False, None
    require_frozen = "--require-frozen" in arguments
    json_path: Path | None = None
    if "--json" in arguments:
        index = arguments.index("--json")
        if index + 1 >= len(arguments):
            raise ValueError("--json requires an output path")
        json_path = Path(arguments[index + 1]).expanduser()
    return True, require_frozen, json_path


def _run_package_smoke(arguments: list[str]) -> int | None:
    enabled, require_frozen, json_path = _package_smoke_arguments(arguments)
    if not enabled:
        return None
    from .package_smoke import run_package_smoke_test, write_smoke_report

    report = run_package_smoke_test(require_frozen=require_frozen)
    write_smoke_report(report, json_path)
    return 0 if report.ok else 1


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "MattyGWS.VFXTextureLab"
        )
    except Exception:
        # Cosmetic taskbar grouping must never prevent startup.
        pass


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    smoke_result = _run_package_smoke(arguments)
    if smoke_result is not None:
        return smoke_result

    # Importing the complete window only for normal GUI startup keeps the
    # packaging smoke test fast and independent of a display server.
    from .main_window import MainWindow

    _set_windows_app_user_model_id()
    QCoreApplication.setOrganizationName("VFXTextureLab")
    QCoreApplication.setApplicationName("VFX Texture Lab")
    QCoreApplication.setApplicationVersion(__version__)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    qt_arguments = [sys.argv[0], *arguments]
    app = QApplication(qt_arguments)
    app.setStyle("Fusion")
    try:
        app.setWindowIcon(QIcon(str(files("vfx_texture_lab.assets").joinpath("app_icon.png"))))
    except Exception:
        pass
    settings = QSettings()
    app_data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    theme_directory = app_data / "themes"
    selected_theme = str(settings.value("appearance/theme", "midnight") or "midnight")
    theme = resolve_theme(selected_theme, theme_directory)
    set_active_theme(theme)
    app.setStyleSheet(build_stylesheet(theme))

    window = MainWindow()
    window.show()
    requested_paths = [
        Path(value).expanduser() for value in arguments
        if not value.startswith("--") and Path(value).expanduser().is_file()
    ]
    if requested_paths:
        QTimer.singleShot(0, lambda: [window.open_external_path(path) for path in requested_paths])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
