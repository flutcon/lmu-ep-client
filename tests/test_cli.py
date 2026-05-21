from __future__ import annotations

import sys

from lmu_ep_client import cli


def _set_argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["lmu-ep-client", *args])


def test_list_registrations_uses_env_api_key(monkeypatch):
    seen = {}

    def fake_list_registrations(api):
        seen["api_key"] = api._api_key

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "_list_registrations", fake_list_registrations)
    _set_argv(monkeypatch, "--list-registrations")

    cli.main()

    assert seen["api_key"] == "env-key"


def test_tracking_uses_env_api_key(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--registration-id", "reg-1")

    cli.main()

    assert seen["api_key"] == "env-key"
    assert seen["registration_id"] == "reg-1"


def test_cli_api_key_overrides_env_api_key(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--api-key", "flag-key", "--registration-id", "reg-1")

    cli.main()

    assert seen["api_key"] == "flag-key"


def test_config_file_provides_api_key(monkeypatch, tmp_path):
    seen = {}
    config_path = tmp_path / "config.toml"
    config_path.write_text('[tracking]\napi_key = "config-key"\n', encoding="utf-8")

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--config", str(config_path), "--registration-id", "reg-1")

    cli.main()

    assert seen["api_key"] == "config-key"


def test_cli_practice_requires_team_member_id(monkeypatch):
    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    _set_argv(monkeypatch, "--registration-id", "reg-1", "--practice")

    try:
        cli.main()
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected parser error")


def test_cli_passes_practice_team_member_id(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--registration-id", "reg-1", "--practice", "--practice-team-member-id", "member-1")

    cli.main()

    assert seen["practice_team_member_id"] == "member-1"
