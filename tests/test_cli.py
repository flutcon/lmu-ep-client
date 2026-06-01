from __future__ import annotations

import sys
from pathlib import Path

from lmu_ep_client import cli


def _set_argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["lmu-ep-client", *args])


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


def test_list_registrations_uses_env_api_key(monkeypatch):
    seen = {}

    def fake_list_registrations(api):
        seen["api_key"] = api._api_key

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "_list_registrations", fake_list_registrations)
    _set_argv(monkeypatch, "--list-registrations")

    cli.main()

    assert seen["api_key"] == "env-key"


def test_list_registrations_prints_private_owner(capsys):
    class FakeApi:
        def list_registrations(self):
            return [
                {
                    "id": "reg-1",
                    "trackKey": "lemans",
                    "trackLayoutKey": "24h",
                    "carKey": "porsche-963",
                    "startsAt": "2026-06-14T18:00:00Z",
                    "eventTitle": "Private Practice",
                    "isPrivate": True,
                    "ownerLmuDriverName": "A. Racer",
                    "hasTrackingSession": False,
                }
            ]

    cli._list_registrations(FakeApi())

    out = capsys.readouterr().out
    assert "Private" in out
    assert "A. Racer" in out


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


def test_cli_practice_without_team_member_id_in_non_tty_errors(monkeypatch):
    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "is_tty", lambda: False)
    _set_argv(monkeypatch, "--registration-id", "reg-1", "--practice")

    try:
        cli.main()
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected parser error")


def test_cli_interactive_picks_registration(monkeypatch):
    seen = {}

    def fake_list_registrations(self):
        return [{"id": "reg-A", "eventTitle": "12h"}, {"id": "reg-B", "eventTitle": "24h"}]

    def fake_select_registration(regs):
        assert len(regs) == 2
        return regs[1]

    def fake_select_mode():
        return "race"

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "is_tty", lambda: True)
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_registrations", fake_list_registrations
    )
    monkeypatch.setattr(cli, "select_registration", fake_select_registration)
    monkeypatch.setattr(cli, "select_mode", fake_select_mode)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--api-key", "cli-key")

    cli.main()

    assert seen["registration_id"] == "reg-B"
    assert seen["api_key"] == "cli-key"
    assert seen["practice_team_member_id"] is None


def test_cli_interactive_picks_practice_team_member(monkeypatch):
    seen = {}

    def fake_list_registrations(self):
        return [{"id": "reg-A", "eventTitle": "12h"}]

    def fake_list_team_members(self, reg_id):
        assert reg_id == "reg-A"
        return [{"id": "m1", "userName": "Alice"}, {"id": "m2", "userName": "Bob"}]

    def fake_select_registration(regs):
        return regs[0]

    def fake_select_mode():
        return "practice"

    def fake_select_team_member(members):
        return members[1]

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "is_tty", lambda: True)
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_registrations", fake_list_registrations
    )
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_team_members", fake_list_team_members
    )
    monkeypatch.setattr(cli, "select_registration", fake_select_registration)
    monkeypatch.setattr(cli, "select_mode", fake_select_mode)
    monkeypatch.setattr(cli, "select_team_member", fake_select_team_member)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--api-key", "cli-key")

    cli.main()

    assert seen["registration_id"] == "reg-A"
    assert seen["practice_team_member_id"] == "m2"


def test_env_api_key_without_registration_id_falls_through_to_file_only(monkeypatch, tmp_path):
    """A configured env/config API key without --registration-id must NOT trigger
    interactive prompts — scheduled and redirected runs depend on the documented
    file-only logging fallback."""
    seen = {}
    list_regs_called = {"count": 0}

    def fake_list_registrations(self):
        list_regs_called["count"] += 1
        return []

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    # Simulate a redirected/scheduled context (no TTY) — must not error.
    monkeypatch.setattr(cli, "is_tty", lambda: False)
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_registrations", fake_list_registrations
    )
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--config", str(tmp_path / "missing.toml"))

    cli.main()

    assert list_regs_called["count"] == 0
    assert seen["api_key"] is None
    assert seen["registration_id"] is None


