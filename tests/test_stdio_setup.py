from __future__ import annotations

import logging
import sys

from lmu_ep_client import stdio_setup


def test_logging_writer_forwards_lines(caplog):
    writer = stdio_setup._LoggingWriter(logging.INFO)

    with caplog.at_level(logging.INFO, logger=stdio_setup.logger.name):
        writer.write("hello\nworld\n")

    messages = [r.getMessage() for r in caplog.records]
    assert "hello" in messages
    assert "world" in messages


def test_logging_writer_buffers_partial_line(caplog):
    writer = stdio_setup._LoggingWriter(logging.INFO)

    with caplog.at_level(logging.INFO, logger=stdio_setup.logger.name):
        writer.write("partial")
        assert all("partial" not in r.getMessage() for r in caplog.records)
        writer.write(" line\n")

    messages = [r.getMessage() for r in caplog.records]
    assert any("partial line" == m for m in messages)


def test_logging_writer_flush_emits_buffer(caplog):
    writer = stdio_setup._LoggingWriter(logging.WARNING)

    with caplog.at_level(logging.WARNING, logger=stdio_setup.logger.name):
        writer.write("no newline yet")
        writer.flush()

    messages = [r.getMessage() for r in caplog.records]
    assert "no newline yet" in messages


def test_install_stdio_fallback_replaces_none(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    stdio_setup.install_stdio_fallback()

    assert isinstance(sys.stdout, stdio_setup._LoggingWriter)
    assert isinstance(sys.stderr, stdio_setup._LoggingWriter)


def test_install_stdio_fallback_leaves_real_streams_alone(monkeypatch):
    sentinel_out = sys.stdout
    sentinel_err = sys.stderr

    stdio_setup.install_stdio_fallback()

    assert sys.stdout is sentinel_out
    assert sys.stderr is sentinel_err
