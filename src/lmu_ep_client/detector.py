from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from lmu_ep_client.models import (
    EnergyData,
    FuelData,
    PitStop,
    SessionData,
    Stint,
    TireInfo,
    TyreWearData,
)

# Game phase values
PHASE_GARAGE = 0
PHASE_SESSION_OVER = 8

# Pit state values
PIT_NONE = 0
PIT_REQUEST = 1
PIT_ENTERING = 2
PIT_STOPPED = 3
PIT_EXITING = 4
PIT_GARAGE = 5

# Compound type mapping
COMPOUND_NAMES = {0: "Soft", 1: "Medium", 2: "Hard", 3: "Wet"}

# Session type mapping (from LMUSession enum)
SESSION_NAMES = {
    0: "Test Day",
    1: "Practice 1",
    2: "Practice 2",
    3: "Practice 3",
    4: "Practice 4",
    5: "Qualifying 1",
    6: "Qualifying 2",
    7: "Qualifying 3",
    8: "Qualifying 4",
    9: "Warmup",
    10: "Race 1",
    11: "Race 2",
    12: "Race 3",
    13: "Race 4",
}

WHEEL_POSITIONS = ["FL", "FR", "RL", "RR"]

# Any wear increase during a pit stop means tires were swapped
# (tires only lose wear during driving, so any gain = fresh rubber)
TIRE_WEAR_CHANGE_THRESHOLD = 0.001
MOVING_SPEED_THRESHOLD = 1.0  # m/s — above this the car is considered in motion

# mControl values from LMUVehicleScoring (vendor/pyLMUSharedMemory/lmu_data.py:223)
CONTROL_REMOTE = 2
LAP_WRAP_PREV_FRACTION = 0.8
LAP_WRAP_CURR_FRACTION = 0.2


@dataclass
class TickData:
    game_phase: int
    session_type: int
    track: str
    elapsed: float
    driver: str
    vehicle: str
    vehicle_model: str
    vehicle_class: str
    pit_state: int
    total_laps: int
    lap_distance: float
    track_length: float
    last_lap_time: float
    fuel: float
    fuel_capacity: float
    virtual_energy: float
    wheels: list[dict]
    dent_severity: list[int]
    finish_status: int  # 0=none, 1=finished, 2=dnf, 3=dq
    speed: float        # m/s
    team: str
    control: int  # 0=local, 1=AI, 2=remote, 3=replay


@dataclass
class _PrePitSnapshot:
    elapsed: float
    fuel: float
    energy: float
    lap: int
    driver: str
    wheels: list[dict]
    dent_severity: list[int]
    control: int


@dataclass
class _StintStart:
    stint_number: int
    driver: str
    start_lap: int
    start_elapsed: float
    start_fuel: float
    fuel_capacity: float
    start_energy: float
    start_wear: dict[str, float]  # FL/FR/RL/RR -> wear at stint start (1.0=fresh)
    start_control: int