def test_config_api_key_without_registration_id_falls_through_to_file_only(
    monkeypatch, tmp_path
):
    seen = {}
    config_path = tmp_path / "config.toml"
    config_path.write_text('[tracking]\napi_key = "cfg-key"\n', encoding="utf-8")

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "is_tty", lambda: False)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--config", str(config_path))

    cli.main()

    assert seen["api_key"] is None
    assert seen["registration_id"] is None


def test_explicit_api_key_without_registration_in_non_tty_errors(monkeypatch):
    """The original behavior — --api-key without --registration-id and no TTY
    to prompt in — must still be an error."""
    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "is_tty", lambda: False)
    _set_argv(monkeypatch, "--api-key", "cli-key")

    try:
        cli.main()
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected parser error")


def test_cli_interactive_explicit_key_with_practice_flag_skips_mode_prompt(monkeypatch):
    """--api-key + --practice → interactive registration, then skip the
    race-vs-practice prompt, then prompt for the team member."""
    seen = {}
    select_mode_called = {"count": 0}

    def fake_list_registrations(self):
        return [{"id": "reg-A", "eventTitle": "12h"}]

    def fake_list_team_members(self, reg_id):
        return [{"id": "m1", "userName": "Alice"}]

    def fake_select_mode():
        select_mode_called["count"] += 1
        return "practice"

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "is_tty", lambda: True)
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_registrations", fake_list_registrations
    )
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_team_members", fake_list_team_members
    )
    monkeypatch.setattr(cli, "select_registration", lambda regs: regs[0])
    monkeypatch.setattr(cli, "select_mode", fake_select_mode)
    monkeypatch.setattr(cli, "select_team_member", lambda members: members[0])
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--api-key", "cli-key", "--practice")

    cli.main()

    assert select_mode_called["count"] == 0
    assert seen["practice_team_member_id"] == "m1"


def test_cli_interactive_only_team_member_when_registration_given(monkeypatch):
    """--registration-id + --practice but no team-member-id → only team-member prompt."""
    seen = {}
    list_regs_called = {"count": 0}

    def fake_list_registrations(self):
        list_regs_called["count"] += 1
        return []

    def fake_list_team_members(self, reg_id):
        return [{"id": "m1", "userName": "Alice"}]

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "is_tty", lambda: True)
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_registrations", fake_list_registrations
    )
    monkeypatch.setattr(
        "lmu_ep_client.api_client.TrackingClient.list_team_members", fake_list_team_members
    )
    monkeypatch.setattr(cli, "select_team_member", lambda members: members[0])
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--registration-id", "reg-X", "--practice")

    cli.main()

    assert list_regs_called["count"] == 0
    assert seen["registration_id"] == "reg-X"
    assert seen["practice_team_member_id"] == "m1"


def test_cli_no_api_key_runs_without_tracking(monkeypatch, tmp_path):
    """Without an API key, the client should still run as a file-only logger.

    Points --config at a non-existent path so the developer's real
    ~/.config/lmu-ep-client/config.toml is not read.
    """
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.delenv("LMU_EP_API_KEY", raising=False)
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--config", str(tmp_path / "missing.toml"))

    cli.main()

    assert seen["api_key"] is None
    assert seen["registration_id"] is None


def test_cli_passes_practice_team_member_id(monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setenv("LMU_EP_API_KEY", "env-key")
    monkeypatch.setattr(cli, "run", fake_run)
    _set_argv(monkeypatch, "--registration-id", "reg-1", "--practice", "--practice-team-member-id", "member-1")

    cli.main()

    assert seen["practice_team_member_id"] == "member-1"


def test_version_flag_prints_version_and_exits(monkeypatch, capsys):
    from lmu_ep_client import __version__

    _set_argv(monkeypatch, "--version")

    try:
        cli.main()
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("--version did not exit")

    assert __version__ in capsys.readouterr().out
