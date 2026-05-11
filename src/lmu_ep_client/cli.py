from __future__ import annotations

import argparse
import logging
from pathlib import Path

from lmu_ep_client.api_client import DEFAULT_API_URL, ApiError, TrackingClient
from lmu_ep_client.poller import _decode, run
from pyLMUSharedMemory import lmu_data


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
        help="Bearer API key for the tracking API. If omitted, only local JSON files are written.",
    )
    parser.add_argument(
        "--registration-id",
        metavar="UUID",
        type=str,
        default=None,
        help="Registration ID to track events against (see --list-registrations)",
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

    if args.list_registrations:
        if not args.api_key:
            parser.error("--list-registrations requires --api-key")
        _list_registrations(TrackingClient(api_url=args.api_url, api_key=args.api_key))
        return

    if args.api_key and not args.registration_id:
        parser.error("--api-key requires --registration-id (use --list-registrations to find one)")
    if args.registration_id and not args.api_key:
        parser.error("--registration-id requires --api-key")

    run(
        output_dir=args.output_dir,
        team_name=args.team,
        driver_name=args.driver,
        slot_id=args.slot,
        api_url=args.api_url,
        api_key=args.api_key,
        registration_id=args.registration_id,
    )


if __name__ == "__main__":
    main()
