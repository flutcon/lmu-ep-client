from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

logger = logging.getLogger(__name__)


class _LoggingWriter:
    """File-like sink that forwards writes to the logger.

    PyInstaller windowed builds set sys.stdout/sys.stderr to None, so any
    print() call raises AttributeError. This stand-in keeps print() working
    and funnels the text into the rotating log file.
    """

    def __init__(self, level: int) -> None:
        self._level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            logger.log(self._level, self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False


def attach_parent_console() -> bool:
    """Try to attach to the parent shell's console on Windows.

    When a `console=False` PyInstaller exe is launched from cmd/pwsh, no
    console is attached. AttachConsole(ATTACH_PARENT_PROCESS) reuses the
    launching terminal's console so CLI output is visible there.

    Returns True if a console was attached (or already present).
    """
    if os.name != "nt":
        return sys.stdout is not None and sys.stderr is not None

    import ctypes

    kernel32 = ctypes.windll.kernel32
    ATTACH_PARENT_PROCESS = -1
    if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        return False

    try:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
    except OSError:
        return False
    return True


def install_stdio_fallback() -> None:
    """Ensure sys.stdout and sys.stderr are writable.

    Replaces None (PyInstaller windowed mode with no parent console) with
    writers that funnel into the logger. Leaves existing real streams alone.
    """
    if sys.stdout is None:
        sys.stdout = _LoggingWriter(logging.INFO)  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _LoggingWriter(logging.ERROR)  # type: ignore[assignment]


def configure_startup_stdio(*, attach_console: bool) -> None:
    """Set up stdio for the process.

    If `attach_console` is True (CLI invocation), try to reuse the parent
    terminal so prints land where the user typed the command. Either way,
    install a fallback so None stdio never crashes a print().
    """
    if attach_console:
        attach_parent_console()
    install_stdio_fallback()
