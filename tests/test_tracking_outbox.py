from __future__ import annotations

import json
from unittest.mock import MagicMock

from lmu_ep_client.api_client import ApiError
from lmu_ep_client.tracking_outbox import TrackingOutbox


def test_enqueue_persists_event_with_idempotency_key(tmp_path):
    outbox = TrackingOutbox(tmp_path / "outbox.json")

    item = outbox.enqueue("/api/tracking/registrations/r1/events", {"type": "pitstop"})

    raw = json.loads((tmp_path / "outbox.json").read_text(encoding="utf-8"))
    assert raw[0]["path"] == "/api/tracking/registrations/r1/events"
    assert raw[0]["body"] == {"type": "pitstop"}
    assert raw[0]["idempotency_key"] == item.idempotency_key
    assert raw[0]["sent_at"] is None


def test_drain_marks_event_sent_after_success(tmp_path):
    outbox = TrackingOutbox(tmp_path / "outbox.json")
    item = outbox.enqueue("/api/tracking/registrations/r1/events", {"type": "driver_started"})
    api = MagicMock()

    outbox.drain(api)

    api.post.assert_called_once_with(
        "/api/tracking/registrations/r1/events",
        body={"type": "driver_started"},
        idempotency_key=item.idempotency_key,
    )
    reloaded = TrackingOutbox(tmp_path / "outbox.json")
    assert reloaded.pending_count == 0


def test_drain_replays_pending_event_after_restart(tmp_path):
    first = TrackingOutbox(tmp_path / "outbox.json")
    item = first.enqueue("/api/tracking/registrations/r1/events", {"type": "pit_at_box"})
    api = MagicMock()
    api.post.side_effect = ApiError(status=0, code="NETWORK", message="down")

    first.drain(api)

    restarted = TrackingOutbox(tmp_path / "outbox.json")
    api.post.side_effect = None
    api.post.reset_mock()
    restarted.drain(api, force=True)

    api.post.assert_called_once_with(
        "/api/tracking/registrations/r1/events",
        body={"type": "pit_at_box"},
        idempotency_key=item.idempotency_key,
    )
    assert TrackingOutbox(tmp_path / "outbox.json").pending_count == 0


def test_drain_replays_pending_session_status_after_restart(tmp_path):
    first = TrackingOutbox(tmp_path / "outbox.json")
    first.enqueue_session_status("r1", "ended")
    api = MagicMock()
    api.patch_session_status.side_effect = ApiError(status=0, code="NETWORK", message="down")

    first.drain(api)

    restarted = TrackingOutbox(tmp_path / "outbox.json")
    api.patch_session_status.side_effect = None
    api.patch_session_status.reset_mock()
    restarted.drain(api, force=True)

    api.patch_session_status.assert_called_once_with("r1", "ended")
    assert TrackingOutbox(tmp_path / "outbox.json").pending_count == 0


def test_failed_send_uses_backoff_before_retry(tmp_path):
    now = [1000.0]
    outbox = TrackingOutbox(tmp_path / "outbox.json", clock=lambda: now[0])
    outbox.enqueue("/api/tracking/registrations/r1/events", {"type": "pit_exited"})
    api = MagicMock()
    api.post.side_effect = ApiError(status=0, code="NETWORK", message="down")

    outbox.drain(api)
    outbox.drain(api)
    assert api.post.call_count == 1

    now[0] += 2.0
    outbox.drain(api)
    assert api.post.call_count == 2
