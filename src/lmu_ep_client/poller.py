from __future__ import annotations

import logging
import time
from pathlib import Path

from pyLMUSharedMemory import lmu_data

from lmu_ep_client.detector import StintDetector, TickData
from lmu_ep_client.writer import flush_session

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0
FLUSH_INTERVAL = 30.0
WAIT_RETRY_INTERVAL = 10.0


def _read_tick(info: lmu_data.SimInfo) -> TickData | None:
    try:
        scoring_info = info.LMUData.scoring.scoringInfo
        player_idx = info.LMUData.telemetry.playerVehicleIdx

        veh_scoring = info.LMUData.scoring.vehScoringInfo[player_idx]
        veh_telem = info.LMUData.telemetry.telemInfo[player_idx]

        wheels = []
        for i in range(4):
            w = veh_telem.mWheels[i]
            wheels.append({
                "wear": w.mWear,
                "compound_type": w.mCompoundType,
                "flat": bool(w.mFlat),
                "detached": bool(w.mDetached),
            })

        dent_severity = [veh_telem.mDentSeverity[i] for i in range(8)]

        return TickData(
            game_phase=scoring_info.mGamePhase,
            session_type=scoring_info.mSession,
            track=scoring_info.mTrackName.decode().rstrip("\x00"),
            elapsed=scoring_info.mCurrentET,
            driver=veh_scoring.mDriverName.decode().rstrip("\x00"),
            vehicle=veh_scoring.mVehicleName.decode().rstrip("\x00"),
            vehicle_model=veh_telem.mVehicleModel.decode().rstrip("\x00"),
            vehicle_class=veh_scoring.mVehicleClass.decode().rstrip("\x00"),
            pit_state=veh_scoring.mPitState,
            total_laps=veh_scoring.mTotalLaps,
            fuel=veh_telem.mFuel,
            fuel_capacity=veh_telem.mFuelCapacity,
            virtual_energy=veh_telem.mVirtualEnergy,
            wheels=wheels,
            dent_severity=dent_severity,
        )
    except Exception as e:
        logger.warning("Failed to read shared memory: %s", e, exc_info=True)
        return None


def _log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


def run(output_dir: Path | None = None, stop_event=None) -> None:
    _log("Waiting for LMU session...")

    info: lmu_data.SimInfo | None = None
    detector = StintDetector()
    last_flush = 0.0
    last_tick: TickData | None = None
    file_path: Path | None = None

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

            tick = _read_tick(info)
            if tick is None:
                time.sleep(POLL_INTERVAL)
                continue

            last_tick = tick

            # Log raw state every tick for debugging
            if last_tick and (
                tick.pit_state != (detector._prev_pit_state)
                or tick.game_phase != getattr(detector, '_prev_game_phase', None)
            ):
                _log(f"[DEBUG] phase={tick.game_phase} pit={tick.pit_state} "
                     f"laps={tick.total_laps} fuel={tick.fuel:.1f} "
                     f"energy={tick.virtual_energy:.1f} driver={tick.driver} "
                     f"vehicle_model='{tick.vehicle_model}'")
            detector._prev_game_phase = tick.game_phase

            events = detector.update(tick)

            if "session_start" in events:
                _log(f"Session detected: {detector.session.track} — {detector.session.session_type}")
                _log(f"Vehicle: {tick.vehicle_model or tick.vehicle} ({tick.vehicle_class})")
                _log(f"Stint 1 started — Driver: {tick.driver}")

            if "pit_enter" in events:
                _log("Pit entry detected")

            if "pit_exit" in events:
                stint = detector.stints[-1]
                pit = stint.pit_stop
                pit_dict = pit.to_dict()
                msg = f"Pit exit — standing time: {pit_dict['standing_time_seconds']}s"
                msg += f" | +{pit.fuel_added_litres}L fuel"
                msg += f" | +{pit.energy_added_percent}% energy"
                if pit.driver_change:
                    msg += f" | Driver change: {pit.new_driver}"
                _log(msg)

                next_stint_num = len(detector.stints) + 1
                _log(f"Stint {next_stint_num} started — Driver: {tick.driver}")

                # Flush on stint completion
                if detector.session:
                    file_path = flush_session(detector.session, detector.stints, output_dir)
                    last_flush = time.monotonic()

            if "session_end" in events:
                if detector.session:
                    file_path = flush_session(detector.session, detector.stints, output_dir)
                    _log(f"Session ended. Saved: {file_path}")
                # Reset for next session
                detector = StintDetector()
                last_flush = 0.0
                file_path = None

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
