# LMU Stint Logger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI tool that captures Le Mans Ultimate stint activity via shared memory and writes JSON session logs.

**Architecture:** Single-process poller at 1 Hz reads LMU shared memory via pyLMUSharedMemory. A detector compares current vs. previous tick state to identify pit transitions, driver changes, and session boundaries. Data accumulates in memory and flushes to JSON on stint completion, every 30s, and on shutdown.

**Tech Stack:** Python 3.10+, pyLMUSharedMemory, pytest, standard library only otherwise.

**Spec:** `docs/superpowers/specs/2026-04-02-stint-logger-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, entry point |
| `.gitignore` | Ignore sessions/ output directory |
| `src/lmu_ep_client/__init__.py` | Package marker |
| `src/lmu_ep_client/models.py` | Dataclasses: `SessionData`, `Stint`, `PitStop`, `TireInfo`, `FuelData`, `EnergyData` with `to_dict()` |
| `src/lmu_ep_client/writer.py` | JSON serialization, file naming, flush-to-disk logic |
| `src/lmu_ep_client/detector.py` | `StintDetector` class: pit state machine, driver change detection, session start/end, lap tracking |
| `src/lmu_ep_client/poller.py` | `run()` function: main 1 Hz loop, shared memory reads, periodic flush, shutdown handling |
| `src/lmu_ep_client/__main__.py` | CLI entry point, calls `poller.run()` |
| `tests/test_models.py` | Unit tests for models and serialization |
| `tests/test_writer.py` | Unit tests for JSON writing and file naming |
| `tests/test_detector.py` | Unit tests for state detection logic |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/lmu_ep_client/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "lmu-ep-client"
version = "0.1.0"
description = "LMU Endurance Protocol Client — stint activity logger"
requires-python = ">=3.10"
dependencies = [
    "pyLMUSharedMemory",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create .gitignore**

```
sessions/
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
```

- [ ] **Step 3: Create package init**

Create `src/lmu_ep_client/__init__.py` as an empty file.

- [ ] **Step 4: Create empty test directory**

Create `tests/__init__.py` as an empty file.

- [ ] **Step 5: Set up virtual environment and install**

Run:
```bash
python -m venv .venv
.venv/Scripts/activate && pip install -e ".[dev]"
```

Expected: Install succeeds, pyLMUSharedMemory is pulled in.

- [ ] **Step 6: Verify pytest runs**

Run: `python -m pytest tests/ -v`
Expected: "no tests ran" / 0 collected, exit code 5 (no tests). Confirms test infra works.

- [ ] **Step 7: Commit**

```bash
git init
git add pyproject.toml .gitignore src/lmu_ep_client/__init__.py tests/__init__.py
git commit -m "chore: scaffold project with pyproject.toml and package structure"
```

---

### Task 2: Data Models

**Files:**
- Create: `src/lmu_ep_client/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for TireInfo**

Create `tests/test_models.py`:

```python
from lmu_ep_client.models import TireInfo


def test_tire_info_to_dict_changed():
    tire = TireInfo(
        changed=True,
        old_wear=0.72,
        old_compound="Hard",
        new_compound="Soft",
    )
    result = tire.to_dict()
    assert result == {
        "changed": True,
        "old_wear": 0.72,
        "old_compound": "Hard",
        "new_compound": "Soft",
    }


def test_tire_info_to_dict_not_changed():
    tire = TireInfo(
        changed=False,
        old_wear=0.45,
        old_compound="Hard",
        new_compound=None,
    )
    result = tire.to_dict()
    assert result == {
        "changed": False,
        "old_wear": 0.45,
        "old_compound": "Hard",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Implement TireInfo**

Create `src/lmu_ep_client/models.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: 2 passed.

- [ ] **Step 5: Write failing tests for FuelData and EnergyData**

Append to `tests/test_models.py`:

```python
from lmu_ep_client.models import FuelData, EnergyData


def test_fuel_data_to_dict():
    fuel = FuelData(
        start_litres=110.0,
        end_litres=12.3,
        capacity=110.0,
    )
    result = fuel.to_dict()
    assert result == {
        "start_litres": 110.0,
        "end_litres": 12.3,
        "litres_used": 97.7,
        "litres_per_lap": None,
        "capacity": 110.0,
    }


def test_fuel_data_with_laps():
    fuel = FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0)
    result = fuel.to_dict(total_laps=28)
    assert result["litres_per_lap"] == round(97.7 / 28, 2)


def test_energy_data_to_dict():
    energy = EnergyData(start_percent=100.0, end_percent=5.2)
    result = energy.to_dict()
    assert result == {
        "start_percent": 100.0,
        "end_percent": 5.2,
        "used_percent": 94.8,
        "percent_per_lap": None,
    }


def test_energy_data_with_laps():
    energy = EnergyData(start_percent=100.0, end_percent=5.2)
    result = energy.to_dict(total_laps=28)
    assert result["percent_per_lap"] == round(94.8 / 28, 2)
```

- [ ] **Step 6: Run test to verify new tests fail**

Run: `python -m pytest tests/test_models.py -v`
Expected: 2 passed, 4 failed (new tests fail on import).

- [ ] **Step 7: Implement FuelData and EnergyData**

Append to `src/lmu_ep_client/models.py`:

```python
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
```

- [ ] **Step 8: Run tests to verify all pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: 6 passed.

- [ ] **Step 9: Write failing test for PitStop**

Append to `tests/test_models.py`:

```python
from lmu_ep_client.models import PitStop


def test_pit_stop_to_dict():
    pit = PitStop(
        pit_enter_elapsed=3360.5,
        pit_stand_elapsed=3372.0,
        pit_exit_elapsed=3395.2,
        fuel_added_litres=97.7,
        energy_added_percent=94.8,
        repair_flag=False,
        driver_change=True,
        new_driver="TeammateName",
        tyres={
            "FL": TireInfo(changed=True, old_wear=0.72, old_compound="Hard", new_compound="Hard"),
            "FR": TireInfo(changed=False, old_wear=0.68, old_compound="Hard"),
        },
    )
    result = pit.to_dict()
    assert result["standing_time_seconds"] == round(3395.2 - 3372.0, 1)
    assert result["total_pit_time_seconds"] == round(3395.2 - 3360.5, 1)
    assert result["driver_change"] is True
    assert result["new_driver"] == "TeammateName"
    assert result["tyres"]["FL"]["changed"] is True
    assert result["tyres"]["FR"]["changed"] is False


def test_pit_stop_no_driver_change():
    pit = PitStop(
        pit_enter_elapsed=100.0,
        pit_stand_elapsed=110.0,
        pit_exit_elapsed=125.0,
        fuel_added_litres=50.0,
        energy_added_percent=40.0,
        repair_flag=True,
        driver_change=False,
        new_driver=None,
        tyres={},
    )
    result = pit.to_dict()
    assert result["driver_change"] is False
    assert "new_driver" not in result
    assert result["repair_flag"] is True
```

- [ ] **Step 10: Run test to verify new tests fail**

Run: `python -m pytest tests/test_models.py::test_pit_stop_to_dict -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 11: Implement PitStop**

Append to `src/lmu_ep_client/models.py`:

```python
@dataclass
class PitStop:
    pit_enter_elapsed: float
    pit_stand_elapsed: float
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
            "pit_exit_elapsed": self.pit_exit_elapsed,
            "standing_time_seconds": round(self.pit_exit_elapsed - self.pit_stand_elapsed, 1),
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
```

- [ ] **Step 12: Run tests to verify all pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: 8 passed.

- [ ] **Step 13: Write failing test for Stint and SessionData**

Append to `tests/test_models.py`:

```python
from lmu_ep_client.models import Stint, SessionData


