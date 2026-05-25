# GUI Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PySide6 launcher that opens when `lmu-ep-client` is started with no arguments, while preserving all existing CLI behavior when arguments are passed.

**Architecture:** Keep CLI parsing in `cli.py`, but branch to a lazy GUI launcher before constructing the parser when `len(sys.argv) == 1`. Put the Qt window and testable GUI helper functions in `src/lmu_ep_client/gui.py`; the helper functions handle config writes, display formatting, state validation, and poller argument construction, while the window calls existing `TrackingClient` and `poller.run(...)`.

**Tech Stack:** Python 3.10+, PySide6/Qt, PyInstaller, pytest, existing `TrackingClient`, existing `poller.run(...)`.

---

## File Structure

- Modify `pyproject.toml`
  Add `PySide6` as a runtime dependency.

- Modify `lmu-ep-client.spec`
  Collect PySide6 runtime assets for the one-file executable while keeping `console=True`.

- Modify `src/lmu_ep_client/cli.py`
  Add a lazy no-argument GUI branch and a small `_launch_gui()` wrapper.

- Create `src/lmu_ep_client/gui.py`
  Own the PySide6 window, background worker, pure helper functions, and launch function.

- Modify `tests/test_cli.py`
  Update no-argument expectations and add coverage that arguments still use the CLI path.

- Create `tests/test_gui.py`
  Cover pure helper behavior: API key save/load format, registration/member labels, validation, and poller kwargs.

- Modify `tests/test_packaging.py`
  Check PySide6 runtime dependency and PyInstaller collection configuration.

---

### Task 1: Add PySide6 Dependency And Packaging Checks

**Files:**
- Modify: `pyproject.toml`
- Modify: `lmu-ep-client.spec`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write failing packaging tests**

Add these tests to `tests/test_packaging.py` after the existing test:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_packaging.py -v
```

Expected: `test_pyside6_is_runtime_dependency` fails because `PySide6>=6.7` is not in dependencies, and `test_pyinstaller_spec_collects_pyside6_assets` fails because the spec does not collect PySide6 yet.

- [ ] **Step 3: Add PySide6 dependency**

Modify `pyproject.toml` so `[project].dependencies` is:

```toml
dependencies = [
    "questionary>=2.0",
    "PySide6>=6.7",
]
```

- [ ] **Step 4: Collect PySide6 in the PyInstaller spec**

Modify the top of `lmu-ep-client.spec` to include PySide6 collection:

```python
from PyInstaller.utils.hooks import collect_all

_q_datas, _q_binaries, _q_hidden = collect_all('questionary')
_pt_datas, _pt_binaries, _pt_hidden = collect_all('prompt_toolkit')
_wc_datas, _wc_binaries, _wc_hidden = collect_all('wcwidth')
_qt_datas, _qt_binaries, _qt_hidden = collect_all('PySide6')
```

Then update the `Analysis(...)` arguments:

```python
binaries=_q_binaries + _pt_binaries + _wc_binaries + _qt_binaries,
datas=_q_datas + _pt_datas + _wc_datas + _qt_datas,
hiddenimports=_q_hidden + _pt_hidden + _wc_hidden + _qt_hidden,
```

Keep this unchanged:

```python
console=True,
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
pytest tests/test_packaging.py -v
```

Expected: all packaging tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add pyproject.toml lmu-ep-client.spec tests/test_packaging.py
git commit -m "build: package pyside gui runtime"
```

---

### Task 2: Route No-Argument Launches To The GUI

**Files:**
- Modify: `src/lmu_ep_client/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI routing tests**

Add these tests near the top of `tests/test_cli.py`, after `_set_argv`:

```python
def test_no_args_launches_gui(monkeypatch):
    launched = {"count": 0}

    def fake_launch_gui():
        launched["count"] += 1

    monkeypatch.setattr(cli, "_launch_gui", fake_launch_gui)
    _set_argv(monkeypatch)

    cli.main()

    assert launched["count"] == 1