class StintDetector:
    def __init__(self) -> None:
        self.session: SessionData | None = None
        self.stints: list[Stint] = []
        self._current_stint_start: _StintStart | None = None
        self._prev_pit_state: int = PIT_NONE
        self._pre_pit: _PrePitSnapshot | None = None
        self._pit_enter_elapsed: float = 0.0
        self._pit_stand_elapsed: float = 0.0
        self._pit_depart_elapsed: float = 0.0
        self._pit_departed_emitted: bool = False
        self._session_active: bool = False
        self._prev_total_laps: int | None = None
        self._prev_lap_distance: float | None = None

    def update(self, tick: TickData) -> set[str]:
        events: set[str] = set()

        # Session start detection
        if not self._session_active:
            if tick.game_phase not in (PHASE_GARAGE, PHASE_SESSION_OVER) and tick.game_phase > 0:
                self._session_active = True
                self.session = SessionData(
                    track=tick.track,
                    session_type=SESSION_NAMES.get(tick.session_type, f"Unknown ({tick.session_type})"),
                    start_time=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    end_time="",
                    vehicle=tick.vehicle_model or tick.vehicle,
                    vehicle_class=tick.vehicle_class,
                )
                # Only start first stint if car is on track; otherwise wait
                # until the car leaves the pits (practice sessions start in garage)
                if tick.pit_state in (PIT_NONE, PIT_REQUEST):
                    self._start_stint(tick)
                    if tick.speed > MOVING_SPEED_THRESHOLD:
                        events.add("mid_stint_join")
                else:
                    logger.debug("Session started while in pits (pit_state=%d), deferring first stint", tick.pit_state)
                events.add("session_start")
        else:
            if self._lap_completed(tick):
                events.add("lap_completed")

            # Session end detection (SessionOver or return to garage)
            if tick.game_phase in (PHASE_SESSION_OVER, PHASE_GARAGE):
                self._finalize_current_stint(tick)
                if self.session:
                    self.session.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                events.add("session_end")
                self._session_active = False
                self._pre_pit = None
                self._pit_enter_elapsed = 0.0
                self._pit_stand_elapsed = 0.0
                self._pit_depart_elapsed = 0.0
                self._pit_departed_emitted = False
                self._current_stint_start = None
                self._prev_pit_state = tick.pit_state
                self._prev_total_laps = None
                self._prev_lap_distance = None
                return events

            # Pit state transitions
            pit_events = self._check_pit_transitions(tick)
            events.update(pit_events)

        self._prev_pit_state = tick.pit_state
        self._prev_total_laps = tick.total_laps
        self._prev_lap_distance = tick.lap_distance
        return events

    def _lap_completed(self, tick: TickData) -> bool:
        if self._prev_total_laps is not None and tick.total_laps > self._prev_total_laps:
            return True
        if self._prev_lap_distance is None or tick.track_length <= 0:
            return False
        return (
            self._prev_lap_distance > tick.track_length * LAP_WRAP_PREV_FRACTION
            and tick.lap_distance < tick.track_length * LAP_WRAP_CURR_FRACTION
        )

    def _start_stint(self, tick: TickData) -> None:
        self._current_stint_start = _StintStart(
            stint_number=len(self.stints) + 1,
            driver=tick.driver,
            start_lap=tick.total_laps,
            start_elapsed=tick.elapsed,
            start_fuel=tick.fuel,
            fuel_capacity=tick.fuel_capacity,
            start_energy=tick.virtual_energy,
            start_wear={pos: round(tick.wheels[i]["wear"], 4) for i, pos in enumerate(WHEEL_POSITIONS)},
            start_control=tick.control,
        )

    def _check_pit_transitions(self, tick: TickData) -> set[str]:
        events: set[str] = set()
        prev = self._prev_pit_state
        curr = tick.pit_state
        on_track = (PIT_NONE, PIT_REQUEST)

        if prev != curr:
            logger.debug("Pit state: %d -> %d (elapsed=%.1f)", prev, curr, tick.elapsed)

        # Entered pit zone: was on track, now in pit area
        if prev in on_track and curr not in on_track:
            self._pre_pit = _PrePitSnapshot(
                elapsed=tick.elapsed,
                fuel=tick.fuel,
                energy=tick.virtual_energy,
                lap=tick.total_laps,
                driver=tick.driver,
                wheels=[dict(w) for w in tick.wheels],
                dent_severity=list(tick.dent_severity),
                control=tick.control,
            )
            self._pit_enter_elapsed = tick.elapsed
            self._pit_stand_elapsed = 0.0
            self._pit_depart_elapsed = 0.0
            self._pit_departed_emitted = False
            events.add("pit_enter")

        # Reached pit stand — record first time we see STOPPED(3), EXITING(4), or GARAGE(5)
        # after entering the pits. LMU uses different combinations of these at the box.
        # State 4 counts here because LMU sometimes goes 2→4→5→0 (skipping 3).
        just_landed = False
        if not self._pit_stand_elapsed and self._pre_pit and curr in (PIT_STOPPED, PIT_EXITING, PIT_GARAGE):
            self._pit_stand_elapsed = tick.elapsed
            events.add("pit_at_box")
            just_landed = True

        # Track pit box departure — update on every state change while at the box.
        # The last recorded value before leaving gives us when service ended.
        # e.g. in 2→4→5→0: records at 4→5, giving the moment service completed.
        # Emit pit_departed once, on the first such transition (and never on
        # the tick we first landed — that's pit_at_box, not a departure).
        if (
            self._pit_stand_elapsed
            and not just_landed
            and prev != curr
            and curr in (PIT_STOPPED, PIT_EXITING, PIT_GARAGE)
        ):
            if not self._pit_departed_emitted:
                events.add("pit_departed")
                self._pit_departed_emitted = True
            self._pit_depart_elapsed = tick.elapsed

        # Left pit zone: was in pit area (or garage), now back on track
        if prev not in on_track and curr in on_track:
            pit_exit_elapsed = tick.elapsed

            # Drive-through: entered pit lane but never stopped — not a real pit stop
            if self._pre_pit and not self._pit_stand_elapsed:
                logger.debug("Drive-through detected (no stop), continuing stint (elapsed=%.1f)", tick.elapsed)
                self._pre_pit = None
                events.add("pit_lane_exit")
            elif self._pre_pit and self._current_stint_start:
                pre = self._pre_pit
                local_pit_telemetry = pre.control != CONTROL_REMOTE and tick.control != CONTROL_REMOTE

                # Build tire info
                tyres: dict[str, TireInfo] = {}
                if local_pit_telemetry:
                    for i, pos in enumerate(WHEEL_POSITIONS):
                        old_w = pre.wheels[i]
                        new_w = tick.wheels[i]
                        compound_changed = old_w["compound_index"] != new_w["compound_index"]
                        wear_reset = new_w["wear"] > old_w["wear"] + TIRE_WEAR_CHANGE_THRESHOLD
                        changed = compound_changed or wear_reset
                        tyres[pos] = TireInfo(
                            changed=changed,
                            old_wear=round(old_w["wear"], 4),
                            old_compound=COMPOUND_NAMES.get(old_w["compound_type"], "Unknown"),
                            new_compound=COMPOUND_NAMES.get(new_w["compound_type"], "Unknown") if changed else None,
                            new_wear=round(new_w["wear"], 4),
                        )

                # Detect repair
                repair = None
                if local_pit_telemetry:
                    repair = any(
                        tick.dent_severity[j] < pre.dent_severity[j]
                        for j in range(len(pre.dent_severity))
                    )

                # Detect driver change
                driver_changed = tick.driver != pre.driver

                pit_stop = PitStop(
                    pit_enter_elapsed=self._pit_enter_elapsed,
                    pit_stand_elapsed=self._pit_stand_elapsed,
                    pit_depart_elapsed=self._pit_depart_elapsed or self._pit_stand_elapsed,
                    pit_exit_elapsed=pit_exit_elapsed,
                    fuel_added_litres=round(tick.fuel - pre.fuel, 2),
                    energy_added_percent=round(tick.virtual_energy - pre.energy, 2),
                    repair_flag=repair,
                    driver_change=driver_changed,
                    new_driver=tick.driver if driver_changed else None,
                    tyres=tyres,
                    post_fuel_litres=round(tick.fuel, 2),
                    post_energy_percent=round(tick.virtual_energy, 2),
                )

                # Finalize current stint
                cs = self._current_stint_start
                stint = Stint(
                    stint_number=cs.stint_number,
                    driver=cs.driver,
                    start_lap=cs.start_lap,
                    end_lap=pre.lap,
                    start_time_elapsed=cs.start_elapsed,
                    end_time_elapsed=pre.elapsed,
                    fuel=FuelData(
                        start_litres=cs.start_fuel,
                        end_litres=pre.fuel,
                        capacity=cs.fuel_capacity,
                    ),
                    energy=EnergyData(
                        start_percent=cs.start_energy,
                        end_percent=pre.energy,
                    ),
                    tyre_wear=TyreWearData(
                        start=cs.start_wear,
                        end={pos: round(pre.wheels[i]["wear"], 4) for i, pos in enumerate(WHEEL_POSITIONS)},
                    ),
                    pit_stop=pit_stop,
                    remote_controlled=cs.start_control == CONTROL_REMOTE or pre.control == CONTROL_REMOTE,
                )
                self.stints.append(stint)

                # Start new stint
                self._start_stint(tick)
                self._pre_pit = None
                # If LMU went straight stand → on-track without an intermediate
                # at-box transition (e.g. 2→3→0), no pit_departed has fired yet.
                # Surface it now so the four-phase event sequence is complete.
                if not self._pit_departed_emitted:
                    events.add("pit_departed")
                events.add("pit_exit")
            elif self._current_stint_start is None:
                # First time leaving pits after session started in garage
                logger.debug("First pit exit — starting stint 1 (elapsed=%.1f)", tick.elapsed)
                self._start_stint(tick)
                self._pre_pit = None

        return events

    def _finalize_current_stint(self, tick: TickData) -> None:
        if self._current_stint_start is None:
            return
        cs = self._current_stint_start
        stint = Stint(
            stint_number=cs.stint_number,
            driver=cs.driver,
            start_lap=cs.start_lap,
            end_lap=tick.total_laps,
            start_time_elapsed=cs.start_elapsed,
            end_time_elapsed=tick.elapsed,
            fuel=FuelData(
                start_litres=cs.start_fuel,
                end_litres=tick.fuel,
                capacity=cs.fuel_capacity,
            ),
            energy=EnergyData(
                start_percent=cs.start_energy,
                end_percent=tick.virtual_energy,
            ),
            tyre_wear=TyreWearData(
                start=cs.start_wear,
                end={pos: round(tick.wheels[i]["wear"], 4) for i, pos in enumerate(WHEEL_POSITIONS)},
            ),
            remote_controlled=cs.start_control == CONTROL_REMOTE or tick.control == CONTROL_REMOTE,
        )
        self.stints.append(stint)
        self._current_stint_start = None

    def finalize_on_shutdown(self, tick: TickData | None) -> None:
        if self.session:
            self.session.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        if tick:
            self._finalize_current_stint(tick)
