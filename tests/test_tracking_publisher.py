from unittest.mock import MagicMock

from lmu_ep_client.api_client import ApiError
from lmu_ep_client.session_context import SessionContext
from lmu_ep_client.tracking_publisher import TrackingPublisher


def _make(api: MagicMock, roster: dict[str, str] | None = None) -> TrackingPublisher:
    ctx = SessionContext(
        registration_id="r1",
        session_id="s1",
        driver_to_member_id=roster or {"Alex S.": "m1", "Jin K.": "m3"},
    )
    return TrackingPublisher(api, ctx)


def _last_post(api: MagicMock) -> tuple[str, dict]:
    args, kwargs = api.post.call_args
    path = args[0] if args else kwargs["path"]
    body = kwargs.get("body") or (args[1] if len(args) > 1 else None)
    return path, body


def test_driver_started_resolves_known_driver():
    api = MagicMock()
    pub = _make(api)
    pub.driver_started("Alex S.")

    path, body = _last_post(api)
    assert path == "/api/tracking/registrations/r1/events"
    assert body["type"] == "driver_started"
    assert body["teamMemberId"] == "m1"
    assert "occurredAt" in body


def test_driver_started_unknown_driver_sends_null_team_member_id():
    api = MagicMock()
    api.get_session.return_value = {"id": "s1", "teamMembers": []}
    pub = _make(api)
    pub.driver_started("Unknown Person")

    _, body = _last_post(api)
    assert body["teamMemberId"] is None


def test_driver_stopped_payload():
    api = MagicMock()
    pub = _make(api)
    pub.driver_stopped("Jin K.")

    _, body = _last_post(api)
    assert body["type"] == "driver_stopped"
    assert body["teamMemberId"] == "m3"


def test_pitstop_with_swap_includes_both_ids():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Jin K.", meta={"standing_time_seconds": 32.1})

    _, body = _last_post(api)
    assert body["type"] == "pitstop"
    assert body["swapFromMemberId"] == "m1"
    assert body["teamMemberId"] == "m3"
    assert body["meta"] == {"standing_time_seconds": 32.1}


def test_pitstop_same_driver_no_swap():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Alex S.", meta={"fuel_added_litres": 50})

    _, body = _last_post(api)
    assert body["type"] == "pitstop"
    assert "swapFromMemberId" not in body
    assert "teamMemberId" not in body
    assert body["meta"]["fuel_added_litres"] == 50


def test_pitstop_swap_with_unknown_new_driver_drops_swap_fields():
    api = MagicMock()
    api.get_session.return_value = {"id": "s1", "teamMembers": []}
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Ghost", meta={})

    _, body = _last_post(api)
    assert body["type"] == "pitstop"
    assert "swapFromMemberId" not in body
    assert "teamMemberId" not in body


def test_pitstop_omits_meta_when_none():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver=None, new_driver=None, meta=None)

    _, body = _last_post(api)
    assert "meta" not in body


def test_publisher_swallows_api_errors():
    api = MagicMock()
    api.post.side_effect = ApiError(status=500, code="INTERNAL", message="boom")
    pub = _make(api)

    # Should not raise — poller stays alive.
    pub.driver_started("Alex S.")
    pub.driver_stopped("Alex S.")
    pub.pitstop("Alex S.", "Jin K.", {})


def test_pitstop_path_uses_registration_id():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver=None, new_driver=None, meta=None)

    path, _ = _last_post(api)
    assert path == "/api/tracking/registrations/r1/events"
