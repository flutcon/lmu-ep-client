from __future__ import annotations

import argparse
import logging
import os
import sys
import tomllib
from pathlib import Path

from lmu_ep_client.api_client import DEFAULT_API_URL, ApiError, TrackingClient
from lmu_ep_client.interactive import (
    InteractiveAbort,
    is_tty,
    select_mode,
    select_registration,
    select_team_member,
)
from lmu_ep_client.poller import _decode, run
from pyLMUSharedMemory import lmu_data

ENV_API_KEY = "LMU_EP_API_KEY"
CONFIG_FILENAME = "config.toml"


def _default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "lmu-ep-client" / CONFIG_FILENAME


def _config_api_key(config_path: Path) -> str | None:
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValueError(f"Could not read config file {config_path}: {e}") from e

    try:
        config = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid config file {config_path}: {e}") from e

    value = config.get("api_key")
    tracking = config.get("tracking")
    if value is None and isinstance(tracking, dict):
        value = tracking.get("api_key")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Config file {config_path} has a non-string api_key")

    value = value.strip()
    return value or None


def _resolve_api_key(cli_api_key: str | None, config_path: Path | None = None) -> str | None:
    if cli_api_key is not None:
        api_key = cli_api_key.strip()
        if not api_key:
            raise ValueError("--api-key cannot be empty")
        return api_key

    env_api_key = os.environ.get(ENV_API_KEY, "").strip()
    if env_api_key:
        return env_api_key

    return _config_api_key(config_path or _default_config_path())


def _launch_gui() -> None:
    from lmu_ep_client.gui import launch_gui

    launch_gui()


def _print_session_info(info) -> None:
    """Print the session/vehicle table. Kept separate from open/close so its
    ctypes locals (scoring_info, v) fall out of scope before info.close() — the
    mmap refuses to close while any ctypes views into it are still alive.
    """
    scoring_info = info.LMUData.scoring.scoringInfo
    num_vehicles = scoring_info.mNumVehicles

    if num_vehicles == 0:
        print("No active session found.")
        return

    track = _decode(scoring_info.mTrackName)
    print(f"Session: {track}  ({num_vehicles} cars)\n")
    print(f"  {'#':<4} {'ID':<5} {'Driver':<24} {'Vehicle':<36} {'Class'}")
    print(f"  {'-'*4} {'-'*5} {'-'*24} {'-'*36} {'-'*16}")

    for i in range(num_vehicles):
        v = info.LMUData.scoring.vehScoringInfo[i]
        driver = _decode(v.mDriverName)
        vehicle = _decode(v.mVehicleName)
        cls = _decode(v.mVehicleClass)
        place = v.mPlace
        slot_id = v.mID
        marker = " *" if v.mIsPlayer else ""
        print(f"  {place:<4} {slot_id:<5} {driver:<24} {vehicle:<36} {cls}{marker}")

    print("\n  * = your car (only visible when you are driving)")
    print("  Use --driver <name>, --team <name>, or --slot <id> to track a specific car")


def _list_teams() -> None:
    try:
        info = lmu_data.SimInfo()
    except Exception:
        print("LMU is not running or shared memory is not available.")
        return

    try:
        _print_session_info(info)
    finally:
        info.close()


def _list_registrations(api: TrackingClient) -> None:
    try:
        regs = api.list_registrations()
    except ApiError as e:
        print(f"Failed to list registrations: {e}")
        return

    if not regs:
        print("No registrations found for this team.")
        return

    print(f"  {'ID':<38} {'Track':<14} {'Layout':<10} {'Car':<22} {'Starts':<22} Tracking")
    print(f"  {'-'*38} {'-'*14} {'-'*10} {'-'*22} {'-'*22} {'-'*8}")
    for r in regs:
        starts = r.get("startsAt") or "-"
        tracking = "yes" if r.get("hasTrackingSession") else "no"
        layout = r.get("trackLayoutKey") or "-"
        title = r.get("eventTitle") or ""
        print(
            f"  {r['id']:<38} {(r.get('trackKey') or '-'):<14} {layout:<10} "
            f"{(r.get('carKey') or '-'):<22} {starts:<22} {tracking}"
        )
        if title:
            print(f"    {title}")
    print("\n  Use --registration-id <ID> to track events against one of these.")


