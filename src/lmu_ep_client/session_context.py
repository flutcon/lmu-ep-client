from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from lmu_ep_client.api_client import ApiError, TrackingClient

logger = logging.getLogger(__name__)

REFRESH_THROTTLE_SECONDS = 30.0


@dataclass
class SessionContext:
    """Per-registration tracking state cached at startup.

    `driver_to_member_id` maps the LMU driver name (`mDriverName` from shared
    memory, also stored server-side as `lmuDriverName`) to the team member
    UUID the API expects as `teamMemberId` in event payloads.
    """

    registration_id: str
    session_id: str
    kind: str = "race"
    practice_session_id: str | None = None
    practice_team_member_id: str | None = None
    driver_to_member_id: dict[str, str] = field(default_factory=dict)
    _last_refresh_attempt: dict[str, float] = field(default_factory=dict)

    def resolve_driver(
        self,
        lmu_driver_name: str,
        api: TrackingClient | None = None,
    ) -> str | None:
        """Look up team member UUID for an LMU driver name.

        On a cache miss with `api` provided, refetch the roster once (throttled
        per-name to avoid hammering the API on a name that's genuinely unknown).
        """
        hit = self.driver_to_member_id.get(lmu_driver_name)
        if hit is not None or api is None:
            return hit

        now = time.monotonic()
        last = self._last_refresh_attempt.get(lmu_driver_name, 0.0)
        if now - last < REFRESH_THROTTLE_SECONDS:
            return None
        self._last_refresh_attempt[lmu_driver_name] = now

        try:
            payload = api.get_session(self.registration_id)
        except ApiError as e:
            logger.warning("Roster refresh failed: %s", e)
            return None

        roster = payload.get("teamMembers") or []
        self.driver_to_member_id = _build_driver_map(roster)
        return self.driver_to_member_id.get(lmu_driver_name)


def _build_driver_map(roster: list[dict]) -> dict[str, str]:
    return {
        m["lmuDriverName"]: m["id"]
        for m in roster
        if m.get("lmuDriverName") and m.get("id")
    }


def fetch_session_context(api: TrackingClient, registration_id: str) -> SessionContext:
    """Ensure a tracking session exists, then fetch it with its roster.

    POST is idempotent — returns existing session if present. GET gives us
    the team-member roster needed to resolve driver names to UUIDs.
    """
    api.create_session(registration_id)
    payload = api.get_session(registration_id)

    roster = payload.get("teamMembers") or []
    return SessionContext(
        registration_id=registration_id,
        session_id=payload["id"],
        driver_to_member_id=_build_driver_map(roster),
    )


def fetch_practice_session_context(
    api: TrackingClient,
    registration_id: str,
    team_member_id: str,
) -> SessionContext:
    practice = api.create_practice_session(registration_id, team_member_id)
    return SessionContext(
        registration_id=registration_id,
        session_id=practice["id"],
        kind="practice",
        practice_session_id=practice["id"],
        practice_team_member_id=team_member_id,
        driver_to_member_id={},
    )
