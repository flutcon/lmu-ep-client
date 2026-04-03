from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TireInfo:
    changed: bool
    old_wear: float
    old_compound: str
    new_compound: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "changed": self.changed,
            "old_wear": self.old_wear,
            "old_compound": self.old_compound,
        }
        if self.new_compound is not None:
            d["new_compound"] = self.new_compound
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
class PitStop:
    pit_enter_elapsed: float
    pit_stand_elapsed: float
    pit_depart_elapsed: float
    pit_exit_elapsed: float
    fuel_added_litres: float
    energy_added_percent: float
    repair_flag: bool
    driver_change: bool
    new_driver: str | None
    tyres: dict[str, TireInfo]

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
            "repair_flag": self.repair_flag,
            "driver_change": self.driver_change,
        }
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
    pit_stop: PitStop | None = None

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