def test_args_preserve_cli_path(monkeypatch):
    seen = {}
    launched = {"count": 0}

    def fake_launch_gui():
        launched["count"] += 1

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_launch_gui", fake_launch_gui)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--config", str(Path("missing.toml")))

    cli.main()

    assert launched["count"] == 0
    assert seen["api_key"] is None
    assert seen["registration_id"] is None
```

Also add this import at the top of `tests/test_cli.py`:

```python
from pathlib import Path
```

Update the existing no-argument tests so they pass at least one CLI argument. Change:

```python
_set_argv(monkeypatch)
```

to:

```python
_set_argv(monkeypatch, "--config", str(tmp_path / "missing.toml"))
```

in `test_env_api_key_without_registration_id_falls_through_to_file_only`, and add `tmp_path` to that test signature:

```python
def test_env_api_key_without_registration_id_falls_through_to_file_only(monkeypatch, tmp_path):
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_cli.py::test_no_args_launches_gui tests/test_cli.py::test_args_preserve_cli_path -v
```

Expected: fails because `cli._launch_gui` does not exist.

- [ ] **Step 3: Add lazy GUI launcher branch**

In `src/lmu_ep_client/cli.py`, add this function after `_resolve_api_key(...)`:

```python
def _launch_gui() -> None:
    from lmu_ep_client.gui import launch_gui

    launch_gui()
```

At the start of `main()`, before `argparse.ArgumentParser(...)`, add:

```python
    if len(sys.argv) == 1:
        _launch_gui()
        return
```

- [ ] **Step 4: Create temporary GUI module stub**

Create `src/lmu_ep_client/gui.py` with:

```python
from __future__ import annotations


def launch_gui() -> None:
    raise RuntimeError("GUI launcher is not implemented yet")
```

This stub is only for importability; later tasks replace it with the real GUI.

- [ ] **Step 5: Run CLI tests**

Run:

```powershell
pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/lmu_ep_client/cli.py src/lmu_ep_client/gui.py tests/test_cli.py
git commit -m "feat: route no-arg launches to gui"
```

---

### Task 3: Add Testable GUI Helpers

**Files:**
- Modify: `src/lmu_ep_client/gui.py`
- Create: `tests/test_gui.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_gui.py`:

```python
from __future__ import annotations

from pathlib import Path

from lmu_ep_client import gui
from lmu_ep_client.api_client import DEFAULT_API_URL


def test_save_api_key_writes_tracking_config(tmp_path):
    config_path = tmp_path / "config.toml"

    gui.save_api_key("  lmu_secret  ", config_path=config_path)

    assert config_path.read_text(encoding="utf-8") == '[tracking]\napi_key = "lmu_secret"\n'


def test_save_api_key_rejects_empty(tmp_path):
    config_path = tmp_path / "config.toml"

    try:
        gui.save_api_key("   ", config_path=config_path)
    except ValueError as e:
        assert "API key cannot be empty" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_load_initial_api_key_prefers_env(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[tracking]\napi_key = "config-key"\n', encoding="utf-8")
    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")

    assert gui.load_initial_api_key(config_path=config_path) == "env-key"


def test_load_initial_api_key_uses_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[tracking]\napi_key = "config-key"\n', encoding="utf-8")
    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)

    assert gui.load_initial_api_key(config_path=config_path) == "config-key"


def test_format_registration_label():
    reg = {
        "id": "reg-1",
        "startsAt": "2026-06-14T18:00:00Z",
        "trackKey": "lemans",
        "trackLayoutKey": "24h",
        "carKey": "porsche-963",
        "eventTitle": "Summer Endurance",
        "hasTrackingSession": True,
    }

    label = gui.format_registration_label(reg)

    assert "2026-06-14T18:00:00Z" in label
    assert "lemans/24h" in label
    assert "porsche-963" in label
    assert "Summer Endurance" in label
    assert "[tracking]" in label


def test_format_team_member_label():
    member = {"id": "m1", "userName": "Alice", "role": "driver", "lmuDriverName": "A. Racer"}

    assert gui.format_team_member_label(member) == "Alice  driver  LMU: A. Racer"


def test_validate_start_blocks_missing_registration():
    state = gui.LaunchConfig(api_key="key")

    assert gui.validate_start(state) == "Select a registration before starting."


