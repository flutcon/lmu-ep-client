from __future__ import annotations

import logging
import math
import time
from pathlib import Path

from pyLMUSharedMemory import lmu_data

from lmu_ep_client.api_client import DEFAULT_API_URL, ApiError, TrackingClient
from lmu_ep_client.detector import StintDetector, TickData
from lmu_ep_client.session_context import SessionContext, fetch_session_context
from lmu_ep_client.tracking_publisher import TrackingPublisher
from lmu_ep_client.writer import flush_session

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0
FLUSH_INTERVAL = 30.0
WAIT_RETRY_INTERVAL = 10.0

# mFinishStatus values (vendor/pyLMUSharedMemory/lmu_data.py LMUFinishStatus enum):
# 0=None, 1=Finished, 2=DNF, 3=DQ. 0 is omitted (session ended without a result).
FINISH_STATUS_NAMES = {1: "finished", 2: "dnf", 3: "dq"}


class AmbiguousMatchError(Exception):
    """Raised when --team matches more than one car. The user must disambiguate
    with --slot since silently picking one would log the wrong stint data."""


def _decode(b) -> str:
    """Tolerantly decode a null-terminated LMU shared-memory string field.

    Player-supplied driver/team names may contain bytes that aren't valid
    UTF-8 (e.g. locale-encoded chars from a non-UTF-8 client). Replace rather
    than raise — losing one glyph is better than killing the poll loop on a
    bad nickname elsewhere in the field.
    """
    return b.decode("utf-8", errors="replace").rstrip("\x00")


def _started_meta(tick: TickData) -> dict:
    return {
        "track": tick.track,
        "vehicle": tick.vehicle_model or tick.vehicle,
        "vehicle_class": tick.vehicle_class,
    }


def _stopped_meta(tick: TickData) -> dict:
    finish = FINISH_STATUS_NAMES.get(tick.finish_status)
    return {"finish_status": finish} if finish else {}


def _find_player_id(info: lmu_data.SimInfo, team_name: str | None, driver_name: str | None, slot_id: int | None) -> int | None:
    """Return the slot ID of the player's car, or None if not yet found.

    Strategy (in order):
    1. slot_id: exact slot ID — most reliable, found via --list-teams.
    2. team_name: substring match against mVehicleName — stable across driver swaps.
    3. driver_name: match by mDriverName — works when you know who is currently driving.
    4. mIsPlayer flag — only true when actively driving; works for solo use.
    """
    scoring_info = info.LMUData.scoring.scoringInfo
    num_vehicles = scoring_info.mNumVehicles
    vehicles = [info.LMUData.scoring.vehScoringInfo[i] for i in range(num_vehicles)]

    if slot_id is not None:
        entry = next((v for v in vehicles if v.mID == slot_id), None)
    elif team_name:
        # Substring match against mVehicleName — the entry/team name is
        # embedded there (e.g. "BMW GT3 Custom Team 2025 #397") and stays
        # constant regardless of who is currently driving.
        needle = team_name.lower()
        matches = [v for v in vehicles if needle in _decode(v.mVehicleName).lower()]
        if len(matches) > 1:
            listing = "\n".join(
                f"  slot {v.mID}: {_decode(v.mVehicleName)}" for v in matches
            )
            raise AmbiguousMatchError(
                f"--team {team_name!r} matched {len(matches)} cars:\n{listing}\n"
                "Use --slot <ID> to pick one."
            )
        entry = matches[0] if matches else None
    elif driver_name:
        entry = next((v for v in vehicles if _decode(v.mDriverName) == driver_name), None)
    else:
        entry = next((v for v in vehicles if v.mIsPlayer), None)

    return entry.mID if entry is not None else None


