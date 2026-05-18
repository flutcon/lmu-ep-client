from __future__ import annotations

import json
import sys
from pathlib import Path

from lmu_ep_client.models import SessionData, Stint


def _default_output_dir() -> Path:
    # When frozen by PyInstaller, anchor to the exe's folder so the user
    # always finds sessions/ next to the binary they launched, regardless
    # of the shell's current working directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "sessions"
    return Path("sessions")


def session_filename(start_time: str, track: str, session_type: str) -> str:
    time_part = start_time.replace("T", "_").replace(":", "-")
    track_part = track.replace(" ", "_")
    session_part = session_type.replace(" ", "_")
    return f"{time_part}_{track_part}_{session_part}.json"


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
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
