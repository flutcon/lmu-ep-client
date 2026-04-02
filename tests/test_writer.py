import json
from pathlib import Path

from lmu_ep_client.writer import session_filename, flush_session
from lmu_ep_client.models import SessionData, Stint, FuelData, EnergyData


def test_session_filename():
    result = session_filename(
        start_time="2026-04-02T18:30:00",
        track="Le Mans 24h",
        session_type="Race",
    )
    assert result == "2026-04-02_18-30-00_Le_Mans_24h_Race.json"


def test_session_filename_special_chars():
    result = session_filename(
        start_time="2026-04-02T09:05:00",
        track="Spa-Francorchamps",
        session_type="Practice 1",
    )
    assert result == "2026-04-02_09-05-00_Spa-Francorchamps_Practice_1.json"


def test_flush_session_creates_file(tmp_path):
    session = SessionData(
        track="Monza",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    stints = [
        Stint(
            stint_number=1,
            driver="Player",
            start_lap=1,
            end_lap=11,
            start_time_elapsed=0.0,
            end_time_elapsed=600.0,
            fuel=FuelData(start_litres=110.0, end_litres=70.0, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=60.0),
        ),
    ]
    path = flush_session(session, stints, output_dir=tmp_path)

    assert path.exists()
    assert path.name == "2026-04-02_18-30-00_Monza_Race.json"

    data = json.loads(path.read_text())
    assert data["session"]["track"] == "Monza"
    assert len(data["stints"]) == 1
    assert data["stints"][0]["total_laps"] == 10


def test_flush_session_overwrites(tmp_path):
    session = SessionData(
        track="Monza",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    flush_session(session, [], output_dir=tmp_path)
    path = flush_session(session, [], output_dir=tmp_path)
    assert path.exists()
    # Only one file, overwritten
    assert len(list(tmp_path.iterdir())) == 1
