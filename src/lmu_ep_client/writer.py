from __future__ import annotations

import json
from pathlib import Path

from lmu_ep_client.models import SessionData, Stint


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
        output_dir = Path("sessions")
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = session_filename(session.start_time, session.track, session.session_type)
    path = output_dir / filename

    data = session.to_dict(stints)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
