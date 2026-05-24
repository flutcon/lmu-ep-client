from unittest.mock import MagicMock

from lmu_ep_client.api_client import ApiError
from lmu_ep_client.session_context import SessionContext
from lmu_ep_client.tracking_outbox import TrackingOutbox
from lmu_ep_client.tracking_publisher import TrackingPublisher


def _make(
    api: MagicMock,
    roster: dict[str, str] | None = None,
    outbox: TrackingOutbox | None = None,
    practice_session_id: str | None = None,
) -> TrackingPublisher:
    ctx = SessionContext(
        registration_id="r1",
        session_id=practice_session_id or "s1",
        kind="practice" if practice_session_id else "race",
        practice_session_id=practice_session_id,
        practice_team_member_id="m1" if practice_session_id else None,
        driver_to_member_id=roster or {"Alex S.": "m1", "Jin K.": "m3"},
    )
    return TrackingPublisher(api, ctx, outbox=outbox or TrackingOutbox.in_memory())


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


def _post_bodies(api: MagicMock) -> list[dict]:
    bodies = []
    for call in api.post.call_args_list:
        args, kwargs = call
        bodies.append(kwargs.get("body") or (args[1] if len(args) > 1 else None))
    return bodies


def test_pitstop_with_swap_emits_clean_pitstop_then_driver_started():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Jin K.", meta={"standing_time_seconds": 32.1})

    bodies = _post_bodies(api)
    assert len(bodies) == 2

    pit_body, swap_body = bodies
    assert pit_body["type"] == "pitstop"
    assert "swapFromMemberId" not in pit_body
    assert "teamMemberId" not in pit_body
    assert pit_body["meta"] == {"standing_time_seconds": 32.1}

    assert swap_body["type"] == "driver_started"
    assert swap_body["teamMemberId"] == "m3"
    assert swap_body["swapFromMemberId"] == "m1"


def test_pitstop_same_driver_emits_only_pitstop():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Alex S.", meta={"fuel_added_litres": 50})

    bodies = _post_bodies(api)
    assert len(bodies) == 1
    body = bodies[0]
    assert body["type"] == "pitstop"
    assert "swapFromMemberId" not in body
    assert "teamMemberId" not in body
    assert body["meta"]["fuel_added_litres"] == 50


def test_pitstop_swap_with_unknown_new_driver_skips_swap_event():
    api = MagicMock()
    api.get_session.return_value = {"id": "s1", "teamMembers": []}
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Ghost", meta={})

    bodies = _post_bodies(api)
    assert len(bodies) == 1
    body = bodies[0]
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


def test_publisher_queues_failed_event_for_later_replay(tmp_path):
    api = MagicMock()
    api.post.side_effect = ApiError(status=0, code="NETWORK", message="down")
    pub = _make(api, outbox=TrackingOutbox(tmp_path / "outbox.json"))

    pub.driver_started("Alex S.")

    restarted_outbox = TrackingOutbox(tmp_path / "outbox.json")
    assert restarted_outbox.pending_count == 1
    api.post.side_effect = None
    api.post.reset_mock()

    restarted_outbox.drain(api, force=True)

    _, kwargs = api.post.call_args
    assert kwargs["body"]["type"] == "driver_started"
    assert kwargs["idempotency_key"]


def test_end_session_patches_status_through_outbox(tmp_path):
    api = MagicMock()
    pub = _make(api, outbox=TrackingOutbox(tmp_path / "outbox.json"))

    pub.end_session()

    api.patch_session_status.assert_called_once_with("r1", "ended")
    assert TrackingOutbox(tmp_path / "outbox.json").pending_count == 0


def test_end_practice_session_patches_practice_status_through_outbox(tmp_path):
    api = MagicMock()
    pub = _make(api, outbox=TrackingOutbox(tmp_path / "outbox.json"), practice_session_id="p1")

    pub.end_session()

    api.patch_practice_session_status.assert_called_once_with("p1", "ended")
    assert TrackingOutbox(tmp_path / "outbox.json").pending_count == 0


def test_end_session_queues_failed_status_for_later_replay(tmp_path):
    api = MagicMock()
    api.patch_session_status.side_effect = ApiError(status=0, code="NETWORK", message="down")
    pub = _make(api, outbox=TrackingOutbox(tmp_path / "outbox.json"))

    pub.end_session()

    restarted_outbox = TrackingOutbox(tmp_path / "outbox.json")
    assert restarted_outbox.pending_count == 1
    api.patch_session_status.side_effect = None
    api.patch_session_status.reset_mock()

    restarted_outbox.drain(api, force=True)

    api.patch_session_status.assert_called_once_with("r1", "ended")