def test_stint_to_dict_with_pit():
    stint = Stint(
        stint_number=1,
        driver="Player",
        start_lap=1,
        end_lap=29,
        start_time_elapsed=0.0,
        end_time_elapsed=3360.5,
        fuel=FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0),
        energy=EnergyData(start_percent=100.0, end_percent=5.2),
        pit_stop=PitStop(
            pit_enter_elapsed=3360.5,
            pit_stand_elapsed=3372.0,
            pit_exit_elapsed=3395.2,
            fuel_added_litres=97.7,
            energy_added_percent=94.8,
            repair_flag=False,
            driver_change=False,
            new_driver=None,
            tyres={},
        ),
    )
    result = stint.to_dict()
    assert result["stint_number"] == 1
    assert result["total_laps"] == 28
    assert result["stint_duration_seconds"] == 3360.5
    assert result["fuel"]["litres_per_lap"] == round(97.7 / 28, 2)
    assert result["pit_stop"] is not None


def test_stint_to_dict_no_pit():
    stint = Stint(
        stint_number=2,
        driver="Player",
        start_lap=29,
        end_lap=45,
        start_time_elapsed=3395.2,
        end_time_elapsed=5300.0,
        fuel=FuelData(start_litres=110.0, end_litres=30.0, capacity=110.0),
        energy=EnergyData(start_percent=100.0, end_percent=20.0),
        pit_stop=None,
    )
    result = stint.to_dict()
    assert result["total_laps"] == 16
    assert result["pit_stop"] is None