def test_validate_start_blocks_practice_without_member():
    state = gui.LaunchConfig(api_key="key", registration_id="reg-1", mode="practice")

    assert gui.validate_start(state) == "Select a practice driver before starting."


def test_validate_start_blocks_invalid_slot():
    state = gui.LaunchConfig(api_key="key", registration_id="reg-1", slot_id_text="abc")

    assert gui.validate_start(state) == "Slot ID must be a number."


def test_validate_start_accepts_race_config():
    state = gui.LaunchConfig(api_key="key", registration_id="reg-1", mode="race")

    assert gui.validate_start(state) is None


def test_launch_config_to_run_kwargs_race(tmp_path):
    state = gui.LaunchConfig(
        api_key="key",
        registration_id="reg-1",
        mode="race",
        output_dir_text=str(tmp_path),
        team_name="Team",
        driver_name="Driver",
        slot_id_text="42",
        debug=True,
    )

    kwargs = gui.launch_config_to_run_kwargs(state)

    assert kwargs == {
        "output_dir": tmp_path,
        "team_name": "Team",
        "driver_name": "Driver",
        "slot_id": 42,
        "api_url": DEFAULT_API_URL,
        "api_key": "key",
        "registration_id": "reg-1",
        "practice_team_member_id": None,
    }


def test_launch_config_to_run_kwargs_practice():
    state = gui.LaunchConfig(
        api_key="key",
        registration_id="reg-1",
        mode="practice",
        practice_team_member_id="member-1",
    )

    kwargs = gui.launch_config_to_run_kwargs(state)

    assert kwargs["practice_team_member_id"] == "member-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_gui.py -v
```

Expected: fails because the helper functions and `LaunchConfig` are not implemented.

- [ ] **Step 3: Implement helper code**

Replace `src/lmu_ep_client/gui.py` with:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from lmu_ep_client.api_client import DEFAULT_API_URL
from lmu_ep_client.cli import ENV_API_KEY, _config_api_key, _default_config_path


@dataclass
class LaunchConfig:
    api_key: str = ""
    registration_id: str | None = None
    mode: str = "race"
    practice_team_member_id: str | None = None
    output_dir_text: str = ""
    team_name: str = ""
    driver_name: str = ""
    slot_id_text: str = ""
    api_url: str = DEFAULT_API_URL
    debug: bool = False


def save_api_key(api_key: str, config_path: Path | None = None) -> None:
    value = api_key.strip()
    if not value:
        raise ValueError("API key cannot be empty")

    path = config_path or _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(f'[tracking]\napi_key = "{escaped}"\n', encoding="utf-8")


def load_initial_api_key(config_path: Path | None = None) -> str:
    env_api_key = os.environ.get(ENV_API_KEY, "").strip()
    if env_api_key:
        return env_api_key
    return _config_api_key(config_path or _default_config_path()) or ""


def format_registration_label(reg: dict) -> str:
    starts = reg.get("startsAt") or "no start time"
    track = reg.get("trackKey") or "?"
    layout = reg.get("trackLayoutKey")
    track_str = f"{track}/{layout}" if layout else track
    car = reg.get("carKey") or "?"
    title = reg.get("eventTitle") or ""
    tracking = " [tracking]" if reg.get("hasTrackingSession") else ""
    suffix = f" - {title}" if title else ""
    return f"{starts}  {track_str}  {car}{tracking}{suffix}"


def format_team_member_label(member: dict) -> str:
    name = member.get("userName") or "?"
    role = member.get("role") or ""
    lmu = member.get("lmuDriverName")
    lmu_str = f"LMU: {lmu}" if lmu else "LMU name not set"
    return f"{name}  {role}  {lmu_str}".strip()


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def validate_start(config: LaunchConfig) -> str | None:
    if not config.api_key.strip():
        return "Enter and save an API key before starting."
    if not config.registration_id:
        return "Select a registration before starting."
    if config.mode == "practice" and not config.practice_team_member_id:
        return "Select a practice driver before starting."
    if config.slot_id_text.strip():
        try:
            int(config.slot_id_text.strip())
        except ValueError:
            return "Slot ID must be a number."
    return None


def launch_config_to_run_kwargs(config: LaunchConfig) -> dict:
    output_dir = Path(config.output_dir_text.strip()) if config.output_dir_text.strip() else None
    slot_id = int(config.slot_id_text.strip()) if config.slot_id_text.strip() else None
    return {
        "output_dir": output_dir,
        "team_name": _optional_text(config.team_name),
        "driver_name": _optional_text(config.driver_name),
        "slot_id": slot_id,
        "api_url": config.api_url.strip() or DEFAULT_API_URL,
        "api_key": config.api_key.strip(),
        "registration_id": config.registration_id,
        "practice_team_member_id": (
            config.practice_team_member_id if config.mode == "practice" else None
        ),
    }


def launch_gui() -> None:
    raise RuntimeError("GUI launcher is not implemented yet")
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
pytest tests/test_gui.py -v
```

