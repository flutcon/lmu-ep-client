from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TireInfo:
    changed: bool
    old_wear: float
    old_compound: str
    new_compound: str | None = None
    new_wear: float | None = None  # post-pit wear (1.0=fresh, 0.0=worn)

    def to_dict(self) -> dict:
        d: dict = {
            "changed": self.changed,
            "old_wear": self.old_wear,
            "old_compound": self.old_compound,
        }
        if self.new_compound is not None:
            d["new_compound"] = self.new_compound
        if self.new_wear is not None:
            d["new_wear"] = self.new_wear
        return d


@dataclass
class FuelData:
    start_litres: float
    end_litres: float
    capacity: float

    def to_dict(self, total_laps: int | None = None) -> dict:
        used = round(self.start_litres - self.end_litres, 2)
        per_lap = round(used / total_laps, 2) if total_laps and total_laps > 0 else None
        return {
            "start_litres": self.start_litres,
            "end_litres": self.end_litres,
            "litres_used": used,
            "litres_per_lap": per_lap,
            "capacity": self.capacity,
        }


@dataclass
class EnergyData:
    start_percent: float
    end_percent: float

    def to_dict(self, total_laps: int | None = None) -> dict:
        used = round(self.start_percent - self.end_percent, 2)
        per_lap = round(used / total_laps, 2) if total_laps and total_laps > 0 else None
        return {
            "start_percent": self.start_percent,
            "end_percent": self.end_percent,
            "used_percent": used,
            "percent_per_lap": per_lap,
        }


@dataclass
class TyreWearData:
    start: dict[str, float]  # FL/FR/RL/RR -> wear at stint start (1.0=fresh, 0.0=worn)
    end: dict[str, float]    # wear at stint end (pre-pit or session end)

    def to_dict(self) -> dict:
        delta = {pos: round(self.start[pos] - self.end[pos], 4) for pos in self.start}
        return {
            "start": self.start,
            "end": self.end,
            "used": delta,
        }


@dataclass
class PitStop:
    pit_enter_elapsed: float
    pit_stand_elapsed: float
    pit_depart_elapsed: float
    pit_exit_elapsed: float
    fuel_added_litres: float
    energy_added_percent: float
    repair_flag: bool | None
    driver_change: bool
    new_driver: str | None
    tyres: dict[str, TireInfo]
    post_fuel_litres: float = 0.0       # absolute litres at pit exit (next stint start)
    post_energy_percent: float = 0.0    # absolute % at pit exit (next stint start)

    def to_dict(self) -> dict:
        d: dict = {
            "pit_enter_elapsed": self.pit_enter_elapsed,
            "pit_stand_elapsed": self.pit_stand_elapsed,
            "pit_depart_elapsed": self.pit_depart_elapsed,
            "pit_exit_elapsed": self.pit_exit_elapsed,
            "standing_time_seconds": round(self.pit_depart_elapsed - self.pit_stand_elapsed, 1),
            "total_pit_time_seconds": round(self.pit_exit_elapsed - self.pit_enter_elapsed, 1),
            "fuel_added_litres": self.fuel_added_litres,
            "energy_added_percent": self.energy_added_percent,
            "post_fuel_litres": self.post_fuel_litres,
            "post_energy_percent": self.post_energy_percent,
            "driver_change": self.driver_change,
        }
        if self.repair_flag is not None:
            d["repair_flag"] = self.repair_flag
        if self.new_driver is not None:
            d["new_driver"] = self.new_driver
        d["tyres"] = {pos: tire.to_dict() for pos, tire in self.tyres.items()}
        return d


@dataclass
class Stint:
    stint_number: int
    driver: str
    start_lap: int
    end_lap: int
    start_time_elapsed: float
    end_time_elapsed: float
    fuel: FuelData
    energy: EnergyData
    tyre_wear: TyreWearData
    pit_stop: PitStop | None = None
    # Set when the stint was driven by a remote teammate. LMU stops updating
    # the local mWear telemetry slot, so per-wheel wear is unreadable on the
    # spectating client — null it out. Fuel still works because the poller
    # falls back to the networked mFuelFraction; energy is networked too.
    remote_controlled: bool = False

    def to_dict(self) -> dict:
        total_laps = self.end_lap - self.start_lap
        return {
            "stint_number": self.stint_number,
            "driver": self.driver,
            "start_lap": self.start_lap,
            "end_lap": self.end_lap,
            "total_laps": total_laps,
            "start_time_elapsed": self.start_time_elapsed,
            "end_time_elapsed": self.end_time_elapsed,
            "stint_duration_seconds": round(self.end_time_elapsed - self.start_time_elapsed, 1),
            "fuel": self.fuel.to_dict(total_laps=total_laps),
            "energy": self.energy.to_dict(total_laps=total_laps),
            "tyre_wear": None if self.remote_controlled else self.tyre_wear.to_dict(),
            "pit_stop": self.pit_stop.to_dict() if self.pit_stop else None,
        }


@dataclass
class SessionData:
    track: str
    session_type: str
    start_time: str
    end_time: str
    vehicle: str
    vehicle_class: str

    def to_dict(self, stints: list[Stint]) -> dict:
        return {
            "session": {
                "track": self.track,
                "session_type": self.session_type,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "vehicle": self.vehicle,
                "vehicle_class": self.vehicle_class,
            },
            "stints": [s.to_dict() for s in stints],
        }