def _read_tick(info: lmu_data.SimInfo, player_id: int) -> TickData | None:
    try:
        scoring_info = info.LMUData.scoring.scoringInfo
        num_vehicles = scoring_info.mNumVehicles

        # Use the latched slot ID to find the team car regardless of who is driving
        veh_scoring = next(
            (info.LMUData.scoring.vehScoringInfo[i] for i in range(num_vehicles)
             if info.LMUData.scoring.vehScoringInfo[i].mID == player_id),
            None,
        )
        if veh_scoring is None:
            return None

        veh_telem = next(
            (info.LMUData.telemetry.telemInfo[i] for i in range(num_vehicles)
             if info.LMUData.telemetry.telemInfo[i].mID == player_id),
            None,
        )
        if veh_telem is None:
            return None

        wheels = []
        for i in range(4):
            w = veh_telem.mWheels[i]
            wheels.append({
                "wear": w.mWear,
                "compound_index": w.mCompoundIndex,
                "compound_type": w.mCompoundType,
                "flat": bool(w.mFlat),
                "detached": bool(w.mDetached),
            })

        dent_severity = [veh_telem.mDentSeverity[i] for i in range(8)]

        v = veh_telem.mLocalVel
        speed = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)

        # mFuel (telemetry, litres) is precise but frozen for remote-controlled
        # cars — LMU stops writing to that slot when a teammate drives. The
        # networked fallback is mFuelFraction (scoring, uint8 0-255 = 0-100%);
        # the in-game HUD uses it. Resolution is ~0.4% of capacity (~0.5L on a
        # 120L tank) but it actually updates.
        control = veh_scoring.mControl
        fuel_capacity = veh_telem.mFuelCapacity
        fuel_fraction = veh_scoring.mFuelFraction
        if control == 2 and fuel_capacity > 0:
            fuel = (fuel_fraction / 255.0) * fuel_capacity
        else:
            fuel = veh_telem.mFuel

        return TickData(
            game_phase=scoring_info.mGamePhase,
            session_type=scoring_info.mSession,
            track=_decode(scoring_info.mTrackName),
            elapsed=scoring_info.mCurrentET,
            driver=_decode(veh_scoring.mDriverName),
            vehicle=_decode(veh_scoring.mVehicleName),
            vehicle_model=_decode(veh_telem.mVehicleModel),
            vehicle_class=_decode(veh_scoring.mVehicleClass),
            pit_state=veh_scoring.mPitState,
            total_laps=veh_scoring.mTotalLaps,
            fuel=fuel,
            fuel_capacity=fuel_capacity,
            virtual_energy=veh_telem.mVirtualEnergy * 100.0,
            wheels=wheels,
            dent_severity=dent_severity,
            finish_status=veh_scoring.mFinishStatus,
            speed=speed,
            team=_decode(veh_scoring.mPitGroup),
            control=control,
        )
    except Exception as e:
        logger.warning("Failed to read shared memory: %s", e, exc_info=True)
        return None


def _log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


