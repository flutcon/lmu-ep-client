# lmu-ep-client

Stint activity logger for Le Mans Ultimate. Reads shared memory and writes a structured JSON session file capturing stint data, pit stop details, tire changes, fuel/energy usage, repairs, and driver changes.

## Requirements

- Windows (LMU shared memory is Windows-only)
- Python 3.10+
- Le Mans Ultimate installed and running

## Usage

### Executable (recommended)

Download or build `lmu-ep-client.exe` (see below). Start it before or during a session:

```
lmu-ep-client.exe
lmu-ep-client.exe --output-dir C:\path\to\sessions
lmu-ep-client.exe --registration-id <uuid>
lmu-ep-client.exe --registration-id <uuid> --practice --practice-team-member-id <uuid>
lmu-ep-client.exe --api-key lmu_... --registration-id <uuid>
lmu-ep-client.exe --debug
```

Stop with `Ctrl+C`. The tool writes a final flush on shutdown.

### From source

```
pip install -e ".[dev]"
python -m lmu_ep_client
python -m lmu_ep_client --output-dir ./sessions --debug
python -m lmu_ep_client --list-registrations
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir DIR` | `./sessions/` | Directory for JSON output files |
| `--team NAME` | auto-detect player car | Track the car whose vehicle/entry name contains `NAME` |
| `--driver NAME` | auto-detect player car | Track the car currently driven by `NAME` |
| `--slot ID` | auto-detect player car | Track a specific car slot ID from `--list-teams` |
| `--list-teams` | off | List active LMU cars and slot IDs, then exit |
| `--api-key KEY` | off | Bearer API key for live tracking events; overrides `LMU_EP_API_KEY` and config |
| `--config PATH` | user config path | TOML config file with `api_key` or `[tracking].api_key` |
| `--registration-id UUID` | off | Event registration to publish tracking events against |
| `--practice` | off | Publish API events to a pre-event practice session instead of the race session |
| `--practice-team-member-id UUID` | off | Team member ID to pin the practice session to; required with `--practice` |
| `--list-registrations` | off | List API registrations for the configured API key, then exit |
| `--api-url URL` | production API | Override the tracking API base URL |
| `--debug` | off | Enable debug logging to stderr |

## Output

One JSON file per session, written to the output directory:

```
sessions/2026-04-02_14-31-12_LeMans24h_Race_1.json
```

The file is flushed on every pit stop completion and every 30 seconds while a stint is active. A final flush runs on `Ctrl+C`.

## Tracking API

When an API key and `--registration-id` are provided, the client mirrors live tracking events to the API while continuing to write the local JSON session file. API keys are resolved in this order:

1. `--api-key KEY`
2. `LMU_EP_API_KEY`
3. Config file

The default config file is `%APPDATA%\lmu-ep-client\config.toml` on Windows and `$XDG_CONFIG_HOME/lmu-ep-client/config.toml` or `~/.config/lmu-ep-client/config.toml` elsewhere. Use `--config PATH` to point at another TOML file:

```toml
[tracking]
api_key = "lmu_..."
```

API publishing uses a durable local outbox at:

```
sessions/tracking-outbox.json
```

If `--output-dir` is set, the outbox is stored in that directory instead.

Every API event is written to the outbox before the network request is attempted. Each queued event has a stable idempotency key that is reused on retries, so a restart or network drop does not create a new logical event. After the API accepts an event, the outbox marks it with `sent_at`; unsent events are replayed on startup and retried during polling with exponential backoff.

This means local logging remains the source of truth, and pit/driver events are not discarded just because the network is temporarily unavailable.

### Practice sessions

Use `--practice` to publish to a pre-event practice session for one driver:

```
lmu-ep-client.exe --registration-id <uuid> --practice --practice-team-member-id <uuid>
```

On startup the client creates or resumes the practice session for that
registration/team-member pair. All normal driver and pit events are posted with
`practiceSessionId`, and shutdown marks the practice session ended instead of
ending the race tracking session. Practice startup does not require a race
tracking session to exist for the registration; the provided
`--practice-team-member-id` is used as the driver identity for practice events.

Practice mode also sends `lap_completed` events when `mTotalLaps` increments
or when the vehicle lap distance wraps over start/finish, and the local client
is the current driver. The lap-distance fallback catches practice laps that LMU
does not count in `mTotalLaps`, such as invalidated laps. The lap event uses the
last-lap time from scoring (`mLastLapTime`) when available, falling back to the
elapsed-time delta between lap crossings if LMU has not populated `mLastLapTime`
yet. It also includes the current fuel, energy, and tyre-wear snapshot:

```json
{
  "type": "lap_completed",
  "practiceSessionId": "practice-session-uuid",
  "teamMemberId": "team-member-uuid",
  "meta": {
    "lapTimeSeconds": 124.318,
    "tyreWear": {
      "fl": 92.44,
      "fr": 91.71,
      "rl": 87.04,
      "rr": 86.55
    },
    "energyPct": 73.23,
    "fuelLitres": 48.46
  }
}
```

Tyre wear in practice lap events is percent remaining. Because LMU only updates
per-wheel wear reliably for the local/current driver, remote-controlled laps are
not published as `lap_completed` events.

### Tracking events

The client publishes these pit-related API events:

| Event | Moment |
|-------|--------|
| `pit_entered` | Car crosses into pit lane |
| `pit_at_box` | First tick at the pit box (`PIT_STOPPED`, `PIT_EXITING`, or `PIT_GARAGE`) |
| `pit_departed` | Service is complete and the car leaves the box |
| `pit_exited` | Car crosses back onto the track |
| `pitstop` | Rich pit summary emitted at pit exit |

#### Game-time ordering (`etSeconds`)

Every event body includes an `etSeconds` field sourced from LMU's
`mCurrentET` (session-elapsed seconds at the moment the event fired).
Because `mCurrentET` is synchronized across all clients in the same
online session, two teammates observing the same moment publish the same
`etSeconds` — giving the server an authoritative ordering key independent
of per-client wall-clock skew.

`occurredAt` remains the wall-clock time and is still used by the server
for display; `etSeconds` should be preferred for dedup/alignment of
events received from multiple clients. The field is omitted when no
session tick is available (pre-/post-session housekeeping).

For `pit_entered`, `etSeconds` is captured at the actual pit-lane
crossing tick (not at the deferred emit), matching the wall-clock
backdating already done for `occurredAt`. The `pitstop` event and its
follow-up swap `driver_started` carry the same `etSeconds` so they sort
together.

When the local client is the current driver, `pit_at_box` and `pit_departed`
carry a live telemetry snapshot in `meta`:

```json
{
  "fuel_litres": 72.34,
  "energy_percent": 54.32,
  "tyre_wear": {
    "FL": 0.8123,
    "FR": 0.7988,
    "RL": 0.8457,
    "RR": 0.8235
  }
}
```

Tyre wear comes from local wheel telemetry (`mWheels[i].mWear`), which LMU does
not update reliably while a teammate is driving the car remotely. For that
reason, the client omits this live snapshot whenever `mControl` indicates a
remote driver. The `pitstop` summary also omits tyre-change details and
`repair_flag` if either side of the pit stop was remote-controlled, because
those values depend on comparing trustworthy pre- and post-service local
telemetry. Fuel and energy remain included when the poller has a reliable
source for them.

### File structure

```json
{
  "session": {
    "track": "Le Mans 24h",
    "session_type": "Race 1",
    "start_time": "2026-04-02T14:31:12",
    "end_time": "2026-04-02T18:30:00",
    "vehicle": "Porsche 963",
    "vehicle_class": "Hypercar"
  },
  "stints": [
    {
      "stint_number": 1,
      "driver": "Verstappen",
      "start_lap": 0,
      "end_lap": 22,
      "total_laps": 22,
      "start_time_elapsed": 0.0,
      "end_time_elapsed": 3600.0,
      "stint_duration_seconds": 3600.0,
      "fuel": {
        "start_litres": 110.0,
        "end_litres": 12.3,
        "litres_used": 97.7,
        "litres_per_lap": 4.44,
        "capacity": 110.0
      },
      "energy": {
        "start_percent": 100.0,
        "end_percent": 5.2,
        "used_percent": 94.8,
        "percent_per_lap": 4.31
      },
      "pit_stop": {
        "pit_enter_elapsed": 3600.0,
        "pit_stand_elapsed": 3612.0,
        "pit_depart_elapsed": 3635.0,
        "pit_exit_elapsed": 3640.0,
        "standing_time_seconds": 23.0,
        "total_pit_time_seconds": 40.0,
        "fuel_added_litres": 97.7,
        "energy_added_percent": 94.8,
        "post_fuel_litres": 110.0,
        "post_energy_percent": 100.0,
        "repair_flag": false,
        "driver_change": true,
        "new_driver": "Hamilton",
        "tyres": {
          "FL": { "changed": true, "old_wear": 0.42, "old_compound": "Hard", "new_compound": "Medium", "new_wear": 1.0 },
          "FR": { "changed": true, "old_wear": 0.41, "old_compound": "Hard", "new_compound": "Medium", "new_wear": 1.0 },
          "RL": { "changed": true, "old_wear": 0.38, "old_compound": "Hard", "new_compound": "Medium", "new_wear": 1.0 },
          "RR": { "changed": true, "old_wear": 0.37, "old_compound": "Hard", "new_compound": "Medium", "new_wear": 1.0 }
        }
      }
    }
  ]
}
```

For remote-controlled stints, `tyre_wear` is serialized as `null`. For pit
stops where tyre and repair data cannot be trusted, `pit_stop.tyres` is an
empty object and `repair_flag` is omitted.

## Building the executable

Install runtime + dev dependencies into the *same* environment PyInstaller
runs from — otherwise the bundle will be missing third-party packages like
`questionary` and fail at startup with `ModuleNotFoundError`. The simplest
recipe is a project-local venv:

```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\pyinstaller.exe lmu-ep-client.spec --noconfirm
```

Output: `dist/lmu-ep-client.exe` — single-file executable, no Python install required on the target machine.

## Development

```
pip install -e ".[dev]"
pytest
```

The `vendor/` directory contains `pyLMUSharedMemory` — the shared memory interface mapping. When working with any shared memory fields, check [vendor/pyLMUSharedMemory/lmu_data.py](vendor/pyLMUSharedMemory/lmu_data.py) for field names, types, and documented enum values.