Expected: all helper tests pass.

- [ ] **Step 5: Run CLI and packaging tests**

Run:

```powershell
pytest tests/test_gui.py tests/test_cli.py tests/test_packaging.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/lmu_ep_client/gui.py tests/test_gui.py
git commit -m "feat: add gui launcher helpers"
```

---

### Task 4: Add Worker Thread For Poller Execution

**Files:**
- Modify: `src/lmu_ep_client/gui.py`
- Modify: `tests/test_gui.py`

- [ ] **Step 1: Write failing worker tests**

Add these tests to `tests/test_gui.py`:

```python
class _FakeStopEvent:
    def __init__(self):
        self.set_called = False

    def set(self):
        self.set_called = True


def test_run_worker_calls_poller_with_stop_event(monkeypatch):
    calls = {}
    fake_stop = _FakeStopEvent()

    def fake_run(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(gui, "run", fake_run)
    worker = gui.RunWorker({"api_key": "key", "registration_id": "reg-1"}, stop_event=fake_stop)

    worker.run()

    assert calls["api_key"] == "key"
    assert calls["registration_id"] == "reg-1"
    assert calls["stop_event"] is fake_stop


def test_run_worker_stop_sets_event():
    fake_stop = _FakeStopEvent()
    worker = gui.RunWorker({}, stop_event=fake_stop)

    worker.stop()

    assert fake_stop.set_called is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/test_gui.py::test_run_worker_calls_poller_with_stop_event tests/test_gui.py::test_run_worker_stop_sets_event -v
```

Expected: fails because `RunWorker` is not implemented.

- [ ] **Step 3: Implement `RunWorker`**

In `src/lmu_ep_client/gui.py`, add these imports:

```python
import threading
from collections.abc import Callable
```

Add this import near the other project imports:

```python
from lmu_ep_client.poller import run
```

Add this class before `launch_gui()`:

```python
class RunWorker:
    def __init__(
        self,
        kwargs: dict,
        stop_event: threading.Event | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.kwargs = dict(kwargs)
        self.stop_event = stop_event or threading.Event()
        self.log = log or (lambda message: None)

    def run(self) -> None:
        run(**self.kwargs, stop_event=self.stop_event, log=self.log)

    def stop(self) -> None:
        self.stop_event.set()
```

- [ ] **Step 4: Run worker tests**

Run:

```powershell
pytest tests/test_gui.py -v
```

Expected: all GUI tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/lmu_ep_client/gui.py tests/test_gui.py
git commit -m "feat: add gui poller worker"
```

---

### Task 5: Build The PySide6 Launcher Window

**Files:**
- Modify: `src/lmu_ep_client/gui.py`

- [ ] **Step 1: Add Qt imports and model item classes**

In `src/lmu_ep_client/gui.py`, add these imports:

```python
import logging

from lmu_ep_client.api_client import ApiError, TrackingClient
```

Add lazy Qt imports inside a function to keep non-GUI helper tests importable even in constrained environments:

```python
def _qt():
    from PySide6.QtCore import QObject, QThread, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QRadioButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    return {
        "QObject": QObject,
        "QThread": QThread,
        "Signal": Signal,
        "QApplication": QApplication,
        "QCheckBox": QCheckBox,
        "QComboBox": QComboBox,
        "QFileDialog": QFileDialog,
        "QFormLayout": QFormLayout,
        "QGridLayout": QGridLayout,
        "QGroupBox": QGroupBox,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMainWindow": QMainWindow,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "QRadioButton": QRadioButton,
        "QTextEdit": QTextEdit,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }
