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

# Minimum wear improvement to consider a tire swap has occurred
TIRE_WEAR_CHANGE_THRESHOLD = 0.1


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
    fuel: float
    fuel_capacity: float
    virtual_energy: float
    wheels: list[dict]
    dent_severity: list[int]


@dataclass
class _PrePitSnapshot:
    elapsed: float
    fuel: float
    energy: float
    lap: int
    driver: str
    wheels: list[dict]
    dent_severity: list[int]


@dataclass
class _StintStart:
    stint_number: int
    driver: str
    start_lap: int
    start_elapsed: float
    start_fuel: float
    fuel_capacity: float
    start_energy: float


class StintDetector:
    def __init__(self) -> None:
        self.session: SessionData | None = None
        self.stints: list[Stint] = []
        self._current_stint_start: _StintStart | None = None
        self._prev_pit_state: int = PIT_NONE
        self._prev_laps: int = 0
        self._pre_pit: _PrePitSnapshot | None = None
        self._pit_enter_elapsed: float = 0.0
        self._pit_stand_elapsed: float = 0.0
        self._session_active: bool = False

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
                else:
                    logger.debug("Session started while in pits (pit_state=%d), deferring first stint", tick.pit_state)
                events.add("session_start")
        else:
            # Session end detection (SessionOver or return to garage)
            if tick.game_phase in (PHASE_SESSION_OVER, PHASE_GARAGE):
                self._finalize_current_stint(tick)
                if self.session:
                    self.session.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                events.add("session_end")
                self._session_active = False
                self._prev_laps = 0
                self._pre_pit = None
                self._pit_enter_elapsed = 0.0
                self._pit_stand_elapsed = 0.0
                self._current_stint_start = None
                self._prev_pit_state = tick.pit_state
                return events

            # Pit state transitions
            pit_events = self._check_pit_transitions(tick)
            events.update(pit_events)

            # Lap completion
            if tick.total_laps > self._prev_laps and self._prev_laps > 0:
                events.add("lap_completed")
            self._prev_laps = tick.total_laps

        self._prev_pit_state = tick.pit_state
        return events

    def _start_stint(self, tick: TickData) -> None:
        self._current_stint_start = _StintStart(
            stint_number=len(self.stints) + 1,
            driver=tick.driver,
            start_lap=tick.total_laps,
            start_elapsed=tick.elapsed,
            start_fuel=tick.fuel,
            fuel_capacity=tick.fuel_capacity,
            start_energy=tick.virtual_energy,
        )

    def _check_pit_transitions(self, tick: TickData) -> set[str]:
        events: set[str] = set()
        prev = self._prev_pit_state
        curr = tick.pit_state
        on_track = (PIT_NONE, PIT_REQUEST)
        in_pit = (PIT_ENTERING, PIT_STOPPED, PIT_EXITING)

        if prev != curr:
            logger.debug("Pit state: %d -> %d (elapsed=%.1f)", prev, curr, tick.elapsed)

        # Entered pit zone: was on track, now in pit area
        if prev in on_track and curr in in_pit:
            self._pre_pit = _PrePitSnapshot(
                elapsed=tick.elapsed,
                fuel=tick.fuel,
                energy=tick.virtual_energy,
                lap=tick.total_laps,
                driver=tick.driver,
                wheels=[dict(w) for w in tick.wheels],
                dent_severity=list(tick.dent_severity),
            )
            self._pit_enter_elapsed = tick.elapsed
            self._pit_stand_elapsed = 0.0
            events.add("pit_enter")

        # Reached pit stand (record when we first see STOPPED)
        if curr == PIT_STOPPED and prev != PIT_STOPPED:
            self._pit_stand_elapsed = tick.elapsed

        # Left pit zone: was in pit area, now back on track
        if prev in in_pit and curr in on_track:
            pit_exit_elapsed = tick.elapsed
            if not self._pit_stand_elapsed:
                self._pit_stand_elapsed = self._pit_enter_elapsed

            if self._pre_pit and self._current_stint_start:
                pre = self._pre_pit

                # Build tire info
                tyres: dict[str, TireInfo] = {}
                for i, pos in enumerate(WHEEL_POSITIONS):
                    old_w = pre.wheels[i]
                    new_w = tick.wheels[i]
                    compound_changed = old_w["compound_type"] != new_w["compound_type"]
                    wear_reset = new_w["wear"] > old_w["wear"] + TIRE_WEAR_CHANGE_THRESHOLD
                    changed = compound_changed or wear_reset
                    tyres[pos] = TireInfo(
                        changed=changed,
                        old_wear=round(old_w["wear"], 4),
                        old_compound=COMPOUND_NAMES.get(old_w["compound_type"], "Unknown"),
                        new_compound=COMPOUND_NAMES.get(new_w["compound_type"], "Unknown") if changed else None,
                    )

                # Detect repair
                repair = any(
                    tick.dent_severity[j] < pre.dent_severity[j]
                    for j in range(len(pre.dent_severity))
                )

                # Detect driver change
                driver_changed = tick.driver != pre.driver

                pit_stop = PitStop(
                    pit_enter_elapsed=self._pit_enter_elapsed,
                    pit_stand_elapsed=self._pit_stand_elapsed,
                    pit_exit_elapsed=pit_exit_elapsed,
                    fuel_added_litres=round(tick.fuel - pre.fuel, 2),
                    energy_added_percent=round(tick.virtual_energy - pre.energy, 2),
                    repair_flag=repair,
                    driver_change=driver_changed,
                    new_driver=tick.driver if driver_changed else None,
                    tyres=tyres,
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
                    pit_stop=pit_stop,
                )
                self.stints.append(stint)

                # Start new stint
                self._start_stint(tick)
                self._pre_pit = None
            elif self._current_stint_start is None:
                # First time leaving pits after session started in garage
                logger.debug("First pit exit — starting stint 1 (elapsed=%.1f)", tick.elapsed)
                self._start_stint(tick)
                self._pre_pit = None

            events.add("pit_exit")

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
        )
        self.stints.append(stint)
        self._current_stint_start = None

    def finalize_on_shutdown(self, tick: TickData | None) -> None:
        if self.session:
            self.session.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        if tick:
            self._finalize_current_stint(tick)
