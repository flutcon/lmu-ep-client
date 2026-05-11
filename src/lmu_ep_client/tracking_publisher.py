from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lmu_ep_client.api_client import ApiError, TrackingClient
from lmu_ep_client.session_context import SessionContext

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TrackingPublisher:
    """Maps detector events to tracking API calls.

    All public methods log + swallow ApiError so a transient network failure
    can't take down the polling loop. Local JSON output is the source of
    truth; the API is best-effort mirroring.
    """

    def __init__(self, api: TrackingClient, ctx: SessionContext) -> None:
        self._api = api
        self._ctx = ctx

    @property
    def registration_id(self) -> str:
        return self._ctx.registration_id

    @staticmethod
    def now_iso() -> str:
        return _now_iso()

    def _post_event(self, body: dict[str, Any]) -> None:
        path = f"/api/tracking/registrations/{self._ctx.registration_id}/events"
        try:
            self._api.post(path, body=body)
        except ApiError as e:
            logger.warning("Failed to post %s event: %s", body.get("type"), e)

    def _post_phase(self, event_type: str, occurred_at: str | None) -> None:
        self._post_event({"type": event_type, "occurredAt": occurred_at or _now_iso()})

    def pit_entered(self, occurred_at: str | None = None) -> None:
        self._post_phase("pit_entered", occurred_at)

    def pit_at_box(self, occurred_at: str | None = None) -> None:
        self._post_phase("pit_at_box", occurred_at)

    def pit_departed(self, occurred_at: str | None = None) -> None:
        self._post_phase("pit_departed", occurred_at)

    def pit_exited(self, occurred_at: str | None = None) -> None:
        self._post_phase("pit_exited", occurred_at)

    def _resolve(self, lmu_driver_name: str | None) -> str | None:
        if not lmu_driver_name:
            return None
        member_id = self._ctx.resolve_driver(lmu_driver_name, api=self._api)
        if member_id is None:
            logger.warning(
                "Driver %r not in roster (lmuDriverName unset on team member?) — "
                "sending event without teamMemberId",
                lmu_driver_name,
            )
        return member_id

    def driver_started(
        self, lmu_driver_name: str, meta: dict[str, Any] | None = None
    ) -> None:
        body: dict[str, Any] = {
            "type": "driver_started",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        if meta:
            body["meta"] = meta
        self._post_event(body)

    def driver_stopped(
        self, lmu_driver_name: str, meta: dict[str, Any] | None = None
    ) -> None:
        body: dict[str, Any] = {
            "type": "driver_stopped",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        if meta:
            body["meta"] = meta
        self._post_event(body)

    def pitstop(
        self,
        prev_driver: str | None,
        new_driver: str | None,
        meta: dict[str, Any] | None = None,
        started_meta: dict[str, Any] | None = None,
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
            if started_meta:
                swap_body["meta"] = started_meta
            self._post_event(swap_body)
        else:
            logger.warning(
                "Pit driver swap %r -> %r could not be fully resolved "
                "(from=%s, to=%s); skipping swap event",
                prev_driver, new_driver, from_id, to_id,
            )
