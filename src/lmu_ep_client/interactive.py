"""Arrow-key prompts for picking a registration, mode, and team member.

Wraps questionary so the rest of the client can stay test-friendly: each
function takes plain dicts in and returns the picked dict (or None on
cancel). All prompts require a TTY — if stdin is redirected the caller
should fall back to flag-driven mode.
"""

from __future__ import annotations

import sys
from typing import Any

import questionary


class InteractiveAbort(Exception):
    """Raised when the user cancels a prompt (Ctrl-C / Esc)."""


def is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _format_registration(reg: dict[str, Any]) -> str:
    starts = reg.get("startsAt") or "no start time"
    track = reg.get("trackKey") or "?"
    layout = reg.get("trackLayoutKey")
    track_str = f"{track}/{layout}" if layout else track
    car = reg.get("carKey") or "?"
    title = reg.get("eventTitle") or ""
    tracking = " [tracking]" if reg.get("hasTrackingSession") else ""
    suffix = f" — {title}" if title else ""
    return f"{starts}  {track_str:<18}  {car:<22}{tracking}{suffix}"


def select_registration(regs: list[dict[str, Any]]) -> dict[str, Any]:
    if not regs:
        raise InteractiveAbort("No registrations found for this team.")

    choices = [
        questionary.Choice(title=_format_registration(r), value=r) for r in regs
    ]
    picked = questionary.select(
        "Pick a registration:",
        choices=choices,
        use_shortcuts=False,
    ).ask()
    if picked is None:
        raise InteractiveAbort("Cancelled.")
    return picked


def select_mode(default_practice: bool = False) -> str:
    """Returns 'race' or 'practice'."""
    choices = [
        questionary.Choice(title="Practice session", value="practice"),
        questionary.Choice(title="Race session", value="race"),
    ]
    if not default_practice:
        choices.reverse()
    picked = questionary.select("Session type:", choices=choices).ask()
    if picked is None:
        raise InteractiveAbort("Cancelled.")
    return picked


def _format_team_member(m: dict[str, Any]) -> str:
    name = m.get("userName") or "?"
    lmu = m.get("lmuDriverName")
    role = m.get("role") or ""
    lmu_str = f"LMU: {lmu}" if lmu else "LMU name not set"
    return f"{name:<24} {role:<8} {lmu_str}"


def select_team_member(members: list[dict[str, Any]]) -> dict[str, Any]:
    if not members:
        raise InteractiveAbort("This registration's team has no members.")

    choices = [
        questionary.Choice(title=_format_team_member(m), value=m) for m in members
    ]
    picked = questionary.select(
        "Pick the driver for this practice session:",
        choices=choices,
    ).ask()
    if picked is None:
        raise InteractiveAbort("Cancelled.")
    return picked