```

- [ ] **Step 2: Add background runnable factory**

Add this function after `RunWorker`:

```python
def _make_qt_worker(qt: dict, worker: RunWorker):
    class QtRunWorker(qt["QObject"]):
        finished = qt["Signal"]()
        failed = qt["Signal"](str)
        message = qt["Signal"](str)

        def run(self) -> None:
            worker.log = self.message.emit
            try:
                worker.run()
            except Exception as e:
                logging.getLogger(__name__).exception("GUI worker failed")
                self.failed.emit(str(e))
            finally:
                self.finished.emit()

        def stop(self) -> None:
            worker.stop()

    return QtRunWorker()
```

- [ ] **Step 3: Implement `LauncherWindow`**

Add this function after `_make_qt_worker(...)`. It returns a class so Qt symbols stay lazy:

```python
def _launcher_window_class(qt: dict):
    class LauncherWindow(qt["QMainWindow"]):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("LMU EP Client")
            self.resize(760, 560)
            self.registrations: list[dict] = []
            self.team_members: list[dict] = []
            self.thread = None
            self.worker = None
            self.qt_worker = None

            root = qt["QWidget"]()
            layout = qt["QVBoxLayout"](root)
            grid = qt["QGridLayout"]()
            layout.addLayout(grid)

            api_group = qt["QGroupBox"]("API")
            api_layout = qt["QVBoxLayout"](api_group)
            self.api_key_edit = qt["QLineEdit"]()
            self.api_key_edit.setEchoMode(qt["QLineEdit"].Password)
            self.api_key_edit.setText(load_initial_api_key())
            self.save_key_button = qt["QPushButton"]("Save key")
            self.refresh_button = qt["QPushButton"]("Refresh registrations")
            api_buttons = qt["QHBoxLayout"]()
            api_buttons.addWidget(self.save_key_button)
            api_buttons.addWidget(self.refresh_button)
            api_layout.addWidget(self.api_key_edit)
            api_layout.addLayout(api_buttons)
            grid.addWidget(api_group, 0, 0)

            event_group = qt["QGroupBox"]("Event")
            event_layout = qt["QVBoxLayout"](event_group)
            self.registration_combo = qt["QComboBox"]()
            self.registration_combo.addItem("Refresh registrations to choose an event", None)
            event_layout.addWidget(self.registration_combo)
            grid.addWidget(event_group, 1, 0)

            mode_group = qt["QGroupBox"]("Mode")
            mode_layout = qt["QHBoxLayout"](mode_group)
            self.race_radio = qt["QRadioButton"]("Race")
            self.practice_radio = qt["QRadioButton"]("Practice")
            self.race_radio.setChecked(True)
            mode_layout.addWidget(self.race_radio)
            mode_layout.addWidget(self.practice_radio)
            grid.addWidget(mode_group, 2, 0)

            member_group = qt["QGroupBox"]("Practice driver")
            member_layout = qt["QVBoxLayout"](member_group)
            self.member_combo = qt["QComboBox"]()
            self.member_combo.addItem("Select Practice mode to load drivers", None)
            member_layout.addWidget(self.member_combo)
            grid.addWidget(member_group, 3, 0)

            advanced_group = qt["QGroupBox"]("Advanced")
            advanced_layout = qt["QFormLayout"](advanced_group)
            self.output_dir_edit = qt["QLineEdit"]()
            self.output_dir_button = qt["QPushButton"]("Browse")
            output_row = qt["QHBoxLayout"]()
            output_row.addWidget(self.output_dir_edit)
            output_row.addWidget(self.output_dir_button)
            self.team_edit = qt["QLineEdit"]()
            self.driver_edit = qt["QLineEdit"]()
            self.slot_edit = qt["QLineEdit"]()
            self.debug_check = qt["QCheckBox"]("Enable debug logging")
            advanced_layout.addRow("Output directory", output_row)
            advanced_layout.addRow("Team", self.team_edit)
            advanced_layout.addRow("Driver", self.driver_edit)
            advanced_layout.addRow("Slot ID", self.slot_edit)
            advanced_layout.addRow("", self.debug_check)
            grid.addWidget(advanced_group, 0, 1, 3, 1)

            status_group = qt["QGroupBox"]("Status")
            status_layout = qt["QVBoxLayout"](status_group)
            self.status_label = qt["QLabel"]("Ready.")
            self.log_edit = qt["QTextEdit"]()
            self.log_edit.setReadOnly(True)
            self.start_button = qt["QPushButton"]("Start client")
            self.stop_button = qt["QPushButton"]("Stop")
            self.stop_button.setEnabled(False)
            action_row = qt["QHBoxLayout"]()
            action_row.addWidget(self.start_button)
            action_row.addWidget(self.stop_button)
            status_layout.addWidget(self.status_label)
            status_layout.addWidget(self.log_edit)
            status_layout.addLayout(action_row)
            grid.addWidget(status_group, 3, 1)

            self.setCentralWidget(root)

            self.save_key_button.clicked.connect(self.save_key)
            self.refresh_button.clicked.connect(self.refresh_registrations)
            self.registration_combo.currentIndexChanged.connect(self.registration_changed)
            self.practice_radio.toggled.connect(self.mode_changed)
            self.output_dir_button.clicked.connect(self.pick_output_dir)
            self.start_button.clicked.connect(self.start_client)
            self.stop_button.clicked.connect(self.stop_client)
            self.update_status()

        def append_log(self, message: str) -> None:
            self.log_edit.append(message)

        def selected_registration(self) -> dict | None:
            return self.registration_combo.currentData()

        def selected_member(self) -> dict | None:
            return self.member_combo.currentData()

        def current_config(self) -> LaunchConfig:
            reg = self.selected_registration()
            member = self.selected_member()
            return LaunchConfig(
                api_key=self.api_key_edit.text(),
                registration_id=reg.get("id") if reg else None,
                mode="practice" if self.practice_radio.isChecked() else "race",
                practice_team_member_id=member.get("id") if member else None,
                output_dir_text=self.output_dir_edit.text(),
                team_name=self.team_edit.text(),
                driver_name=self.driver_edit.text(),
                slot_id_text=self.slot_edit.text(),
                debug=self.debug_check.isChecked(),
            )

        def save_key(self) -> None:
            try:
                save_api_key(self.api_key_edit.text())
            except ValueError as e:
                self.status_label.setText(str(e))
                return
            except OSError as e:
                self.status_label.setText(f"Could not save API key: {e}")
                return
            self.status_label.setText("API key saved.")

        def refresh_registrations(self) -> None:
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                self.status_label.setText("Enter an API key before refreshing registrations.")
                return
            try:
                regs = TrackingClient(DEFAULT_API_URL, api_key).list_registrations()
            except (ApiError, ValueError) as e:
                self.status_label.setText(f"Failed to load registrations: {e}")
                return
            self.registrations = regs
            self.registration_combo.clear()
            if not regs:
                self.registration_combo.addItem("No registrations found", None)
                self.status_label.setText("No registrations found.")
                return
            for reg in regs:
                self.registration_combo.addItem(format_registration_label(reg), reg)
            self.status_label.setText(f"{len(regs)} registration(s) loaded.")
            self.mode_changed()

        def registration_changed(self) -> None:
            self.mode_changed()

        def mode_changed(self) -> None:
            if self.practice_radio.isChecked():
                self.load_team_members()
            else:
                self.member_combo.clear()
                self.member_combo.addItem("Race mode does not need a practice driver", None)
            self.update_status()

        def load_team_members(self) -> None:
            reg = self.selected_registration()
            self.member_combo.clear()
            if not reg:
                self.member_combo.addItem("Select a registration first", None)
                return
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                self.member_combo.addItem("Enter an API key first", None)
                return
            try:
                members = TrackingClient(DEFAULT_API_URL, api_key).list_team_members(reg["id"])
            except (ApiError, ValueError) as e:
                self.member_combo.addItem("Could not load team members", None)
                self.status_label.setText(f"Failed to load team members: {e}")
                return
            if not members:
                self.member_combo.addItem("No team members found", None)
                self.status_label.setText("No team members found for this registration.")
                return
            for member in members:
                self.member_combo.addItem(format_team_member_label(member), member)
            self.status_label.setText(f"{len(members)} team member(s) loaded.")

        def pick_output_dir(self) -> None:
            directory = qt["QFileDialog"].getExistingDirectory(self, "Choose output directory")
            if directory:
                self.output_dir_edit.setText(directory)
                self.update_status()

        def update_status(self) -> None:
            reg = self.selected_registration()
            member = self.selected_member()
            parts = [
                "API key saved or entered." if self.api_key_edit.text().strip() else "API key missing.",
                f"Registrations loaded: {len(self.registrations)}.",
                f"Selected registration: {reg.get('id') if reg else 'none'}.",
                f"Practice driver: {member.get('id') if member else 'none'}.",
                f"Output: {self.output_dir_edit.text().strip() or './sessions'}.",
                "Running." if self.thread else "Stopped.",
            ]
            self.append_log(" ".join(parts))

        def start_client(self) -> None:
            config = self.current_config()
            error = validate_start(config)
            if error:
                self.status_label.setText(error)
                return
            if config.debug:
                logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")
            kwargs = launch_config_to_run_kwargs(config)
            self.worker = RunWorker(kwargs)
            self.qt_worker = _make_qt_worker(qt, self.worker)
            self.thread = qt["QThread"]()
            self.qt_worker.moveToThread(self.thread)
            self.thread.started.connect(self.qt_worker.run)
            self.qt_worker.message.connect(self.append_log)
            self.qt_worker.failed.connect(self.status_label.setText)
            self.qt_worker.finished.connect(self.thread.quit)
            self.qt_worker.finished.connect(self.client_finished)
            self.thread.start()
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.status_label.setText("Client running.")

        def stop_client(self) -> None:
            if self.qt_worker:
                self.qt_worker.stop()
                self.status_label.setText("Stopping client...")

        def client_finished(self) -> None:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.thread = None
            self.worker = None
            self.qt_worker = None
            self.status_label.setText("Client stopped.")

        def closeEvent(self, event) -> None:
            if self.worker:
                self.worker.stop()
            super().closeEvent(event)

    return LauncherWindow
