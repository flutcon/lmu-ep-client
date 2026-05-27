from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vendored_shared_memory_is_packaged_with_client_distribution():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "pyLMUSharedMemory" not in config["project"].get("dependencies", [])
    assert "vendor" in config["tool"]["setuptools"]["packages"]["find"]["where"]


def test_pyside6_is_runtime_dependency():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "PySide6>=6.7" in config["project"]["dependencies"]


def test_pyinstaller_spec_collects_pyside6_assets():
    spec_text = (ROOT / "lmu-ep-client.spec").read_text(encoding="utf-8")

    # Only the three Qt modules the GUI actually uses are collected (as hidden
    # imports, since the imports are lazy). Bundling all of PySide6 dragged in
    # ~290 MB of unused Qt WebEngine.
    assert "collect_all('PySide6')" not in spec_text
    assert "PySide6.QtWidgets" in spec_text
    assert "_qt_hidden" in spec_text
    assert "_qt_excludes" in spec_text
    assert "console=False" in spec_text


def test_pyinstaller_spec_excludes_qt_webengine():
    spec_text = (ROOT / "lmu-ep-client.spec").read_text(encoding="utf-8")

    assert "PySide6.QtWebEngineCore" in spec_text