def test_pitstop_path_uses_registration_id():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver=None, new_driver=None, meta=None)

    path, _ = _last_post(api)
    assert path == "/api/tracking/registrations/r1/events"


def test_pit_entered_uses_provided_occurred_at():
    """pit_entered is deferred until pit_at_box so the poller backdates it
    with the wall-clock captured at the actual pit-lane crossing."""
    api = MagicMock()
    pub = _make(api)
    pub.pit_entered(occurred_at="2026-05-11T10:00:00Z")

    path, body = _last_post(api)
    assert path == "/api/tracking/registrations/r1/events"
    assert body == {"type": "pit_entered", "occurredAt": "2026-05-11T10:00:00Z"}


def test_event_bodies_include_et_seconds_when_provided():
    """etSeconds (mCurrentET) carries the game's session-elapsed time so events
    from all teammates in the same online session share a common ordering key."""
    api = MagicMock()
    pub = _make(api)

    pub.driver_started("Alex S.", et_seconds=12.5)
    pub.driver_stopped("Alex S.", et_seconds=99.25)
    pub.pit_entered(et_seconds=200.0)
    pub.pit_at_box(et_seconds=210.0)
    pub.pit_departed(et_seconds=240.0)
    pub.pit_exited(et_seconds=245.0)
    pub.lap_completed(
        lap_time_seconds=124.318,
        tyre_wear={"fl": 92.4, "fr": 91.7, "rl": 87.0, "rr": 86.5},
        energy_pct=73.2,
        fuel_litres=48.5,
        team_member_id="m1",
        et_seconds=370.0,
    )

    bodies = _post_bodies(api)
    assert [body["etSeconds"] for body in bodies] == [12.5, 99.25, 200.0, 210.0, 240.0, 245.0, 370.0]


def test_pitstop_with_swap_stamps_et_seconds_on_both_events():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(prev_driver="Alex S.", new_driver="Jin K.", meta={}, et_seconds=555.5)

    bodies = _post_bodies(api)
    assert len(bodies) == 2
    assert bodies[0]["type"] == "pitstop"
    assert bodies[0]["etSeconds"] == 555.5
    assert bodies[1]["type"] == "driver_started"
    assert bodies[1]["etSeconds"] == 555.5


def test_event_bodies_omit_et_seconds_when_absent():
    api = MagicMock()
    pub = _make(api)
    pub.pit_at_box()

    _, body = _last_post(api)
    assert "etSeconds" not in body


def test_pit_entered_defaults_occurred_at_to_now():
    api = MagicMock()
    pub = _make(api)
    pub.pit_entered()

    _, body = _last_post(api)
    assert body["type"] == "pit_entered"
    assert body["occurredAt"]  # server-now fallback


def test_pit_phase_methods_post_correct_types():
    api = MagicMock()
    pub = _make(api)
    pub.pit_at_box()
    pub.pit_departed()
    pub.pit_exited()

    types = [b["type"] for b in _post_bodies(api)]
    assert types == ["pit_at_box", "pit_departed", "pit_exited"]


def test_pit_phase_methods_omit_team_member_id():
    """Phase events have no driver association — the server rejects teamMemberId on them."""
    api = MagicMock()
    pub = _make(api)
    pub.pit_entered()
    pub.pit_at_box()
    pub.pit_departed()
    pub.pit_exited()

    for body in _post_bodies(api):
        assert "teamMemberId" not in body
        assert "swapFromMemberId" not in body
        assert "meta" not in body


def test_pit_phase_methods_attach_meta_when_provided():
    api = MagicMock()
    pub = _make(api)
    meta = {
        "fuel_litres": 72.34,
        "energy_percent": 54.32,
        "tyre_wear": {"FL": 0.8123, "FR": 0.7988, "RL": 0.8457, "RR": 0.8235},
    }

    pub.pit_at_box(meta=meta)
    pub.pit_departed(meta=meta)

    box_body, departed_body = _post_bodies(api)
    assert box_body["type"] == "pit_at_box"
    assert box_body["meta"] == meta
    assert departed_body["type"] == "pit_departed"
    assert departed_body["meta"] == meta


