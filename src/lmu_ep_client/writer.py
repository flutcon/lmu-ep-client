from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from lmu_ep_client.models import SessionData, Stint


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_FILENAME_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]+')


def _default_output_dir() -> Path:
    # When frozen by PyInstaller, anchor to the exe's folder so the user
    # always finds sessions/ next to the binary they launched, regardless
    # of the shell's current working directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "sessions"
    return Path("sessions")


def session_filename(start_time: str, track: str, session_type: str) -> str:
    time_part = _slug_filename_component(start_time.replace("T", "_").replace(":", "-"))
    track_part = _slug_filename_component(track)
    session_part = _slug_filename_component(session_type)
    return f"{time_part}_{track_part}_{session_part}.json"


def _slug_filename_component(value: str) -> str:
    slug = _FILENAME_UNSAFE_CHARS.sub("_", value).strip("._ ")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        return "unknown"
    if slug.upper() in _WINDOWS_RESERVED_NAMES:
        return f"_{slug}"
    return slug


def _write_text_atomic(path: Path, text: str) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def flush_session(
    session: SessionData,
    stints: list[Stint],
    output_dir: Path | None = None,
) -> Path:
    if output_dir is None:
        output_dir = _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = session_filename(session.start_time, session.track, session.session_type)
    path = output_dir / filename

    data = session.to_dict(stints)
    _write_text_atomic(path, json.dumps(data, indent=2))
    return path
