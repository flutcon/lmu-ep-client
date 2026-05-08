from __future__ import annotations

from dataclasses import dataclass, field

from lmu_ep_client.api_client import TrackingClient


@dataclass
class SessionContext:
    """Per-registration tracking state cached at startup.

    `driver_to_member_id` maps the LMU driver name (`mDriverName` from shared
    memory, also stored server-side as `lmuDriverName`) to the team member
    UUID the API expects as `teamMemberId` in event payloads.
    """

    registration_id: str
    session_id: str
    driver_to_member_id: dict[str, str] = field(default_factory=dict)

    def resolve_driver(self, lmu_driver_name: str) -> str | None:
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
