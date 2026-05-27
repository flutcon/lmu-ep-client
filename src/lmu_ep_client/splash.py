from __future__ import annotations

SPLASH_WIDTH = 360
SPLASH_HEIGHT = 120
BG_COLOR = "#1f1f1f"
FG_COLOR = "#e6e6e6"
ACCENT_COLOR = "#4ea1ff"


def make_splash():
    """Build a tiny QSplashScreen.

    Caller must have created QApplication first. The pixmap is drawn
    programmatically so we don't have to ship an image asset.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    pixmap = QPixmap(SPLASH_WIDTH, SPLASH_HEIGHT)
    pixmap.fill(QColor(BG_COLOR))

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(QColor(ACCENT_COLOR))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            pixmap.rect().adjusted(0, 24, 0, 0),
            Qt.AlignHCenter | Qt.AlignTop,
            "LMU EP Client",
        )

        painter.setPen(QColor(FG_COLOR))
        body_font = QFont()
        body_font.setPointSize(9)
        painter.setFont(body_font)
        painter.drawText(
            pixmap.rect().adjusted(0, 0, 0, -24),
            Qt.AlignHCenter | Qt.AlignBottom,
            "Loading…",
        )
    finally:
        painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    return splash
