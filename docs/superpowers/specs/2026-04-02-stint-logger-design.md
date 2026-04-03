# LMU Endurance Protocol Client — Design Spec

A lightweight Python CLI tool that captures stint activity data from Le Mans Ultimate via shared memory and writes structured JSON session logs.

## Goals

- Track stint data during Practice, Qualifying, and Race sessions
- Capture pit stop details: entry/stand/exit timing, tire changes with wear, fuel/energy added, repairs, driver changes
- Compute per-stint stats: duration, lap count, fuel per lap, energy per lap
- Support multi-driver team events (detect driver swaps)
- Output one JSON file per session for post-session review
- Pure CLI — start before race, stop after with Ctrl+C

## Non-Goals

- No real-time dashboard or UI
- No persistent database
- No strategy planning or comparison features
- No tracking of other cars on the grid (only the player's car)

## Dependencies

- **pyLMUSharedMemory** — shared memory access to LMU (zero external deps, Python 3.7+)
- Python standard library only beyond that

## Architecture

Single-process, three logical components:

```
┌─────────────────────────────────────┐
│           lmu-ep-client CLI         │
│                                     │
│  ┌───────────┐    ┌──────────────┐  │
│  │  Poller   │───>│ Stint        │  │
│  │  (1 Hz)   │    │ Detector     │  │
│  └───────────┘    └──────┬───────┘  │
│                          │          │
│                   ┌──────▼───────┐  │
│                   │ Session      │  │
│                   │ Accumulator  │  │
│                   └──────┬───────┘  │
│                          │          │
│                   ┌──────▼───────┐  │
│                   │ JSON Writer  │  │
│                   │ (flush on    │  │
│                   │  stint end + │  │
│                   │  periodic)   │  │
│                   └──────────────┘  │
└─────────────────────────────────────┘
         ▲
         │ shared memory
    ┌────┴────┐
    │   LMU   │
    └─────────┘
```

- **Poller** (`poller.py`) — main loop reading shared memory via `pyLMUSharedMemory.lmu_data.SimInfo` at 1 Hz using copy mode (access_mode=0) for data safety.
- **Stint Detector** (`detector.py`) — compares current vs. previous tick state to detect pit transitions, driver changes, lap completions, and session start/end.
- **Session Accumulator** — built into the detector; maintains the in-memory session and stint list.
- **JSON Writer** (`writer.py`) — serializes session data to JSON. Flushes to disk on every stint completion and every 30 seconds as a crash safety net.

## Project Structure

```
lmu-ep-client/
├── pyproject.toml
├── sessions/                  # Output directory (gitignored)
├── src/
│   └── lmu_ep_client/
│       ├── __init__.py
│       ├── __main__.py        # CLI entry point, signal handling
│       ├── poller.py          # Main polling loop
│       ├── detector.py        # State transition detection
│       ├── models.py          # Dataclasses: Session, Stint, PitStop, TireInfo
│       └── writer.py          # JSON serialization and file I/O
└── tests/
```

## Data Model

### Session (one per JSON file)

| Field | Type | Source |
|-------|------|--------|
| track | string | `scoringInfo.mTrackName` |
| session_type | string | `scoringInfo.mSession` via `LMUSession` enum |
| start_time | ISO 8601 string | wall clock at session detection |
| end_time | ISO 8601 string | wall clock at session end |
| vehicle | string | `vehScoringInfo[playerIdx].mVehicleName` |
| vehicle_class | string | `vehScoringInfo[playerIdx].mVehicleClass` via enum |

### Stint

| Field | Type | Description |
|-------|------|-------------|
| stint_number | int | Sequential, starting at 1 |
| driver | string | `vehScoringInfo[playerIdx].mDriverName` at stint start |
| start_lap | int | Lap number when stint began |
| end_lap | int | Lap number when stint ended |
| total_laps | int | end_lap - start_lap |
| start_time_elapsed | float | Session elapsed time at stint start (seconds) |
| end_time_elapsed | float | Session elapsed time at stint end (seconds) |
| stint_duration_seconds | float | end - start elapsed |
| fuel.start_litres | float | `mFuel` at stint start |
| fuel.end_litres | float | `mFuel` at stint end (pre-pit) |
| fuel.litres_used | float | start - end |
| fuel.litres_per_lap | float | litres_used / total_laps |
| fuel.capacity | float | `mFuelCapacity` |
| energy.start_percent | float | `mVirtualEnergy` at stint start (0-100) |
| energy.end_percent | float | `mVirtualEnergy` at stint end (pre-pit) |
| energy.used_percent | float | start - end |
| energy.percent_per_lap | float | used / total_laps |
| pit_stop | PitStop or null | null for the final stint |

### PitStop

| Field | Type | Description |
|-------|------|-------------|
| pit_enter_elapsed | float | Session elapsed time when pit state becomes Entering (2) |
| pit_stand_elapsed | float | Session elapsed time when pit state becomes Stopped (3) |
| pit_exit_elapsed | float | Session elapsed time when pit state becomes Exiting (4) |
| standing_time_seconds | float | pit_exit - pit_stand |
| total_pit_time_seconds | float | pit_exit - pit_enter |
| fuel_added_litres | float | post-pit fuel - pre-pit fuel |
| energy_added_percent | float | post-pit energy - pre-pit energy |
| repair_flag | bool | true if repair was requested/detected |
| driver_change | bool | true if driver name changed across pit stop |
| new_driver | string or null | new driver name if driver_change is true |
| tyres | object | keyed by FL, FR, RL, RR |

### TireInfo (per wheel)

| Field | Type | Description |
|-------|------|-------------|
| changed | bool | true if compound changed or wear reset detected |
| old_wear | float | wear value pre-pit (0.0 = fully worn, 1.0 = fresh) |
| old_compound | string | compound name pre-pit via `LMUCompoundType` enum |
| new_compound | string | compound name post-pit (only if changed) |

## Detection Logic

### Pit State Machine

pyLMUSharedMemory `mPitState` values:
- 0 = None (on track)
- 1 = Request
- 2 = Entering
- 3 = Stopped
- 4 = Exiting

Transitions monitored on the player's vehicle (`playerVehicleIdx`):

```
ON_TRACK (0/1) → ENTERING (2)   : snapshot pre-pit data (fuel, energy, tires, dents, lap, elapsed), record pit_enter_elapsed
ENTERING (2)   → STOPPED (3)    : record pit_stand_elapsed
STOPPED (3)    → EXITING (4)    : snapshot post-pit data (fuel, energy, tires, dents, driver name), record pit_exit_elapsed
EXITING (4)    → ON_TRACK (0)   : finalize stint (compute deltas, detect changes), start new stint
```

### Driver Change Detection

Compare `mDriverName` from pre-pit snapshot vs. post-pit snapshot on the player's vehicle scoring entry. If different → `driver_change: true`, `new_driver` set to post-pit name.

### Session Detection

- **Start:** `mGamePhase` transitions to a non-garage phase (formation lap, green flag, etc.) while valid scoring data is present. Supported session types: Practice 1-4, Qualifying 1-4, Warmup, Race 1-4.
- **End:** `mGamePhase` becomes Over (8), or user sends Ctrl+C (SIGINT).
- **Session type:** read from `scoringInfo.mSession`.

### Lap Completion

Detected by `mTotalLaps` incrementing on the player's vehicle. Used for per-lap fuel/energy tracking.

### Tire Change Detection

Compare pre-pit and post-pit tire data per wheel. A tire is considered "changed" if:
- Wear value resets (post-pit wear significantly higher than pre-pit), OR
- Compound type changes

### Repair Detection

Compare `mDentSeverity` values (8 positions) from pre-pit snapshot vs. post-pit snapshot. If any value decreased, `repair_flag: true`.

## Output

### File Location & Naming

```
sessions/{date}_{time}_{track}_{session_type}.json
```

Example: `sessions/2026-04-02_18-30-00_LeMans24h_Race.json`

The `sessions/` directory is created automatically and gitignored.

### Flush Strategy

- **On stint completion** — immediate write after each pit stop is finalized
- **Every 30 seconds** — periodic safety flush while a stint is active
- **On shutdown** — final flush on Ctrl+C, finalizing the current stint with available data

## CLI Interface

```bash
# Start tracking (auto-detects session from shared memory)
python -m lmu_ep_client

# Terminal output example:
# [14:30:05] Waiting for LMU session...
# [14:31:12] Session detected: Le Mans 24h — Race
# [14:31:12] Vehicle: Porsche 963 (Hypercar)
# [14:31:12] Stint 1 started — Driver: PlayerName
# [15:27:45] Pit entry detected
# [15:28:08] Pit exit — standing time: 23.2s | +97.7L fuel | +94.8% energy | Driver change: TeammateName
# [15:28:08] Stint 2 started — Driver: TeammateName
# ...
# [18:30:00] Session ended. Saved: sessions/2026-04-02_14-31-12_LeMans24h_Race.json
```

Ctrl+C triggers graceful shutdown with final data flush.

## Edge Cases

- **Game not running:** Poller waits in a retry loop, printing status every 10 seconds
- **Mid-stint crash (tool crash):** Periodic 30s flush minimizes data loss; last incomplete stint may have partial data
- **Qualifying (short stints):** Same logic applies; each pit in/out cycle is a stint
- **Practice (frequent pits):** All pit cycles tracked regardless of session type
- **No pit stop in session:** Single stint recorded with `pit_stop: null`
- **Multiple driver changes in one pit:** Only the final driver name post-pit matters
