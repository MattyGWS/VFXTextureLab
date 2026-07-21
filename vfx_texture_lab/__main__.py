from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths, QTimer, Qt
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import build_stylesheet, resolve_theme, set_active_theme


def main() -> int:
    QCoreApplication.setOrganizationName("VFXTextureLab")
    QCoreApplication.setApplicationName("VFX Texture Lab")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
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
        Path(value).expanduser() for value in sys.argv[1:]
        if Path(value).expanduser().is_file()
    ]
    if requested_paths:
        QTimer.singleShot(0, lambda: [window.open_external_path(path) for path in requested_paths])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
