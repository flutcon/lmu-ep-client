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

    assert "collect_all('PySide6')" in spec_text
    assert "_qt_datas" in spec_text
    assert "_qt_binaries" in spec_text
    assert "_qt_hidden" in spec_text
    assert "console=True" in spec_text
