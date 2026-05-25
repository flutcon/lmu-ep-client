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
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _is_tracking_section_header(line: str) -> bool:
    return line.strip() == "[tracking]"


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


def launch_gui() -> None:
    raise RuntimeError("GUI launcher is not implemented yet")
