from __future__ import annotations

import logging

from lmu_ep_client import logging_setup


def test_default_log_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(logging_setup.LOG_DIR_ENV, str(tmp_path))

    assert logging_setup.default_log_dir() == tmp_path


def test_configure_creates_log_file_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv(logging_setup.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(logging_setup, "_configured", False)
    root = logging.getLogger()
    existing_handlers = list(root.handlers)
    try:
        path = logging_setup.configure()
        logging.getLogger("test").warning("hello-world")
        for handler in root.handlers:
            handler.flush()

        assert path == tmp_path / logging_setup.LOG_FILENAME
        assert "hello-world" in path.read_text(encoding="utf-8")
    finally:
        for handler in list(root.handlers):
            if handler not in existing_handlers:
                root.removeHandler(handler)
                handler.close()
        logging_setup._configured = False


def test_configure_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv(logging_setup.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(logging_setup, "_configured", False)
    root = logging.getLogger()
    existing_handlers = list(root.handlers)
    try:
        logging_setup.configure()
        logging_setup.configure()

        added = [h for h in root.handlers if h not in existing_handlers]
        assert len(added) == 1
    finally:
        for handler in list(root.handlers):
            if handler not in existing_handlers:
                root.removeHandler(handler)
                handler.close()
        logging_setup._configured = False
