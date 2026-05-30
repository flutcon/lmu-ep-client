from __future__ import annotations

import sys
from pathlib import Path

APP_ICON_FILENAME = "app.ico"


def app_icon_path() -> Path:
    """Return the app icon path for source and PyInstaller-frozen runs."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "lmu_ep_client" / "assets" / APP_ICON_FILENAME
    return Path(__file__).resolve().parent / "assets" / APP_ICON_FILENAME


def make_app_icon():
    from PySide6.QtGui import QIcon

    return QIcon(str(app_icon_path()))


def apply_app_icon(app, *windows):
    icon = make_app_icon()
    app.setWindowIcon(icon)
    for window in windows:
        window.setWindowIcon(icon)
    return icon
