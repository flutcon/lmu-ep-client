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
