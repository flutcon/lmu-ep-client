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

    def _post_event(self, body: dict[str, Any]) -> None:
        path = f"/api/tracking/registrations/{self._ctx.registration_id}/events"
        try:
            self._api.post(path, body=body)
        except ApiError as e:
            logger.warning("Failed to post %s event: %s", body.get("type"), e)

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

    def driver_started(self, lmu_driver_name: str) -> None:
        body: dict[str, Any] = {
            "type": "driver_started",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        self._post_event(body)

    def driver_stopped(self, lmu_driver_name: str) -> None:
        body: dict[str, Any] = {
            "type": "driver_stopped",
            "occurredAt": _now_iso(),
            "teamMemberId": self._resolve(lmu_driver_name),
        }
        self._post_event(body)

    def pitstop(
        self,
        prev_driver: str | None,
        new_driver: str | None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Emit a pitstop event.

        If `new_driver` differs from `prev_driver`, sends `swapFromMemberId`
        + `teamMemberId` so the server records the swap atomically.
        """
        body: dict[str, Any] = {
            "type": "pitstop",
            "occurredAt": _now_iso(),
        }
        if meta:
            body["meta"] = meta

        if new_driver and prev_driver and new_driver != prev_driver:
            from_id = self._resolve(prev_driver)
            to_id = self._resolve(new_driver)
            if from_id and to_id:
                body["swapFromMemberId"] = from_id
                body["teamMemberId"] = to_id
            else:
                logger.warning(
                    "Pit driver swap %r -> %r could not be fully resolved "
                    "(from=%s, to=%s); sending pitstop without swap",
                    prev_driver, new_driver, from_id, to_id,
                )

        self._post_event(body)