def test_session_data_to_dict():
    session = SessionData(
        track="Le Mans 24h",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    result = session.to_dict(stints=[])
    assert result["session"]["track"] == "Le Mans 24h"
    assert result["session"]["session_type"] == "Race"
    assert result["stints"] == []
```

- [ ] **Step 14: Run test to verify new tests fail**

Run: `python -m pytest tests/test_models.py::test_stint_to_dict_with_pit -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 15: Implement Stint and SessionData**

Append to `src/lmu_ep_client/models.py`:

```python
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
```

- [ ] **Step 16: Run all model tests**

Run: `python -m pytest tests/test_models.py -v`
Expected: 11 passed.

- [ ] **Step 17: Commit**

```bash
git add src/lmu_ep_client/models.py tests/test_models.py
git commit -m "feat: add data models with serialization for session, stint, pit stop, tire info"
```

---

### Task 3: JSON Writer

**Files:**
- Create: `src/lmu_ep_client/writer.py`
- Create: `tests/test_writer.py`

- [ ] **Step 1: Write failing test for filename generation**

Create `tests/test_writer.py`:

```python
from lmu_ep_client.writer import session_filename


def test_session_filename():
    result = session_filename(
        start_time="2026-04-02T18:30:00",
        track="Le Mans 24h",
        session_type="Race",
    )
    assert result == "2026-04-02_18-30-00_Le_Mans_24h_Race.json"


def test_session_filename_special_chars():
    result = session_filename(
        start_time="2026-04-02T09:05:00",
        track="Spa-Francorchamps",
        session_type="Practice 1",
    )
    assert result == "2026-04-02_09-05-00_Spa-Francorchamps_Practice_1.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_writer.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement session_filename**

Create `src/lmu_ep_client/writer.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from lmu_ep_client.models import SessionData, Stint


def session_filename(start_time: str, track: str, session_type: str) -> str:
    time_part = start_time.replace("T", "_").replace(":", "-")
    track_part = track.replace(" ", "_")
    session_part = session_type.replace(" ", "_")
    return f"{time_part}_{track_part}_{session_part}.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_writer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Write failing test for flush_session**

Append to `tests/test_writer.py`:

```python
import json
from pathlib import Path

from lmu_ep_client.writer import flush_session
from lmu_ep_client.models import SessionData, Stint, FuelData, EnergyData


def test_flush_session_creates_file(tmp_path):
    session = SessionData(
        track="Monza",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    stints = [
        Stint(
            stint_number=1,
            driver="Player",
            start_lap=1,
            end_lap=11,
            start_time_elapsed=0.0,
            end_time_elapsed=600.0,
            fuel=FuelData(start_litres=110.0, end_litres=70.0, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=60.0),
        ),
    ]
    path = flush_session(session, stints, output_dir=tmp_path)

    assert path.exists()
    assert path.name == "2026-04-02_18-30-00_Monza_Race.json"

    data = json.loads(path.read_text())
    assert data["session"]["track"] == "Monza"
    assert len(data["stints"]) == 1
    assert data["stints"][0]["total_laps"] == 10


def test_flush_session_overwrites(tmp_path):
    session = SessionData(
        track="Monza",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    flush_session(session, [], output_dir=tmp_path)
    path = flush_session(session, [], output_dir=tmp_path)
    assert path.exists()
    # Only one file, overwritten
    assert len(list(tmp_path.iterdir())) == 1
```

- [ ] **Step 6: Run test to verify new tests fail**

Run: `python -m pytest tests/test_writer.py::test_flush_session_creates_file -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 7: Implement flush_session**

Append to `src/lmu_ep_client/writer.py`:

```python
def flush_session(
    session: SessionData,
    stints: list[Stint],
    output_dir: Path | None = None,
) -> Path:
    if output_dir is None:
        output_dir = Path("sessions")
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = session_filename(session.start_time, session.track, session.session_type)
    path = output_dir / filename

    data = session.to_dict(stints)
    path.write_text(json.dumps(data, indent=2))
    return path
```

- [ ] **Step 8: Run all writer tests**

Run: `python -m pytest tests/test_writer.py -v`
Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add src/lmu_ep_client/writer.py tests/test_writer.py
git commit -m "feat: add JSON writer with session file naming and flush logic"
```

---

### Task 4: Stint Detector

**Files:**
- Create: `src/lmu_ep_client/detector.py`
- Create: `tests/test_detector.py`

The detector operates on a simple data snapshot rather than directly on pyLMUSharedMemory types, so it can be tested without the game running. We define a `TickData` dataclass that the poller will populate from shared memory each tick.

- [ ] **Step 1: Write failing test for session start detection**

Create `tests/test_detector.py`:

```python
from lmu_ep_client.detector import StintDetector, TickData


def _make_tick(
    *,
    game_phase: int = 5,
    session_type: int = 5,
    track: str = "Monza",
    elapsed: float = 0.0,
    driver: str = "Player",
    vehicle: str = "Porsche 963",
    vehicle_class: str = "Hypercar",
    pit_state: int = 0,
    total_laps: int = 0,
    fuel: float = 110.0,
    fuel_capacity: float = 110.0,
    virtual_energy: float = 100.0,
    wheels: list | None = None,
    dent_severity: list | None = None,
) -> TickData:
    if wheels is None:
        wheels = [
            {"wear": 1.0, "compound_type": 2, "flat": False, "detached": False}
            for _ in range(4)
        ]
    if dent_severity is None:
        dent_severity = [0] * 8
    return TickData(
        game_phase=game_phase,
        session_type=session_type,
        track=track,
        elapsed=elapsed,
        driver=driver,
        vehicle=vehicle,
        vehicle_class=vehicle_class,
        pit_state=pit_state,
        total_laps=total_laps,
        fuel=fuel,
        fuel_capacity=fuel_capacity,
        virtual_energy=virtual_energy,
        wheels=wheels,
        dent_severity=dent_severity,
    )


def test_session_start_detected():
    det = StintDetector()
    # First tick in green flag phase
    events = det.update(_make_tick(game_phase=5, elapsed=10.0))
    assert "session_start" in events
    assert det.session is not None
    assert det.session.track == "Monza"


def test_no_session_in_garage():
    det = StintDetector()
    events = det.update(_make_tick(game_phase=0))
    assert "session_start" not in events
    assert det.session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_detector.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement TickData and session detection**

Create `src/lmu_ep_client/detector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

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


@dataclass
class TickData:
    game_phase: int
    session_type: int
    track: str
    elapsed: float
    driver: str
    vehicle: str
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


class StintDetector:
    def __init__(self) -> None:
        self.session: SessionData | None = None
        self.stints: list[Stint] = []
        self._current_stint_start: dict | None = None
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
                    vehicle=tick.vehicle,
                    vehicle_class=tick.vehicle_class,
                )
                self._start_stint(tick)
                events.add("session_start")
        else:
            # Session end detection
            if tick.game_phase == PHASE_SESSION_OVER:
                self._finalize_current_stint(tick)
                if self.session:
                    self.session.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                events.add("session_end")
                self._session_active = False
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
        self._current_stint_start = {
            "stint_number": len(self.stints) + 1,
            "driver": tick.driver,
            "start_lap": tick.total_laps,
            "start_elapsed": tick.elapsed,
            "start_fuel": tick.fuel,
            "fuel_capacity": tick.fuel_capacity,
            "start_energy": tick.virtual_energy,
        }

    def _check_pit_transitions(self, tick: TickData) -> set[str]:
        events: set[str] = set()
        prev = self._prev_pit_state
        curr = tick.pit_state

        # ON_TRACK -> ENTERING: snapshot pre-pit, record pit_enter
        if prev in (PIT_NONE, PIT_REQUEST) and curr == PIT_ENTERING:
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
            events.add("pit_enter")

        # ENTERING -> STOPPED: record pit_stand time
        elif prev == PIT_ENTERING and curr == PIT_STOPPED:
            self._pit_stand_elapsed = tick.elapsed

        # STOPPED -> EXITING: snapshot post-pit, record pit_exit
        elif prev == PIT_STOPPED and curr == PIT_EXITING:
            self._pit_stand_elapsed = self._pit_stand_elapsed or tick.elapsed
            pit_exit_elapsed = tick.elapsed

            if self._pre_pit and self._current_stint_start:
                pre = self._pre_pit

                # Build tire info
                tyres: dict[str, TireInfo] = {}
                for i, pos in enumerate(WHEEL_POSITIONS):
                    old_w = pre.wheels[i]
                    new_w = tick.wheels[i]
                    compound_changed = old_w["compound_type"] != new_w["compound_type"]
                    wear_reset = new_w["wear"] > old_w["wear"] + 0.1
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
                    stint_number=cs["stint_number"],
                    driver=cs["driver"],
                    start_lap=cs["start_lap"],
                    end_lap=pre.lap,
                    start_time_elapsed=cs["start_elapsed"],
                    end_time_elapsed=pre.elapsed,
                    fuel=FuelData(
                        start_litres=cs["start_fuel"],
                        end_litres=pre.fuel,
                        capacity=cs["fuel_capacity"],
                    ),
                    energy=EnergyData(
                        start_percent=cs["start_energy"],
                        end_percent=pre.energy,
                    ),
                    pit_stop=pit_stop,
                )
                self.stints.append(stint)

                # Start new stint
                self._start_stint(tick)
                self._pre_pit = None

            events.add("pit_exit")

        # EXITING -> ON_TRACK: stint is now running
        elif prev == PIT_EXITING and curr in (PIT_NONE, PIT_REQUEST):
            events.add("on_track")

        return events

    def _finalize_current_stint(self, tick: TickData) -> None:
        if self._current_stint_start is None:
            return
        cs = self._current_stint_start
        stint = Stint(
            stint_number=cs["stint_number"],
            driver=cs["driver"],
            start_lap=cs["start_lap"],
            end_lap=tick.total_laps,
            start_time_elapsed=cs["start_elapsed"],
            end_time_elapsed=tick.elapsed,
            fuel=FuelData(
                start_litres=cs["start_fuel"],
                end_litres=tick.fuel,
                capacity=cs["fuel_capacity"],
            ),
            energy=EnergyData(
                start_percent=cs["start_energy"],
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
```

- [ ] **Step 4: Run tests to verify session detection passes**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 2 passed.

- [ ] **Step 5: Write failing tests for pit state transitions**

Append to `tests/test_detector.py`:

```python
def test_full_pit_cycle():
    det = StintDetector()

    # Start session
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))

    # Drive some laps
    det.update(_make_tick(elapsed=300.0, total_laps=5))

    # Enter pit
    events = det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, virtual_energy=40.0))
    assert "pit_enter" in events

    # Pit stopped
    events = det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, virtual_energy=40.0))

    # Pit exiting — fuel/energy refilled, tires swapped
    fresh_wheels = [
        {"wear": 1.0, "compound_type": 0, "flat": False, "detached": False}
        for _ in range(4)
    ]
    events = det.update(_make_tick(
        elapsed=635.0,
        pit_state=4,
        total_laps=10,
        fuel=110.0,
        virtual_energy=100.0,
        wheels=fresh_wheels,
    ))
    assert "pit_exit" in events
    assert len(det.stints) == 1

    stint = det.stints[0]
    assert stint.stint_number == 1
    assert stint.start_lap == 0
    assert stint.end_lap == 10
    assert stint.fuel.start_litres == 110.0
    assert stint.fuel.end_litres == 50.0

    pit = stint.pit_stop
    assert pit is not None
    assert pit.pit_enter_elapsed == 600.0
    assert pit.pit_stand_elapsed == 612.0
    assert pit.pit_exit_elapsed == 635.0
    assert pit.fuel_added_litres == 60.0
    assert pit.energy_added_percent == 60.0
    assert pit.driver_change is False

    # All tires changed (Hard -> Soft, wear reset)
    for pos in ["FL", "FR", "RL", "RR"]:
        assert pit.tyres[pos].changed is True
        assert pit.tyres[pos].old_compound == "Hard"
        assert pit.tyres[pos].new_compound == "Soft"


