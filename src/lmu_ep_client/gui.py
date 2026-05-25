from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lmu_ep_client.api_client import DEFAULT_API_URL, TrackingClient
from lmu_ep_client.cli import ENV_API_KEY, _config_api_key, _default_config_path
from lmu_ep_client.poller import run


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
        "QPushButton": QPushButton,
        "QRadioButton": QRadioButton,
        "QTextEdit": QTextEdit,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }


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
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("API key cannot contain control characters")

    path = config_path or _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    assignment = f'api_key = "{escaped}"\n'
    if not path.exists():
        path.write_text(f"[tracking]\n{assignment}", encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if _is_section_header(line):
            break
        if _is_api_key_assignment(line):
            lines[index] = assignment
            path.write_text("".join(lines), encoding="utf-8")
            return

    tracking_index = next(
        (index for index, line in enumerate(lines) if _is_tracking_section_header(line)),
        None,
    )
    if tracking_index is None:
        path.write_text(_append_tracking_section(text, assignment), encoding="utf-8")
        return

    insert_index = len(lines)
    for index in range(tracking_index + 1, len(lines)):
        if _is_section_header(lines[index]):
            insert_index = index
            break
        if _is_api_key_assignment(lines[index]):
            lines[index] = assignment
            path.write_text("".join(lines), encoding="utf-8")
            return

    lines.insert(insert_index, assignment)
    path.write_text("".join(lines), encoding="utf-8")


def _is_section_header(line: str) -> bool:
    stripped = _strip_toml_line_comment(line).strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _is_tracking_section_header(line: str) -> bool:
    return _strip_toml_line_comment(line).strip() == "[tracking]"


def _strip_toml_line_comment(line: str) -> str:
    return line.split("#", 1)[0]


def _is_api_key_assignment(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("api_key"):
        return False
    remainder = stripped[len("api_key") :].lstrip()
    return remainder.startswith("=")


def _append_tracking_section(text: str, assignment: str) -> str:
    if not text:
        separator = ""
    elif text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    return f"{text}{separator}[tracking]\n{assignment}"


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


class RunWorker:
    def __init__(
        self,
        kwargs: dict,
        stop_event: threading.Event | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.kwargs = dict(kwargs)
        self.stop_event = threading.Event() if stop_event is None else stop_event
        self.log = (lambda message: None) if log is None else log

    def run(self) -> None:
        run(**self.kwargs, stop_event=self.stop_event, log=self.log)

    def stop(self) -> None:
        self.stop_event.set()


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


def _make_api_worker(qt: dict, request: Callable[[], object]):
    class QtApiWorker(qt["QObject"]):
        loaded = qt["Signal"](object)
        failed = qt["Signal"](str)
        finished = qt["Signal"]()

        def run(self) -> None:
            try:
                self.loaded.emit(request())
            except Exception as e:
                logging.getLogger(__name__).exception("GUI API request failed")
                self.failed.emit(str(e))
            finally:
                self.finished.emit()

    return QtApiWorker()


def _api_error_status(kind: str | None, message: str) -> str:
    prefix = (
        "Failed to load team members"
        if kind == "team_members"
        else "Failed to load registrations"
    )
    return message if message.startswith(f"{prefix}:") else f"{prefix}: {message}"


def _launcher_window_class(qt: dict):
    class LauncherWindow(qt["QMainWindow"]):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("LMU EP Client")
            self.resize(760, 560)
            self.registrations: list[dict] = []
            self.thread = None
            self.worker = None
            self.qt_worker = None
            self.api_thread = None
            self.api_qt_worker = None
            self._api_request_kind: str | None = None
            self._refresh_mode_after_api = False
            self._close_after_stop = False
            self._last_worker_error: str | None = None

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
            if self.api_thread:
                self.status_label.setText("API request already running.")
                return
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                self.status_label.setText("Enter an API key before refreshing registrations.")
                return
            self.status_label.setText("Loading registrations...")
            self.start_api_request(
                "registrations",
                lambda: TrackingClient(DEFAULT_API_URL, api_key).list_registrations(),
                self.handle_registrations_loaded,
            )

        def handle_registrations_loaded(self, regs: object) -> None:
            if not isinstance(regs, list):
                self.handle_api_failed("Failed to load registrations: unexpected response")
                return
            self.registrations = regs
            self.registration_combo.blockSignals(True)
            self.registration_combo.clear()
            if not regs:
                self.registration_combo.addItem("No registrations found", None)
                self.registration_combo.blockSignals(False)
                self.status_label.setText("No registrations found.")
                return
            for reg in regs:
                self.registration_combo.addItem(format_registration_label(reg), reg)
            self.registration_combo.blockSignals(False)
            self.status_label.setText(f"{len(regs)} registration(s) loaded.")
            self._refresh_mode_after_api = True

        def registration_changed(self, *args) -> None:
            self.mode_changed()

        def mode_changed(self, *args) -> None:
            if self.practice_radio.isChecked():
                self.load_team_members()
            else:
                self.member_combo.clear()
                self.member_combo.addItem("Race mode does not need a practice driver", None)
            self.update_status()

        def load_team_members(self) -> None:
            if self.api_thread:
                self.status_label.setText("API request already running.")
                return
            reg = self.selected_registration()
            self.member_combo.clear()
            if not reg:
                self.member_combo.addItem("Select a registration first", None)
                return
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                self.member_combo.addItem("Enter an API key first", None)
                return
            registration_id = reg["id"]
            self.member_combo.addItem("Loading team members...", None)
            self.status_label.setText("Loading team members...")
            self.start_api_request(
                "team_members",
                lambda: TrackingClient(DEFAULT_API_URL, api_key).list_team_members(registration_id),
                self.handle_team_members_loaded,
            )

        def handle_team_members_loaded(self, members: object) -> None:
            self.member_combo.clear()
            if not isinstance(members, list):
                self.member_combo.addItem("Could not load team members", None)
                self.handle_api_failed("Failed to load team members: unexpected response")
                return
            if not members:
                self.member_combo.addItem("No team members found", None)
                self.status_label.setText("No team members found for this registration.")
                return
            for member in members:
                self.member_combo.addItem(format_team_member_label(member), member)
            self.status_label.setText(f"{len(members)} team member(s) loaded.")

        def start_api_request(
            self,
            kind: str,
            request: Callable[[], object],
            handle_loaded: Callable[[object], None],
        ) -> None:
            if self.api_thread:
                self.status_label.setText("API request already running.")
                return
            self._api_request_kind = kind
            self.api_qt_worker = _make_api_worker(qt, request)
            self.api_thread = qt["QThread"]()
            self.api_qt_worker.moveToThread(self.api_thread)
            self.api_thread.started.connect(self.api_qt_worker.run)
            self.api_qt_worker.loaded.connect(handle_loaded)
            self.api_qt_worker.failed.connect(self.handle_api_failed)
            self.api_qt_worker.finished.connect(self.api_thread.quit)
            self.api_thread.finished.connect(self.api_thread_finished)
            self.set_api_loading_enabled(False)
            self.api_thread.start()

        def set_api_loading_enabled(self, enabled: bool) -> None:
            kind = self._api_request_kind
            if kind == "registrations":
                self.refresh_button.setEnabled(enabled)
                self.registration_combo.setEnabled(enabled)
            elif kind == "team_members":
                self.registration_combo.setEnabled(enabled)
                self.member_combo.setEnabled(enabled)

        def handle_api_failed(self, message: str) -> None:
            if self._api_request_kind == "team_members":
                self.member_combo.clear()
                self.member_combo.addItem("Could not load team members", None)
            self.status_label.setText(_api_error_status(self._api_request_kind, message))

        def api_thread_finished(self) -> None:
            api_qt_worker = self.api_qt_worker
            api_thread = self.api_thread
            refresh_mode = self._refresh_mode_after_api
            close_after_stop = self._close_after_stop
            if not close_after_stop:
                self.set_api_loading_enabled(True)
            self.api_thread = None
            self.api_qt_worker = None
            self._api_request_kind = None
            self._refresh_mode_after_api = False
            if api_qt_worker:
                api_qt_worker.deleteLater()
            if api_thread:
                api_thread.deleteLater()
            if refresh_mode and not close_after_stop:
                self.mode_changed()
            if close_after_stop and not self.thread:
                self._close_after_stop = False
                self.close()

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
            self._last_worker_error = None
            self._close_after_stop = False
            self.worker = RunWorker(kwargs)
            self.qt_worker = _make_qt_worker(qt, self.worker)
            self.thread = qt["QThread"]()
            self.qt_worker.moveToThread(self.thread)
            self.thread.started.connect(self.qt_worker.run)
            self.qt_worker.message.connect(self.append_log)
            self.qt_worker.failed.connect(self.handle_client_failed)
            self.qt_worker.finished.connect(self.thread.quit)
            self.thread.finished.connect(self.client_thread_finished)
            self.thread.start()
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.status_label.setText("Client running.")

        def handle_client_failed(self, message: str) -> None:
            self._last_worker_error = message
            self.status_label.setText(message)

        def stop_client(self) -> None:
            if self.qt_worker:
                self.qt_worker.stop()
                self.status_label.setText("Stopping client...")

        def client_thread_finished(self) -> None:
            qt_worker = self.qt_worker
            thread = self.thread
            error = self._last_worker_error
            close_after_stop = self._close_after_stop
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.thread = None
            self.worker = None
            self.qt_worker = None
            if qt_worker:
                qt_worker.deleteLater()
            if thread:
                thread.deleteLater()
            if error:
                self.status_label.setText(error)
            else:
                self.status_label.setText("Client stopped.")
            if close_after_stop:
                self._close_after_stop = False
                self.close()

        def closeEvent(self, event) -> None:
            if self.api_thread or self.thread or self.worker:
                self._close_after_stop = True
                if self.qt_worker:
                    self.qt_worker.stop()
                elif self.worker:
                    self.worker.stop()
                self.refresh_button.setEnabled(False)
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(False)
                self.status_label.setText("Closing after background work finishes...")
                event.ignore()
                return
            super().closeEvent(event)

    return LauncherWindow


def launch_gui() -> None:
    qt = _qt()
    app = qt["QApplication"].instance() or qt["QApplication"]([])
    window_class = _launcher_window_class(qt)
    window = window_class()
    window.show()
    app.exec()