def test_practice_events_include_practice_session_id():
    api = MagicMock()
    pub = _make(api, practice_session_id="p1")

    pub.driver_started("Alex S.")
    pub.pit_at_box()
    pub.lap_completed(
        lap_time_seconds=124.318,
        tyre_wear={"fl": 92.4, "fr": 91.7, "rl": 87.0, "rr": 86.5},
        energy_pct=73.2,
        fuel_litres=48.5,
        team_member_id="m1",
    )

    bodies = _post_bodies(api)
    assert [body["type"] for body in bodies] == ["driver_started", "pit_at_box", "lap_completed"]
    for body in bodies:
        assert body["practiceSessionId"] == "p1"
    assert bodies[2]["teamMemberId"] == "m1"
    assert bodies[2]["meta"] == {
        "lapTimeSeconds": 124.318,
        "tyreWear": {"fl": 92.4, "fr": 91.7, "rl": 87.0, "rr": 86.5},
        "energyPct": 73.2,
        "fuelLitres": 48.5,
    }


def test_practice_driver_events_fall_back_to_pinned_team_member_without_roster():
    api = MagicMock()
    ctx = SessionContext(
        registration_id="r1",
        session_id="p1",
        kind="practice",
        practice_session_id="p1",
        practice_team_member_id="m1",
        driver_to_member_id={},
    )
    pub = TrackingPublisher(api, ctx, outbox=TrackingOutbox.in_memory())

    pub.driver_started("Unknown LMU Name")

    _, body = _last_post(api)
    assert body["type"] == "driver_started"
    assert body["teamMemberId"] == "m1"
    assert body["practiceSessionId"] == "p1"
    api.get_session.assert_not_called()


def test_now_iso_returns_zulu_timestamp():
    from lmu_ep_client.tracking_publisher import TrackingPublisher

    ts = TrackingPublisher.now_iso()
    assert ts.endswith("Z")
    # YYYY-MM-DDTHH:MM:SSZ — 20 chars
    assert len(ts) == 20


def test_driver_started_attaches_meta():
    api = MagicMock()
    pub = _make(api)
    pub.driver_started("Alex S.", meta={"track": "Monza", "vehicle": "Porsche 963", "vehicle_class": "Hypercar"})

    _, body = _last_post(api)
    assert body["meta"] == {"track": "Monza", "vehicle": "Porsche 963", "vehicle_class": "Hypercar"}
    assert body["teamMemberId"] == "m1"


def test_driver_started_omits_meta_when_none():
    api = MagicMock()
    pub = _make(api)
    pub.driver_started("Alex S.")

    _, body = _last_post(api)
    assert "meta" not in body


def test_driver_stopped_attaches_finish_status_meta():
    api = MagicMock()
    pub = _make(api)
    pub.driver_stopped("Alex S.", meta={"finish_status": "dnf"})

    _, body = _last_post(api)
    assert body["meta"] == {"finish_status": "dnf"}
    assert body["teamMemberId"] == "m1"


def test_pitstop_swap_attaches_started_meta_to_swap_event_only():
    """started_meta tags the new driver's stint with track/vehicle context —
    it belongs on the swap driver_started event, NOT on the pitstop body."""
    api = MagicMock()
    pub = _make(api)
    pit_meta = {"fuel_added_litres": 50, "post_fuel_litres": 110.0}
    started_meta = {"track": "Spa", "vehicle": "Porsche 963", "vehicle_class": "Hypercar"}
    pub.pitstop(
        prev_driver="Alex S.",
        new_driver="Jin K.",
        meta=pit_meta,
        started_meta=started_meta,
    )

    bodies = _post_bodies(api)
    assert len(bodies) == 2
    pit_body, swap_body = bodies
    assert pit_body["meta"] == pit_meta
    # started_meta must not leak into the pitstop body
    assert pit_body["meta"] != started_meta
    assert swap_body["type"] == "driver_started"
    assert swap_body["meta"] == started_meta
    assert swap_body["swapFromMemberId"] == "m1"


def test_pitstop_without_swap_ignores_started_meta():
    api = MagicMock()
    pub = _make(api)
    pub.pitstop(
        prev_driver="Alex S.",
        new_driver="Alex S.",
        meta={"fuel_added_litres": 30},
        started_meta={"track": "Spa", "vehicle": "Porsche 963", "vehicle_class": "Hypercar"},
    )

    bodies = _post_bodies(api)
    # No driver change -> no swap event, so started_meta is silently dropped.
    assert len(bodies) == 1
    assert bodies[0]["type"] == "pitstop"