def test_driver_change_detection():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, driver="Driver A"))

    # Enter pit as Driver A
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, driver="Driver A"))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, driver="Driver A"))

    # Exit pit as Driver B
    det.update(_make_tick(elapsed=640.0, pit_state=4, total_laps=10, fuel=110.0, driver="Driver B"))

    assert len(det.stints) == 1
    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.driver_change is True
    assert pit.new_driver == "Driver B"


def test_repair_detection():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))

    # Enter pit with damage
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, dent_severity=[0, 2, 1, 0, 0, 0, 0, 0]))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, dent_severity=[0, 2, 1, 0, 0, 0, 0, 0]))

    # Exit pit with damage repaired
    det.update(_make_tick(elapsed=650.0, pit_state=4, total_laps=10, fuel=110.0, dent_severity=[0, 0, 0, 0, 0, 0, 0, 0]))

    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.repair_flag is True


def test_no_repair_when_no_damage_change():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0))
    det.update(_make_tick(elapsed=635.0, pit_state=4, total_laps=10, fuel=110.0))

    pit = det.stints[0].pit_stop
    assert pit is not None
    assert pit.repair_flag is False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 6 passed.

- [ ] **Step 7: Write failing test for session end and finalize_on_shutdown**

Append to `tests/test_detector.py`:

```python
def test_session_end():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))
    det.update(_make_tick(elapsed=600.0, total_laps=10, fuel=50.0, virtual_energy=40.0))

    events = det.update(_make_tick(game_phase=8, elapsed=610.0, total_laps=10, fuel=50.0, virtual_energy=40.0))
    assert "session_end" in events
    assert len(det.stints) == 1
    assert det.stints[0].pit_stop is None
    assert det.stints[0].end_lap == 10
    assert det.session is not None
    assert det.session.end_time != ""


def test_finalize_on_shutdown():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0, total_laps=0))
    tick = _make_tick(elapsed=600.0, total_laps=10, fuel=50.0, virtual_energy=40.0)
    det.update(tick)

    det.finalize_on_shutdown(tick)
    assert len(det.stints) == 1
    assert det.stints[0].end_lap == 10
    assert det.session.end_time != ""
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 8 passed.

- [ ] **Step 9: Write failing test for tire not changed**

Append to `tests/test_detector.py`:

```python
def test_tire_not_changed_when_wear_similar():
    det = StintDetector()
    det.update(_make_tick(game_phase=5, elapsed=0.0))

    worn_wheels = [
        {"wear": 0.5, "compound_type": 2, "flat": False, "detached": False}
        for _ in range(4)
    ]
    det.update(_make_tick(elapsed=600.0, pit_state=2, total_laps=10, fuel=50.0, wheels=worn_wheels))
    det.update(_make_tick(elapsed=612.0, pit_state=3, total_laps=10, fuel=50.0, wheels=worn_wheels))

    # Exit with same wear (no tire change, just fuel)
    det.update(_make_tick(elapsed=625.0, pit_state=4, total_laps=10, fuel=110.0, wheels=worn_wheels))

    pit = det.stints[0].pit_stop
    for pos in ["FL", "FR", "RL", "RR"]:
        assert pit.tyres[pos].changed is False
        assert pit.tyres[pos].old_wear == 0.5
        assert pit.tyres[pos].new_compound is None