```

- [ ] **Step 4: Implement `launch_gui()`**

Replace the stub `launch_gui()` with:

```python
def launch_gui() -> None:
    qt = _qt()
    app = qt["QApplication"].instance() or qt["QApplication"]([])
    window_class = _launcher_window_class(qt)
    window = window_class()
    window.show()
    app.exec()
```

- [ ] **Step 5: Run non-GUI tests**

Run:

```powershell
pytest tests/test_gui.py tests/test_cli.py -v
```

Expected: tests pass. They should not open a window because `launch_gui()` is monkeypatched in CLI tests and helper tests do not call it.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/lmu_ep_client/gui.py
git commit -m "feat: build pyside gui launcher"
```

---

### Task 6: Polish GUI Behavior And Documentation

**Files:**
- Modify: `src/lmu_ep_client/gui.py`
- Modify: `README.md`

- [ ] **Step 1: Write documentation update**

In `README.md`, replace the first executable usage block:

```markdown
Download or build `lmu-ep-client.exe` (see below). Start it before or during a session:

```
lmu-ep-client.exe
lmu-ep-client.exe --output-dir C:\path\to\sessions
lmu-ep-client.exe --registration-id <uuid>
lmu-ep-client.exe --registration-id <uuid> --practice --practice-team-member-id <uuid>
lmu-ep-client.exe --api-key lmu_... --registration-id <uuid>
lmu-ep-client.exe --debug
```
```

