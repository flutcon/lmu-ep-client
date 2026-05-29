import json
from pathlib import Path

import pytest

from lmu_ep_client.writer import session_filename, flush_session
from lmu_ep_client.models import LapData, SessionData, Stint, FuelData, EnergyData, PitStop, TireInfo, TyreWearData


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


def test_session_filename_slugifies_windows_invalid_chars():
    result = session_filename(
        start_time="2026-04-02T09:05:00",
        track='Spa/Francorchamps:24*? "<>|',
        session_type=r"Practice\Qualifying",
    )

    assert result == "2026-04-02_09-05-00_Spa_Francorchamps_24_Practice_Qualifying.json"
    assert not set('<>:"/\\|?*').intersection(result)


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
            tyre_wear=TyreWearData(
                start={"FL": 1.0, "FR": 1.0, "RL": 1.0, "RR": 1.0},
                end={"FL": 0.9, "FR": 0.9, "RL": 0.88, "RR": 0.88},
            ),
        ),
    ]
    path = flush_session(session, stints, output_dir=tmp_path)

    assert path.exists()
    assert path.name == "2026-04-02_18-30-00_Monza_Race.json"

    data = json.loads(path.read_text())
    assert data["session"]["track"] == "Monza"
    assert len(data["stints"]) == 1
    assert data["stints"][0]["total_laps"] == 10


def test_flush_session_writes_lap_temperature_snapshots(tmp_path):
    session = SessionData(
        track="Monza",
        session_type="Practice 1",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    laps = [
        LapData(
            lap_number=1,
            driver="Player",
            end_time_elapsed=124.318,
            lap_time_seconds=124.318,
            fuel_litres=48.46,
            energy_percent=73.23,
            tyre_wear={"FL": 0.9244, "FR": 0.9171, "RL": 0.8704, "RR": 0.8655},
            tyre_temps_c={
                "FL": {
                    "surface": {"left": 80.0, "center": 81.0, "right": 82.0},
                    "carcass": 78.5,
                    "inner_layer": {"left": 79.0, "center": 79.5, "right": 80.0},
                }
            },
        )
    ]

    path = flush_session(session, [], output_dir=tmp_path, laps=laps)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["laps"] == [
        {
            "lap_number": 1,
            "driver": "Player",
            "end_time_elapsed": 124.318,
            "lap_time_seconds": 124.318,
            "fuel_litres": 48.46,
            "energy_percent": 73.23,
            "tyre_wear": {"FL": 0.9244, "FR": 0.9171, "RL": 0.8704, "RR": 0.8655},
            "tyre_temps_c": {
                "FL": {
                    "surface": {"left": 80.0, "center": 81.0, "right": 82.0},
                    "carcass": 78.5,
                    "inner_layer": {"left": 79.0, "center": 79.5, "right": 80.0},
                }
            },
        }
    ]


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


def test_flush_session_keeps_existing_file_when_write_is_interrupted(tmp_path, monkeypatch):
    session = SessionData(
        track="Monza",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    path = flush_session(session, [], output_dir=tmp_path)
    original_json = path.read_text(encoding="utf-8")

    def interrupted_write_text(self, *args, **kwargs):
        self.write_bytes(b'{"partial":')
        raise RuntimeError("interrupted")

    monkeypatch.setattr(Path, "write_text", interrupted_write_text)

    with pytest.raises(RuntimeError, match="interrupted"):
        flush_session(session, [], output_dir=tmp_path)

    assert path.read_text(encoding="utf-8") == original_json


def test_full_session_json_structure(tmp_path):
    """Smoke test: verify the complete JSON output matches expected schema."""
    from lmu_ep_client.models import PitStop, TireInfo

    session = SessionData(
        track="Le Mans 24h",
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
            start_lap=0,
            end_lap=28,
            start_time_elapsed=0.0,
            end_time_elapsed=3360.5,
            fuel=FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=5.2),
            tyre_wear=TyreWearData(
                start={"FL": 1.0, "FR": 1.0, "RL": 1.0, "RR": 1.0},
                end={"FL": 0.28, "FR": 0.32, "RL": 0.45, "RR": 0.42},
            ),
            pit_stop=PitStop(
                pit_enter_elapsed=3360.5,
                pit_stand_elapsed=3372.0,
                pit_depart_elapsed=3385.0,
                pit_exit_elapsed=3395.2,
                fuel_added_litres=97.7,
                energy_added_percent=94.8,
                repair_flag=False,
                driver_change=True,
                new_driver="Teammate",
                tyres={
                    "FL": TireInfo(changed=True, old_wear=0.28, old_compound="Hard", new_compound="Hard"),
                    "FR": TireInfo(changed=True, old_wear=0.32, old_compound="Hard", new_compound="Hard"),
                    "RL": TireInfo(changed=False, old_wear=0.55, old_compound="Hard"),
                    "RR": TireInfo(changed=False, old_wear=0.58, old_compound="Hard"),
                },
            ),
        ),
        Stint(
            stint_number=2,
            driver="Teammate",
            start_lap=28,
            end_lap=55,
            start_time_elapsed=3395.2,
            end_time_elapsed=6600.0,
            fuel=FuelData(start_litres=110.0, end_litres=15.0, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=8.0),
            tyre_wear=TyreWearData(
                start={"FL": 1.0, "FR": 1.0, "RL": 1.0, "RR": 1.0},
                end={"FL": 0.5, "FR": 0.52, "RL": 0.48, "RR": 0.46},
            ),
        ),
    ]

    path = flush_session(session, stints, output_dir=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    # Verify top-level structure
    assert "session" in data
    assert "stints" in data
    assert len(data["stints"]) == 2

    # Verify first stint has pit_stop with all fields
    s1 = data["stints"][0]
    assert s1["pit_stop"]["driver_change"] is True
    assert s1["pit_stop"]["new_driver"] == "Teammate"
    assert s1["pit_stop"]["tyres"]["FL"]["changed"] is True
    assert s1["pit_stop"]["tyres"]["RL"]["changed"] is False
    assert "new_compound" not in s1["pit_stop"]["tyres"]["RL"]

    # Verify second stint has no pit_stop
    assert data["stints"][1]["pit_stop"] is None

    # Verify computed fields
    assert s1["total_laps"] == 28
    assert s1["fuel"]["litres_per_lap"] == round(97.7 / 28, 2)