```

- [ ] **Step 10: Run tests to verify it passes**

Run: `python -m pytest tests/test_detector.py -v`
Expected: 9 passed.

- [ ] **Step 11: Commit**

```bash
git add src/lmu_ep_client/detector.py tests/test_detector.py
git commit -m "feat: add stint detector with pit state machine, driver/tire/repair detection"
```

---

### Task 5: Poller (Main Loop)

**Files:**
- Create: `src/lmu_ep_client/poller.py`

This module integrates with pyLMUSharedMemory and cannot be unit tested without the game running. It is intentionally thin — all logic lives in the detector and writer which are fully tested.

- [ ] **Step 1: Implement poller.py**

Create `src/lmu_ep_client/poller.py`:

```python
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
            vehicle_class=veh_scoring.mVehicleClass.decode().rstrip("\x00"),
            pit_state=veh_scoring.mPitState,
            total_laps=veh_scoring.mTotalLaps,
            fuel=veh_telem.mFuel,
            fuel_capacity=veh_telem.mFuelCapacity,
            virtual_energy=veh_telem.mVirtualEnergy,
            wheels=wheels,
            dent_severity=dent_severity,
        )
    except Exception:
        logger.debug("Failed to read shared memory", exc_info=True)
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
            events = detector.update(tick)

            if "session_start" in events:
                _log(f"Session detected: {detector.session.track} — {detector.session.session_type}")
                _log(f"Vehicle: {tick.vehicle} ({tick.vehicle_class})")
                _log(f"Stint 1 started — Driver: {tick.driver}")

            if "pit_enter" in events:
                _log("Pit entry detected")

            if "pit_exit" in events:
                stint = detector.stints[-1]
                pit = stint.pit_stop
                msg = f"Pit exit — standing time: {pit.to_dict()['standing_time_seconds']}s"
                msg += f" | +{pit.fuel_added_litres}L fuel"
                msg += f" | +{pit.energy_added_percent}% energy"
                if pit.driver_change:
                    msg += f" | Driver change: {pit.new_driver}"
                _log(msg)

                new_stint = detector.stints[-1].stint_number + 1
                _log(f"Stint {new_stint} started — Driver: {tick.driver}")

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
    finally:
        _log("Shutting down...")
        if detector.session:
            detector.finalize_on_shutdown(last_tick)
            file_path = flush_session(detector.session, detector.stints, output_dir)
            _log(f"Final save: {file_path}")
        if info:
            info.close()
