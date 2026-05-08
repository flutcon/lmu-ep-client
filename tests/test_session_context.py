from unittest.mock import MagicMock

from lmu_ep_client.session_context import (
    SessionContext,
    _build_driver_map,
    fetch_session_context,
)


def test_build_driver_map_filters_null_lmu_name():
    roster = [
        {"id": "m1", "lmuDriverName": "Alex S.", "userName": "Alex Schmidt"},
        {"id": "m2", "lmuDriverName": None, "userName": "Mira Patel"},
        {"id": "m3", "lmuDriverName": "Jin K.", "userName": "Jin Kim"},
    ]
    assert _build_driver_map(roster) == {"Alex S.": "m1", "Jin K.": "m3"}


def test_build_driver_map_empty_roster():
    assert _build_driver_map([]) == {}


def test_session_context_resolve_driver():
    ctx = SessionContext(
        registration_id="r1",
        session_id="s1",
        driver_to_member_id={"Alex S.": "m1"},
    )
    assert ctx.resolve_driver("Alex S.") == "m1"
    assert ctx.resolve_driver("Unknown") is None


def test_fetch_session_context_creates_then_fetches():
    api = MagicMock()
    api.create_session.return_value = {"id": "s1"}
    api.get_session.return_value = {
        "id": "s1",
        "eventRegistrationId": "r1",
        "status": "active",
        "events": [],
        "teamMembers": [
            {"id": "m1", "lmuDriverName": "Alex S.", "userName": "Alex"},
            {"id": "m2", "lmuDriverName": None, "userName": "Mira"},
        ],
    }

    ctx = fetch_session_context(api, "r1")

    api.create_session.assert_called_once_with("r1")
    api.get_session.assert_called_once_with("r1")
    assert ctx.registration_id == "r1"
    assert ctx.session_id == "s1"
    assert ctx.driver_to_member_id == {"Alex S.": "m1"}


def test_fetch_session_context_handles_missing_roster_field():
    api = MagicMock()
    api.create_session.return_value = {"id": "s1"}
    api.get_session.return_value = {"id": "s1", "events": []}

    ctx = fetch_session_context(api, "r1")
    assert ctx.driver_to_member_id == {}
