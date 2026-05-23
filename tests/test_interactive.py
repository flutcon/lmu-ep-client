from __future__ import annotations

import pytest

from lmu_ep_client import interactive


class _FakePrompt:
    def __init__(self, value):
        self._value = value
        self.kwargs = None

    def ask(self):
        return self._value


def test_select_registration_returns_picked_dict(monkeypatch):
    regs = [{"id": "r1", "eventTitle": "12h"}, {"id": "r2", "eventTitle": "24h"}]
    captured = {}

    def fake_select(message, choices, **kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return _FakePrompt(choices[1].value)

    monkeypatch.setattr(interactive.questionary, "select", fake_select)
    picked = interactive.select_registration(regs)

    assert picked == regs[1]
    assert "Pick a registration" in captured["message"]
    assert len(captured["choices"]) == 2


def test_select_registration_empty_raises():
    with pytest.raises(interactive.InteractiveAbort):
        interactive.select_registration([])


def test_select_registration_cancel_raises(monkeypatch):
    monkeypatch.setattr(
        interactive.questionary,
        "select",
        lambda *args, **kwargs: _FakePrompt(None),
    )
    with pytest.raises(interactive.InteractiveAbort):
        interactive.select_registration([{"id": "r1"}])


def test_select_mode_returns_choice(monkeypatch):
    monkeypatch.setattr(
        interactive.questionary,
        "select",
        lambda *args, **kwargs: _FakePrompt("race"),
    )
    assert interactive.select_mode() == "race"


def test_select_team_member_returns_picked_dict(monkeypatch):
    members = [{"id": "m1", "userName": "Alice"}, {"id": "m2", "userName": "Bob"}]

    def fake_select(message, choices, **kwargs):
        return _FakePrompt(choices[0].value)

    monkeypatch.setattr(interactive.questionary, "select", fake_select)
    assert interactive.select_team_member(members) == members[0]


def test_select_team_member_empty_raises():
    with pytest.raises(interactive.InteractiveAbort):
        interactive.select_team_member([])


def test_format_registration_handles_missing_fields():
    out = interactive._format_registration({"id": "r1"})
    assert "no start time" in out
    assert "?" in out  # missing track/car keys
