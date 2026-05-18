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
        "repair_flag": false,
        "driver_change": true,
        "new_driver": "Hamilton",
        "tyres": {
          "FL": { "changed": true, "old_wear": 0.42, "old_compound": "Hard", "new_compound": "Medium" },
          "FR": { "changed": true, "old_wear": 0.41, "old_compound": "Hard", "new_compound": "Medium" },
          "RL": { "changed": true, "old_wear": 0.38, "old_compound": "Hard", "new_compound": "Medium" },
          "RR": { "changed": true, "old_wear": 0.37, "old_compound": "Hard", "new_compound": "Medium" }
        }
      }
    }
  ]
}
```

## Building the executable

Requires PyInstaller (`pip install pyinstaller` or install dev dependencies):

```
pip install -e ".[dev]"
pyinstaller lmu-ep-client.spec --noconfirm
```

Output: `dist/lmu-ep-client.exe` — single-file executable, no Python install required on the target machine.

## Development

```
pip install -e ".[dev]"
pytest
```

The `vendor/` directory contains `pyLMUSharedMemory` — the shared memory interface mapping. When working with any shared memory fields, check [vendor/pyLMUSharedMemory/lmu_data.py](vendor/pyLMUSharedMemory/lmu_data.py) for field names, types, and documented enum values.
