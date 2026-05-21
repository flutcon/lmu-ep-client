from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyLMUSharedMemory import lmu_data

from lmu_ep_client.api_client import DEFAULT_API_URL, ApiError, TrackingClient
from lmu_ep_client.detector import CONTROL_REMOTE, WHEEL_POSITIONS, StintDetector, TickData
from lmu_ep_client.session_context import fetch_practice_session_context, fetch_session_context
from lmu_ep_client.tracking_outbox import TrackingOutbox, default_outbox_path
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


def _live_pit_snapshot_meta(tick: TickData) -> dict[str, Any] | None:
    if tick.control == CONTROL_REMOTE:
        return None
    return {
        "fuel_litres": round(tick.fuel, 2),
        "energy_percent": round(tick.virtual_energy, 2),
        "tyre_wear": {
            pos: round(tick.wheels[i]["wear"], 4)
            for i, pos in enumerate(WHEEL_POSITIONS)
        },
    }


def _practice_lap_payload(tick: TickData) -> dict[str, Any] | None:
    if tick.control == CONTROL_REMOTE or tick.last_lap_time <= 0:
        return None
    return {
        "lap_time_seconds": round(tick.last_lap_time, 3),
        "tyre_wear": {
            "fl": round(tick.wheels[0]["wear"] * 100.0, 2),
            "fr": round(tick.wheels[1]["wear"] * 100.0, 2),
            "rl": round(tick.wheels[2]["wear"] * 100.0, 2),
            "rr": round(tick.wheels[3]["wear"] * 100.0, 2),
        },
        "energy_pct": round(tick.virtual_energy, 2),
        "fuel_litres": round(tick.fuel, 2),
    }


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
            last_lap_time=veh_scoring.mLastLapTime,
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


class SharedMemoryReader:
    """Owns the LMU shared-memory connection and tick extraction."""

    def __init__(
        self,
        sim_info_factory: Callable[[], lmu_data.SimInfo] = lmu_data.SimInfo,
    ) -> None:
        self._sim_info_factory = sim_info_factory
        self.info: lmu_data.SimInfo | None = None

    def connect(self) -> bool:
        if self.info is not None:
            return True
        try:
            self.info = self._sim_info_factory()
        except Exception:
            return False
        return True

    def read_tick(self, player_id: int) -> TickData | None:
        if self.info is None:
            return None
        return _read_tick(self.info, player_id)

    def close(self) -> None:
        if self.info is None:
            return
        self.info.close()
        self.info = None


class PlayerSelector:
    """Finds and latches the car slot the client should track."""

    def __init__(
        self,
        team_name: str | None = None,
        driver_name: str | None = None,
        slot_id: int | None = None,
    ) -> None:
        self.team_name = team_name
        self.driver_name = driver_name
        self.slot_id = slot_id

    def select(self, info: lmu_data.SimInfo) -> int | None:
        return _find_player_id(info, self.team_name, self.driver_name, self.slot_id)

    def waiting_message(self) -> str | None:
        if self.slot_id is not None:
            return f"Waiting for slot ID {self.slot_id} to appear in session..."
        if self.team_name:
            return f"Waiting for team '{self.team_name}' to appear in session..."
        if self.driver_name:
            return f"Waiting for driver '{self.driver_name}' to appear in session..."
        return None


def _pit_exit_details(detector: StintDetector, tick: TickData) -> tuple[Any, Any, dict[str, Any], str]:
    stint = detector.stints[-1]
    pit = stint.pit_stop
    pit_dict = pit.to_dict()
    pit_dict["laps_driven"] = stint.end_lap - stint.start_lap
    msg = f"Pit exit - standing time: {pit_dict['standing_time_seconds']}s"
    msg += f" | +{pit.fuel_added_litres}L fuel"
    msg += f" | +{pit.energy_added_percent}% energy"
    if pit.driver_change:
        msg += f" | Driver change: {pit.new_driver}"
    return stint, pit, pit_dict, msg


