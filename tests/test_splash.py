from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QSplashScreen  # noqa: E402

from lmu_ep_client.splash import SPLASH_HEIGHT, SPLASH_WIDTH, make_splash  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_make_splash_returns_qsplashscreen_with_expected_size(qapp):
    splash = make_splash()

    assert isinstance(splash, QSplashScreen)
    pixmap = splash.pixmap()
    assert pixmap.width() == SPLASH_WIDTH
    assert pixmap.height() == SPLASH_HEIGHT
