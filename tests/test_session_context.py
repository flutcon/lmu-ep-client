from unittest.mock import MagicMock

from lmu_ep_client.api_client import ApiError
from lmu_ep_client.session_context import (
    SessionContext,
    _build_driver_map,
    fetch_practice_session_context,
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


def test_fetch_practice_session_context_creates_practice_session_without_race_session_lookup():
    api = MagicMock()
    api.create_practice_session.return_value = {
        "id": "p1",
        "kind": "practice",
        "eventRegistrationId": "r1",
        "teamMemberId": "m1",
    }

    ctx = fetch_practice_session_context(api, "r1", "m1")

    api.create_practice_session.assert_called_once_with("r1", "m1")
    api.get_session.assert_not_called()
    assert ctx.registration_id == "r1"
    assert ctx.session_id == "p1"
    assert ctx.practice_session_id == "p1"
    assert ctx.practice_team_member_id == "m1"
    assert ctx.kind == "practice"
    assert ctx.driver_to_member_id == {}


def test_fetch_practice_session_context_does_not_require_race_session():
    api = MagicMock()
    api.create_practice_session.return_value = {
        "id": "p1",
        "kind": "practice",
        "eventRegistrationId": "r1",
        "teamMemberId": "m1",
    }
    api.get_session.side_effect = ApiError(status=404, code="NOT_FOUND", message="No tracking session")

    ctx = fetch_practice_session_context(api, "r1", "m1")

    api.create_practice_session.assert_called_once_with("r1", "m1")
    api.get_session.assert_not_called()
    assert ctx.registration_id == "r1"
    assert ctx.session_id == "p1"
    assert ctx.practice_session_id == "p1"
    assert ctx.practice_team_member_id == "m1"
    assert ctx.kind == "practice"
    assert ctx.driver_to_member_id == {}


def test_resolve_driver_cache_hit_does_not_call_api():
    api = MagicMock()
    ctx = SessionContext(
        registration_id="r1",
        session_id="s1",
        driver_to_member_id={"Alex S.": "m1"},
    )
    assert ctx.resolve_driver("Alex S.", api=api) == "m1"
    api.get_session.assert_not_called()


def test_resolve_driver_cache_miss_refetches_and_updates_map():
    api = MagicMock()
    api.get_session.return_value = {
        "id": "s1",
        "teamMembers": [
            {"id": "m1", "lmuDriverName": "Alex S."},
            {"id": "m3", "lmuDriverName": "Jin K."},  # new since startup
        ],
    }
    ctx = SessionContext(
        registration_id="r1",
        session_id="s1",
        driver_to_member_id={"Alex S.": "m1"},
    )
    assert ctx.resolve_driver("Jin K.", api=api) == "m3"
    api.get_session.assert_called_once_with("r1")
    assert ctx.driver_to_member_id == {"Alex S.": "m1", "Jin K.": "m3"}


def test_resolve_driver_throttles_repeated_misses():
    api = MagicMock()
    api.get_session.return_value = {"id": "s1", "teamMembers": []}
    ctx = SessionContext(registration_id="r1", session_id="s1")

    # First miss triggers a refetch.
    assert ctx.resolve_driver("Ghost", api=api) is None
    # Second miss within the throttle window does NOT refetch.
    assert ctx.resolve_driver("Ghost", api=api) is None
    api.get_session.assert_called_once()


def test_resolve_driver_handles_api_error_silently():
    api = MagicMock()
    api.get_session.side_effect = ApiError(status=500, code="INTERNAL", message="boom")
    ctx = SessionContext(registration_id="r1", session_id="s1")

    assert ctx.resolve_driver("Anyone", api=api) is None


def test_resolve_driver_without_api_just_does_dict_lookup():
    ctx = SessionContext(
        registration_id="r1",
        session_id="s1",
        driver_to_member_id={"Alex S.": "m1"},
    )
    assert ctx.resolve_driver("Alex S.") == "m1"
    assert ctx.resolve_driver("Unknown") is None