class JsonSink:
    """Persists detected session/stint data to local JSON files."""

    def __init__(
        self,
        output_dir: Path | None = None,
        flush_session_func: Callable[..., Path] = flush_session,
        monotonic: Callable[[], float] = time.monotonic,
        flush_interval: float = FLUSH_INTERVAL,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self._flush_session = flush_session_func
        self._monotonic = monotonic
        self._flush_interval = flush_interval
        self._log = log or (lambda msg: None)
        self.last_flush = 0.0
        self.file_path: Path | None = None
        self._prev_finish_status = 0

    def _flush(self, detector: StintDetector) -> Path | None:
        if detector.session is None:
            return None
        self.file_path = self._flush_session(detector.session, detector.stints, self.output_dir)
        self.last_flush = self._monotonic()
        return self.file_path

    def on_events(self, events: set[str], tick: TickData, detector: StintDetector) -> None:
        if "pit_exit" in events:
            self._flush(detector)

        if self._prev_finish_status == 0 and tick.finish_status != 0 and detector.session:
            path = self._flush(detector)
            self._log(f"Race finished - data saved: {path}")
        self._prev_finish_status = tick.finish_status

        if "session_end" in events:
            path = self._flush(detector)
            self._log(f"Session ended. Saved: {path}")
            self.last_flush = 0.0
            self.file_path = None
            self._prev_finish_status = 0

    def periodic(self, detector: StintDetector) -> None:
        now = self._monotonic()
        if detector.session and (now - self.last_flush) >= self._flush_interval:
            self.file_path = self._flush_session(detector.session, detector.stints, self.output_dir)
            self.last_flush = now

    def on_shutdown(self, detector: StintDetector, last_tick: TickData | None) -> None:
        if detector.session:
            path = self._flush(detector)
            self._log(f"Final save: {path}")


class TrackingApiSink:
    """Publishes detector events to the remote tracking API."""

    def __init__(self, publisher: TrackingPublisher) -> None:
        self._publisher = publisher
        self._pit_entered_at: str | None = None

    def on_events(self, events: set[str], tick: TickData, detector: StintDetector) -> None:
        if "session_start" in events:
            self._publisher.driver_started(tick.driver, meta=_started_meta(tick))

        if "lap_completed" in events and self._publisher.is_practice:
            payload = _practice_lap_payload(tick)
            if payload is not None:
                self._publisher.lap_completed(
                    **payload,
                    team_member_id=self._publisher.resolve_driver(tick.driver),
                )

        if "pit_enter" in events:
            self._pit_entered_at = self._publisher.now_iso()

        if "pit_at_box" in events:
            if self._pit_entered_at:
                self._publisher.pit_entered(occurred_at=self._pit_entered_at)
                self._pit_entered_at = None
            self._publisher.pit_at_box(meta=_live_pit_snapshot_meta(tick))

        if "pit_departed" in events:
            self._publisher.pit_departed(meta=_live_pit_snapshot_meta(tick))

        if "pit_exit" in events:
            stint, _pit, pit_dict, _msg = _pit_exit_details(detector, tick)
            self._publisher.pit_exited()
            self._publisher.pitstop(
                prev_driver=stint.driver,
                new_driver=tick.driver,
                meta=pit_dict,
                started_meta=_started_meta(tick),
            )
            self._pit_entered_at = None

        if "session_end" in events:
            if tick.driver:
                self._publisher.driver_stopped(tick.driver, meta=_stopped_meta(tick))
            self._publisher.end_session()
            self._pit_entered_at = None

    def periodic(self, detector: StintDetector) -> None:
        self._publisher.flush_pending()

    def on_shutdown(self, detector: StintDetector, last_tick: TickData | None) -> None:
        if detector.session:
            self._publisher.end_session()
        self._publisher.flush_pending(force=True)


class SessionRunner:
    """Coordinates one poll loop using injected readers, sinks, and timing."""

    def __init__(
        self,
        reader: SharedMemoryReader,
        selector: PlayerSelector,
        sinks: list[Any],
        detector: StintDetector | None = None,
        poll_interval: float = POLL_INTERVAL,
        wait_retry_interval: float = WAIT_RETRY_INTERVAL,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = _log,
    ) -> None:
        self.reader = reader
        self.selector = selector
        self.sinks = sinks
        self.detector = detector or StintDetector()
        self.poll_interval = poll_interval
        self.wait_retry_interval = wait_retry_interval
        self.sleep = sleep
        self.log = log
        self.player_id: int | None = None
        self.last_tick: TickData | None = None

    def step(self) -> float | None:
        if not self.reader.connect():
            self.log("LMU not detected. Retrying...")
            return self.wait_retry_interval

        if self.player_id is None:
            try:
                self.player_id = self.selector.select(getattr(self.reader, "info", None))
            except AmbiguousMatchError as e:
                self.log(str(e))
                return None

            if self.player_id is None:
                message = self.selector.waiting_message()
                if message:
                    self.log(message)
                return self.poll_interval

            self.log(f"Player car identified (slot ID {self.player_id})")

        tick = self.reader.read_tick(self.player_id)
        if tick is None:
            return self.poll_interval

        self.last_tick = tick
        events = self.detector.update(tick)
        self._log_events(events, tick)

        for sink in self.sinks:
            sink.on_events(events, tick, self.detector)
        for sink in self.sinks:
            sink.periodic(self.detector)

        if "session_end" in events:
            self.detector = StintDetector()
            self.player_id = None

        return self.poll_interval

    def run(self, stop_event=None) -> None:
        try:
            while True:
                if stop_event and stop_event.is_set():
                    break

                delay = self.step()
                if delay is None:
                    break
                self.sleep(delay)

        except KeyboardInterrupt:
            pass
        except Exception:
            logger.exception("Unexpected error in polling loop")
        finally:
            self.log("Shutting down...")
            if self.detector.session:
                self.detector.finalize_on_shutdown(self.last_tick)
            for sink in self.sinks:
                sink.on_shutdown(self.detector, self.last_tick)
            self.reader.close()

    def _log_events(self, events: set[str], tick: TickData) -> None:
        if "session_start" in events and self.detector.session:
            self.log(f"Session detected: {self.detector.session.track} - {self.detector.session.session_type}")
            self.log(f"Vehicle: {tick.vehicle_model or tick.vehicle} ({tick.vehicle_class})")
            if "mid_stint_join" in events:
                self.log(
                    f"Joined mid-stint - Driver: {tick.driver} ({tick.team}) "
                    "(partial stint data from this point)"
                )
            else:
                self.log(f"Stint 1 started - Driver: {tick.driver} ({tick.team})")

        if "pit_enter" in events:
            self.log("Pit entry detected")

        if "pit_at_box" in events:
            self.log("Pit at box")

        if "pit_departed" in events:
            self.log("Pit service complete")

        if "pit_exit" in events:
            _stint, _pit, _pit_dict, msg = _pit_exit_details(self.detector, tick)
            self.log(msg)
            next_stint_num = len(self.detector.stints) + 1
            self.log(f"Stint {next_stint_num} started - Driver: {tick.driver} ({tick.team})")


def _create_tracking_sink(
    output_dir: Path | None,
    api_url: str | None,
    api_key: str | None,
    registration_id: str | None,
    practice_team_member_id: str | None,
    log: Callable[[str], None],
) -> TrackingApiSink | None:
    if not api_key:
        return None

    api = TrackingClient(api_url=api_url or DEFAULT_API_URL, api_key=api_key)
    log(f"Tracking API: {api.base_url}")
    if not registration_id:
        return None

    try:
        if practice_team_member_id:
            session_ctx = fetch_practice_session_context(api, registration_id, practice_team_member_id)
        else:
            session_ctx = fetch_session_context(api, registration_id)
    except ApiError as e:
        log(f"Failed to initialize tracking session: {e}")
        return None

    outbox = TrackingOutbox(default_outbox_path(output_dir))
    publisher = TrackingPublisher(api, session_ctx, outbox=outbox)
    roster_size = len(session_ctx.driver_to_member_id)
    log(
        f"Tracking session ready (registration={registration_id}, "
        f"session={session_ctx.session_id}, roster={roster_size} drivers)"
    )
    replayed = publisher.flush_pending(force=True)
    if replayed:
        log(f"Replayed {replayed} queued tracking event(s)")
    if roster_size:
        names = ", ".join(sorted(session_ctx.driver_to_member_id))
        log(f"Recognized drivers: {names}")
    return TrackingApiSink(publisher)


def run(
    output_dir: Path | None = None,
    stop_event=None,
    team_name: str | None = None,
    driver_name: str | None = None,
    slot_id: int | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    registration_id: str | None = None,
    practice_team_member_id: str | None = None,
    reader: SharedMemoryReader | None = None,
    selector: PlayerSelector | None = None,
    sinks: list[Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = _log,
) -> None:
    if sinks is None:
        sinks = [JsonSink(output_dir=output_dir, monotonic=monotonic, log=log)]
        tracking_sink = _create_tracking_sink(
            output_dir,
            api_url,
            api_key,
            registration_id,
            practice_team_member_id,
            log,
        )
        if api_key and registration_id and tracking_sink is None:
            return
        if tracking_sink is not None:
            sinks.append(tracking_sink)

    log("Waiting for LMU session...")

    runner = SessionRunner(
        reader=reader or SharedMemoryReader(),
        selector=selector or PlayerSelector(team_name=team_name, driver_name=driver_name, slot_id=slot_id),
        sinks=sinks,
        sleep=sleep,
        log=log,
    )
    runner.run(stop_event=stop_event)
