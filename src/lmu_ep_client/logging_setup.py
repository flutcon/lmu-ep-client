from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "client.log"
MAX_BYTES = 2_000_000
BACKUP_COUNT = 5
LOG_DIR_ENV = "LMU_EP_LOG_DIR"


def default_log_dir() -> Path:
    """Per-user, machine-local log directory.

    LOCALAPPDATA (not APPDATA) so logs don't roam — they're disk-cheap and
    machine-specific debugging artifacts, not user settings. LMU_EP_LOG_DIR
    overrides for tests and ad-hoc redirection.
    """
    override = os.environ.get(LOG_DIR_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "lmu-ep-client" / "logs"


def default_log_path() -> Path:
    return default_log_dir() / LOG_FILENAME


_configured = False


def configure(
    *,
    log_path: Path | None = None,
    level: int = logging.INFO,
) -> Path:
    """Attach a rotating file handler to the root logger. Idempotent.

    Returns the resolved log path so callers (e.g. the GUI) can surface it.
    """
    global _configured
    path = log_path or default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if not _configured:
        handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler.set_name("lmu-ep-client.file")
        root.addHandler(handler)
        _configured = True

    root.setLevel(level)
    return path


def set_level(level: int) -> None:
    logging.getLogger().setLevel(level)