def run(
    output_dir: Path | None = None,
    stop_event=None,
    team_name: str | None = None,
    driver_name: str | None = None,
    slot_id: int | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    registration_id: str | None = None,
) -> None:
    api: TrackingClient | None = None
    session_ctx: SessionContext | None = None
    publisher: TrackingPublisher | None = None
    if api_key:
        api = TrackingClient(api_url=api_url or DEFAULT_API_URL, api_key=api_key)
        _log(f"Tracking API: {api.base_url}")
        if registration_id:
            try:
                session_ctx = fetch_session_context(api, registration_id)
            except ApiError as e:
                _log(f"Failed to initialize tracking session: {e}")
                return
            publisher = TrackingPublisher(api, session_ctx)
            roster_size = len(session_ctx.driver_to_member_id)
            _log(
                f"Tracking session ready (registration={registration_id}, "
                f"session={session_ctx.session_id}, roster={roster_size} drivers)"
            )
            if roster_size:
                names = ", ".join(sorted(session_ctx.driver_to_member_id))
                _log(f"Recognized drivers: {names}")

    _log("Waiting for LMU session...")

    info: lmu_data.SimInfo | None = None
    player_id: int | None = None
    detector = StintDetector()
    last_flush = 0.0
    last_tick: TickData | None = None
    file_path: Path | None = None
    _prev_finish_status: int = 0
    # Wall-clock captured when the car crosses the pit-lane line. We defer the
    # `pit_entered` API call until `pit_at_box` confirms a real stop (so drive-
    # throughs never reach the server), then backdate occurredAt with this.
    pit_entered_at: str | None = None

    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            # Connect to shared memory
            if info is None:
                try:
                    info = lmu_data.SimInfo()
                except Exception:
                    _log("LMU not detected. Retrying...")
                    time.sleep(WAIT_RETRY_INTERVAL)
                    continue

            # Latch the player's car slot ID once, then track by ID for the full
            # session — covers spectating between stints in team races.
            if player_id is None:
                try:
                    player_id = _find_player_id(info, team_name, driver_name, slot_id)
                except AmbiguousMatchError as e:
                    _log(str(e))
                    return
                if player_id is None:
                    if slot_id is not None:
                        _log(f"Waiting for slot ID {slot_id} to appear in session...")
                    elif team_name:
                        _log(f"Waiting for team '{team_name}' to appear in session...")
                    elif driver_name:
                        _log(f"Waiting for driver '{driver_name}' to appear in session...")
                    time.sleep(POLL_INTERVAL)
                    continue
                _log(f"Player car identified (slot ID {player_id})")

            tick = _read_tick(info, player_id)
            if tick is None:
                time.sleep(POLL_INTERVAL)
                continue

            last_tick = tick

            events = detector.update(tick)

            if "session_start" in events:
                _log(f"Session detected: {detector.session.track} — {detector.session.session_type}")
                _log(f"Vehicle: {tick.vehicle_model or tick.vehicle} ({tick.vehicle_class})")
                if "mid_stint_join" in events:
                    _log(f"Joined mid-stint — Driver: {tick.driver} ({tick.team}) (partial stint data from this point)")
                else:
                    _log(f"Stint 1 started — Driver: {tick.driver} ({tick.team})")
                if publisher:
                    publisher.driver_started(tick.driver, meta=_started_meta(tick))

            if "pit_enter" in events:
                _log("Pit entry detected")
                if publisher:
                    pit_entered_at = publisher.now_iso()

            if "pit_at_box" in events:
                _log("Pit at box")
                if publisher:
                    if pit_entered_at:
                        publisher.pit_entered(occurred_at=pit_entered_at)
                        pit_entered_at = None
                    publisher.pit_at_box()

            if "pit_departed" in events:
                _log("Pit service complete")
                if publisher:
                    publisher.pit_departed()

            if "pit_exit" in events:
                stint = detector.stints[-1]
                pit = stint.pit_stop
                pit_dict = pit.to_dict()
                pit_dict["laps_driven"] = stint.end_lap - stint.start_lap
                msg = f"Pit exit — standing time: {pit_dict['standing_time_seconds']}s"
                msg += f" | +{pit.fuel_added_litres}L fuel"
                msg += f" | +{pit.energy_added_percent}% energy"
                if pit.driver_change:
                    msg += f" | Driver change: {pit.new_driver}"
                _log(msg)

                next_stint_num = len(detector.stints) + 1
                _log(f"Stint {next_stint_num} started — Driver: {tick.driver} ({tick.team})")

                if publisher:
                    publisher.pit_exited()
                    publisher.pitstop(
                        prev_driver=stint.driver,
                        new_driver=tick.driver,
                        meta=pit_dict,
                        started_meta=_started_meta(tick),
                    )
                pit_entered_at = None

                # Flush on stint completion
                if detector.session:
                    file_path = flush_session(detector.session, detector.stints, output_dir)
                    last_flush = time.monotonic()

            # Flush immediately when the player's race is done (finish/DNF/DQ)
            if _prev_finish_status == 0 and tick.finish_status != 0 and detector.session:
                file_path = flush_session(detector.session, detector.stints, output_dir)
                last_flush = time.monotonic()
                _log(f"Race finished — data saved: {file_path}")
            _prev_finish_status = tick.finish_status

            if "session_end" in events:
                if publisher and tick.driver:
                    publisher.driver_stopped(tick.driver, meta=_stopped_meta(tick))
                if detector.session:
                    file_path = flush_session(detector.session, detector.stints, output_dir)
                    _log(f"Session ended. Saved: {file_path}")
                # Reset for next session
                detector = StintDetector()
                player_id = None
                last_flush = 0.0
                file_path = None
                _prev_finish_status = 0
                pit_entered_at = None

            # Periodic flush
            now = time.monotonic()
            if detector.session and (now - last_flush) >= FLUSH_INTERVAL:
                file_path = flush_session(detector.session, detector.stints, output_dir)
                last_flush = now

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Unexpected error in polling loop")
    finally:
        _log("Shutting down...")
        if detector.session:
            detector.finalize_on_shutdown(last_tick)
            file_path = flush_session(detector.session, detector.stints, output_dir)
            _log(f"Final save: {file_path}")
        if info:
            info.close()