with:

```markdown
Download or build `lmu-ep-client.exe` (see below). Double-click it or run it with no arguments to open the GUI launcher. The GUI lets you save your API key, select a registration, select Race or Practice mode, and start the client.

Command-line usage is still available whenever you pass arguments:

```
lmu-ep-client.exe --output-dir C:\path\to\sessions
lmu-ep-client.exe --registration-id <uuid>
lmu-ep-client.exe --registration-id <uuid> --practice --practice-team-member-id <uuid>
lmu-ep-client.exe --api-key lmu_... --registration-id <uuid>
lmu-ep-client.exe --debug
```
```

- [ ] **Step 2: Add status text refinement**

In `LauncherWindow.update_status`, replace:

```python
self.append_log(" ".join(parts))
```

with:

```python
self.status_label.setText(" ".join(parts))
```

This prevents every status refresh from adding noisy duplicate lines to the log.

- [ ] **Step 3: Add startup status**

At the end of `LauncherWindow.__init__`, after `self.update_status()`, add:

```python
self.append_log("Ready. Save an API key, refresh registrations, choose a mode, then start.")
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_gui.py tests/test_cli.py tests/test_packaging.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/lmu_ep_client/gui.py README.md
git commit -m "docs: describe gui launcher"
```

---

### Task 7: Full Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run source CLI smoke test**

