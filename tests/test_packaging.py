from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vendored_shared_memory_is_packaged_with_client_distribution():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "pyLMUSharedMemory" not in config["project"].get("dependencies", [])
    assert "vendor" in config["tool"]["setuptools"]["packages"]["find"]["where"]