```

- [ ] **Step 2: Review the code for correctness**

Read through poller.py and verify:
- `_read_tick` reads all required fields from shared memory
- String fields use `.decode().rstrip("\x00")`
- Events are handled in the correct order
- Flush timing logic is correct
- Shutdown path finalizes and saves

- [ ] **Step 3: Commit**

```bash
git add src/lmu_ep_client/poller.py
git commit -m "feat: add poller with 1Hz shared memory reads and periodic flush"
```

---

### Task 6: CLI Entry Point

**Files:**
- Create: `src/lmu_ep_client/__main__.py`

- [ ] **Step 1: Implement __main__.py**

Create `src/lmu_ep_client/__main__.py`:

```python
from lmu_ep_client.poller import run

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Verify module is runnable**

Run: `python -m lmu_ep_client`
Expected: Prints `[HH:MM:SS] Waiting for LMU session...` then `[HH:MM:SS] LMU not detected. Retrying...` (since the game is not running). Ctrl+C to exit cleanly.

- [ ] **Step 3: Commit**

```bash
git add src/lmu_ep_client/__main__.py
git commit -m "feat: add CLI entry point for python -m lmu_ep_client"
```

---

### Task 7: Final Integration Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (should be ~20 tests across test_models, test_writer, test_detector).

- [ ] **Step 2: Verify JSON output structure manually**

Run a quick smoke test by creating a test script or adding to tests:

Append to `tests/test_writer.py`:

```python
def test_full_session_json_structure(tmp_path):
    """Smoke test: verify the complete JSON output matches expected schema."""
    from lmu_ep_client.models import PitStop, TireInfo

    session = SessionData(
        track="Le Mans 24h",
        session_type="Race",
        start_time="2026-04-02T18:30:00",
        end_time="2026-04-02T19:30:00",
        vehicle="Porsche 963",
        vehicle_class="Hypercar",
    )
    stints = [
        Stint(
            stint_number=1,
            driver="Player",
            start_lap=0,
            end_lap=28,
            start_time_elapsed=0.0,
            end_time_elapsed=3360.5,
            fuel=FuelData(start_litres=110.0, end_litres=12.3, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=5.2),
            pit_stop=PitStop(
                pit_enter_elapsed=3360.5,
                pit_stand_elapsed=3372.0,
                pit_exit_elapsed=3395.2,
                fuel_added_litres=97.7,
                energy_added_percent=94.8,
                repair_flag=False,
                driver_change=True,
                new_driver="Teammate",
                tyres={
                    "FL": TireInfo(changed=True, old_wear=0.28, old_compound="Hard", new_compound="Hard"),
                    "FR": TireInfo(changed=True, old_wear=0.32, old_compound="Hard", new_compound="Hard"),
                    "RL": TireInfo(changed=False, old_wear=0.55, old_compound="Hard"),
                    "RR": TireInfo(changed=False, old_wear=0.58, old_compound="Hard"),
                },
            ),
        ),
        Stint(
            stint_number=2,
            driver="Teammate",
            start_lap=28,
            end_lap=55,
            start_time_elapsed=3395.2,
            end_time_elapsed=6600.0,
            fuel=FuelData(start_litres=110.0, end_litres=15.0, capacity=110.0),
            energy=EnergyData(start_percent=100.0, end_percent=8.0),
        ),
    ]

    path = flush_session(session, stints, output_dir=tmp_path)
    data = json.loads(path.read_text())

    # Verify top-level structure
    assert "session" in data
    assert "stints" in data
    assert len(data["stints"]) == 2

    # Verify first stint has pit_stop with all fields
    s1 = data["stints"][0]
    assert s1["pit_stop"]["driver_change"] is True
    assert s1["pit_stop"]["new_driver"] == "Teammate"
    assert s1["pit_stop"]["tyres"]["FL"]["changed"] is True
    assert s1["pit_stop"]["tyres"]["RL"]["changed"] is False
    assert "new_compound" not in s1["pit_stop"]["tyres"]["RL"]

    # Verify second stint has no pit_stop
    assert data["stints"][1]["pit_stop"] is None

    # Verify computed fields
    assert s1["total_laps"] == 28
    assert s1["fuel"]["litres_per_lap"] == round(97.7 / 28, 2)
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_writer.py
git commit -m "test: add integration smoke test for full JSON output structure"
```