Run:

```powershell
python -m lmu_ep_client --config .pytest-tmp\missing-gui-smoke.toml --list-teams
```

Expected: command does not open the GUI. It prints either the active LMU car list or `LMU is not running or shared memory is not available.`

- [ ] **Step 3: Run source GUI import smoke test**

Run:

```powershell
python -c "from lmu_ep_client.gui import launch_gui, LaunchConfig; print(LaunchConfig(mode='race').mode)"
```

Expected: prints `race`.

- [ ] **Step 4: Build executable**

Run:

```powershell
.\.venv\Scripts\pyinstaller.exe lmu-ep-client.spec --noconfirm
```

Expected: build completes and creates `dist\lmu-ep-client.exe`.

- [ ] **Step 5: Run packaged CLI smoke test**

Run:

```powershell
.\dist\lmu-ep-client.exe --config .pytest-tmp\missing-gui-smoke.toml --list-teams
```

Expected: executable does not open the GUI. It prints either the active LMU car list or `LMU is not running or shared memory is not available.`

- [ ] **Step 6: Manually verify no-args GUI**

Run:

```powershell
.\dist\lmu-ep-client.exe
```

Expected: the PySide6 launcher window opens. Confirm these manual checks:

- API key field is visible and password-masked.
- Save key writes `%APPDATA%\lmu-ep-client\config.toml`.
- Refresh registrations reports a clear error for a bad key.
- Race mode does not require a practice driver.
- Practice mode requires a practice driver before Start enables a valid run.
- Stop button requests shutdown and the window remains responsive.

- [ ] **Step 7: Commit verification-only fixes if needed**

If any verification step requires a code or documentation fix, make the smallest fix, rerun the failing verification command, then commit:

```powershell
git add <changed-files>
git commit -m "fix: complete gui launcher verification"
```

If no files change, do not create a commit.

---

## Self-Review

Spec coverage:

- No-argument GUI and argument-based CLI preservation are covered by Task 2.
- PySide6/Qt and PyInstaller runtime packaging are covered by Task 1.
- Saved API key via the existing config file is covered by Task 3 and Task 5.
- Registration and practice driver pickers are covered by Task 3 and Task 5.
- Existing `TrackingClient` and `poller.run(...)` reuse are covered by Task 3, Task 4, and Task 5.
- Background worker and graceful stop are covered by Task 4 and Task 5.
- Status and actionable errors are covered by Task 5 and Task 6.
- README/user-facing usage update is covered by Task 6.
- Manual Windows/package verification is covered by Task 7.

Placeholder scan:

- No `TBD`, `TODO`, or incomplete task placeholders are present.
- Each implementation step includes exact files, code, commands, and expected results.

Type consistency:

- `LaunchConfig`, `RunWorker`, `save_api_key`, `load_initial_api_key`, `format_registration_label`, `format_team_member_label`, `validate_start`, and `launch_config_to_run_kwargs` are introduced before later tasks use them.
- `RunWorker.run()` accepts poller kwargs and injects `stop_event` and `log`, matching the existing `poller.run(...)` signature.
