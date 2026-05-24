from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lmu_ep_client.api_client import TrackingClient
from lmu_ep_client.session_context import SessionContext
from lmu_ep_client.tracking_outbox import TrackingOutbox, default_outbox_path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TrackingPublisher:
    """Maps detector events to tracking API calls.

    Public event methods persist to the local outbox before sending. The
    outbox logs + swallows ApiError so a transient network failure can't take
    down the polling loop, and pending events can be replayed later.
    """

    def __init__(
        self,
        api: TrackingClient,
        ctx: SessionContext,
        outbox: TrackingOutbox | None = None,
    ) -> None:
        self._api = api
        self._ctx = ctx
        self._outbox = outbox or TrackingOutbox(default_outbox_path())

    @property
    def registration_id(self) -> str:
        return self._ctx.registration_id

    @property
    def is_practice(self) -> bool:
        return self._ctx.kind == "practice" and self._ctx.practice_session_id is not None

    @staticmethod
    def now_iso() -> str:
        return _now_iso()

    def _post_event(self, body: dict[str, Any]) -> None:
        if self._ctx.practice_session_id is not None:
            body = {**body, "practiceSessionId": self._ctx.practice_session_id}
        path = f"/api/tracking/registrations/{self._ctx.registration_id}/events"
        self._outbox.enqueue(path, body)
        self._outbox.drain(self._api, force=True)

    def flush_pending(self, force: bool = False) -> int:
        return self._outbox.drain(self._api, force=force)

    def set_session_status(self, status: str) -> None:
        if self._ctx.practice_session_id is not None:
            self._outbox.enqueue_practice_session_status(self._ctx.practice_session_id, status)
        else:
            self._outbox.enqueue_session_status(self._ctx.registration_id, status)
        self._outbox.drain(self._api, force=True)

    def end_session(self) -> None:
        self.set_session_status("ended")

    def _post_phase(
        self,
        event_type: str,
        occurred_at: str | None,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        body: dict[str, Any] = {"type": event_type, "occurredAt": occurred_at or _now_iso()}
        if et_seconds is not None:
            body["etSeconds"] = et_seconds
        if meta:
            body["meta"] = meta
        self._post_event(body)

    def pit_entered(
        self,
        occurred_at: str | None = None,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        self._post_phase("pit_entered", occurred_at, meta, et_seconds)

    def pit_at_box(
        self,
        occurred_at: str | None = None,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        self._post_phase("pit_at_box", occurred_at, meta, et_seconds)

    def pit_departed(
        self,
        occurred_at: str | None = None,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        self._post_phase("pit_departed", occurred_at, meta, et_seconds)

    def pit_exited(
        self,
        occurred_at: str | None = None,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        self._post_phase("pit_exited", occurred_at, meta, et_seconds)

    def _resolve(self, lmu_driver_name: str | None) -> str | None:
        if not lmu_driver_name:
            return self._ctx.practice_team_member_id if self.is_practice else None
        if self.is_practice:
            return self._ctx.driver_to_member_id.get(lmu_driver_name) or self._ctx.practice_team_member_id
        member_id = self._ctx.resolve_driver(lmu_driver_name, api=self._api)
        if member_id is None:
            logger.warning(
                "Driver %r not in roster (lmuDriverName unset on team member?) — "
                "sending event without teamMemberId",
                lmu_driver_name,
            )
        return member_id

    def driver_started(
        self,
        lmu_driver_name: str,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "type": "driver_started",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        if et_seconds is not None:
            body["etSeconds"] = et_seconds
        if meta:
            body["meta"] = meta
        self._post_event(body)

    def driver_stopped(
        self,
        lmu_driver_name: str,
        meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "type": "driver_stopped",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        if et_seconds is not None:
            body["etSeconds"] = et_seconds
        if meta:
            body["meta"] = meta
        self._post_event(body)

    def resolve_driver(self, lmu_driver_name: str | None) -> str | None:
        return self._resolve(lmu_driver_name)

    def lap_completed(
        self,
        lap_time_seconds: float,
        tyre_wear: dict[str, float],
        energy_pct: float | None,
        fuel_litres: float | None,
        team_member_id: str | None = None,
        et_seconds: float | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "type": "lap_completed",
            "occurredAt": _now_iso(),
            "teamMemberId": team_member_id,
            "meta": {
                "lapTimeSeconds": lap_time_seconds,
                "tyreWear": tyre_wear,
                "energyPct": energy_pct,
                "fuelLitres": fuel_litres,
            },
        }
        if et_seconds is not None:
            body["etSeconds"] = et_seconds
        self._post_event(body)

    def pitstop(
        self,
        prev_driver: str | None,
        new_driver: str | None,
        meta: dict[str, Any] | None = None,
        started_meta: dict[str, Any] | None = None,
        et_seconds: float | None = None,
    ) -> None:
        """Emit a pitstop event, plus a swap event if the driver changed.

        The pitstop event itself carries no member fields (the API rejects
        `teamMemberId` on pitstop events). When `new_driver` differs from
        `prev_driver` and both resolve, a follow-up `driver_started` event
        with `swapFromMemberId` is sent so the server records the
        stop+start atomically (mirrors the UI swap flow). `started_meta`
        attaches to that swap event so the new driver's stint is tagged
        with the same track/vehicle context as a regular driver_started.
        """
        body: dict[str, Any] = {
            "type": "pitstop",
            "occurredAt": _now_iso(),
        }
        if et_seconds is not None:
            body["etSeconds"] = et_seconds
        if meta:
            body["meta"] = meta
        self._post_event(body)

        if not (new_driver and prev_driver and new_driver != prev_driver):
            return

        from_id = self._resolve(prev_driver)
        to_id = self._resolve(new_driver)
        if from_id and to_id:
            swap_body: dict[str, Any] = {
                "type": "driver_started",
                "occurredAt": _now_iso(),
                "teamMemberId": to_id,
                "swapFromMemberId": from_id,
            }
            if et_seconds is not None:
                swap_body["etSeconds"] = et_seconds
            if started_meta:
                swap_body["meta"] = started_meta
            self._post_event(swap_body)
        else:
            logger.warning(
                "Pit driver swap %r -> %r could not be fully resolved "
                "(from=%s, to=%s); skipping swap event",
                prev_driver, new_driver, from_id, to_id,
            )