def main() -> None:
    if len(sys.argv) == 1:
        _launch_gui()
        return

    parser = argparse.ArgumentParser(
        prog="lmu-ep-client",
        description="LMU Endurance Protocol Client — stint activity logger",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        type=Path,
        default=None,
        help="Directory to write session JSON files (default: ./sessions/)",
    )
    parser.add_argument(
        "--team",
        metavar="NAME",
        type=str,
        default=None,
        help="Substring match against vehicle/entry name (e.g. 'Custom Team 2025')",
    )
    parser.add_argument(
        "--driver",
        metavar="NAME",
        type=str,
        default=None,
        help="Your driver name — use when team names show as 'Group99' etc.",
    )
    parser.add_argument(
        "--slot",
        metavar="ID",
        type=int,
        default=None,
        help="Slot ID of the car to track (shown in --list-teams output)",
    )
    parser.add_argument(
        "--list-teams",
        action="store_true",
        help="List all teams and drivers in the current session and exit",
    )
    parser.add_argument(
        "--api-url",
        metavar="URL",
        type=str,
        default=DEFAULT_API_URL,
        help=f"Tracking API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        type=str,
        default=None,
        help=f"Bearer API key for the tracking API. Overrides {ENV_API_KEY} and config.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        type=Path,
        default=None,
        help=f"TOML config file with api_key or [tracking].api_key (default: {_default_config_path()})",
    )
    parser.add_argument(
        "--registration-id",
        metavar="UUID",
        type=str,
        default=None,
        help="Registration ID to track events against (see --list-registrations)",
    )
    parser.add_argument(
        "--practice",
        action="store_true",
        help="Publish events to a pre-event practice session instead of the race session",
    )
    parser.add_argument(
        "--practice-team-member-id",
        metavar="UUID",
        type=str,
        default=None,
        help="Team member ID to pin the practice session to",
    )
    parser.add_argument(
        "--list-registrations",
        action="store_true",
        help="List your team's registrations from the API and exit. Requires --api-key.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    if args.list_teams:
        _list_teams()
        return

    try:
        api_key = _resolve_api_key(args.api_key, args.config)
    except ValueError as e:
        parser.error(str(e))

    if args.list_registrations:
        if not api_key:
            parser.error(f"--list-registrations requires an API key (--api-key, {ENV_API_KEY}, or config)")
        _list_registrations(TrackingClient(api_url=args.api_url, api_key=api_key))
        return

    if args.practice_team_member_id and not args.practice:
        parser.error("--practice-team-member-id requires --practice")
    if args.registration_id and not api_key:
        parser.error(f"--registration-id requires an API key (--api-key, {ENV_API_KEY}, or config)")

    registration_id = args.registration_id
    practice = args.practice
    practice_team_member_id = args.practice_team_member_id

    # Interactive selection is only triggered by EXPLICIT --api-key on the
    # command line. An API key sourced from env or config without
    # --registration-id continues to fall through to file-only logging, as
    # documented in the README — important for scheduled / redirected runs
    # where there is no TTY.
    explicit_api_key = args.api_key is not None
    client: TrackingClient | None = None

    try:
        if explicit_api_key and not registration_id:
            if not is_tty():
                parser.error(
                    "--api-key without --registration-id requires a TTY for interactive selection. "
                    "Pass --registration-id (use --list-registrations to find one)."
                )
            client = TrackingClient(api_url=args.api_url, api_key=api_key)
            try:
                regs = client.list_registrations()
            except ApiError as e:
                parser.error(f"Failed to list registrations: {e}")
            reg = select_registration(regs)
            registration_id = reg["id"]
            print(f"Selected registration: {reg.get('eventTitle') or registration_id}")
            if not args.practice:
                practice = select_mode() == "practice"

        if api_key and registration_id and practice and not practice_team_member_id:
            if not is_tty():
                parser.error(
                    "--practice without --practice-team-member-id requires a TTY for interactive selection."
                )
            if client is None:
                client = TrackingClient(api_url=args.api_url, api_key=api_key)
            try:
                members = client.list_team_members(registration_id)
            except ApiError as e:
                parser.error(f"Failed to list team members: {e}")
            member = select_team_member(members)
            practice_team_member_id = member["id"]
            print(f"Selected driver: {member.get('userName') or practice_team_member_id}")
    except InteractiveAbort as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if practice and not registration_id:
        parser.error("--practice requires --registration-id")
    if practice and not practice_team_member_id:
        parser.error("--practice requires --practice-team-member-id")

    run(
        output_dir=args.output_dir,
        team_name=args.team,
        driver_name=args.driver,
        slot_id=args.slot,
        api_url=args.api_url,
        api_key=api_key if registration_id else None,
        registration_id=registration_id,
        practice_team_member_id=practice_team_member_id if practice else None,
    )


if __name__ == "__main__":
    main()
