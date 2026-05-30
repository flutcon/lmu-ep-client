from __future__ import annotations

import os

import pytest

from lmu_ep_client.resources import APP_ICON_FILENAME, app_icon_path
from lmu_ep_client import resources


def test_app_icon_path_points_to_packaged_icon():
    path = app_icon_path()

    assert path.name == APP_ICON_FILENAME
    assert path.exists()


def test_app_icon_loads_as_qicon():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    assert not QIcon(str(app_icon_path())).isNull()


def test_apply_app_icon_sets_application_and_windows(monkeypatch):
    icon = object()
    app = _IconTarget()
    splash = _IconTarget()
    window = _IconTarget()
    monkeypatch.setattr(resources, "make_app_icon", lambda: icon)

    result = resources.apply_app_icon(app, splash, window)

    assert result is icon
    assert app.icon is icon
    assert splash.icon is icon
    assert window.icon is icon


class _IconTarget:
    def __init__(self):
        self.icon = None

    def setWindowIcon(self, icon):
        self.icon = icon
