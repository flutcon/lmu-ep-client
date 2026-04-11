from __future__ import annotations

import argparse
import logging
from pathlib import Path

from lmu_ep_client.poller import run
from pyLMUSharedMemory import lmu_data


def _list_teams() -> None:
    try:
        info = lmu_data.SimInfo()
    except Exception:
        print("LMU is not running or shared memory is not available.")
        return

    try:
        scoring_info = info.LMUData.scoring.scoringInfo
        num_vehicles = scoring_info.mNumVehicles

        if num_vehicles == 0:
            print("No active session found.")
            return

        track = scoring_info.mTrackName.decode().rstrip("\x00")
        print(f"Session: {track}  ({num_vehicles} cars)\n")
        print(f"  {'#':<4} {'Team':<28} {'Driver':<24} {'Class'}")
        print(f"  {'-'*4} {'-'*28} {'-'*24} {'-'*16}")

        for i in range(num_vehicles):
            v = info.LMUData.scoring.vehScoringInfo[i]
            team = v.mPitGroup.decode().rstrip("\x00")
            driver = v.mDriverName.decode().rstrip("\x00")
            cls = v.mVehicleClass.decode().rstrip("\x00")
            place = v.mPlace
            marker = " *" if v.mIsPlayer else ""
            print(f"  {place:<4} {team:<28} {driver:<24} {cls}{marker}")

        print("\n  * = your car")
    finally:
        info.close()


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
        help="Team name as shown in-game (required for team races to track the correct car)",
    )
    parser.add_argument(
        "--list-teams",
        action="store_true",
        help="List all teams and drivers in the current session and exit",
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

    run(output_dir=args.output_dir, team_name=args.team)


if __name__ == "__main__":
    main()
