# LMU EP Client GUI Launcher Design

## Purpose

Teammates struggle with the command-line workflow, especially remembering the right flags and selecting the correct registration, practice mode, and practice driver. The first GUI should be a small internal launcher that removes those mistakes without replacing the existing CLI.

The GUI is not a live dashboard in the first version. It starts the same tracking client with correct settings and shows enough status to make setup and startup understandable.

## Users

The first version is for internal teammates. It should be practical, clear, and hard to misuse, but it does not need public-product polish.

## Entry Point

`lmu-ep-client.exe` keeps the current CLI behavior whenever arguments are passed.

When launched with no arguments, the executable opens the GUI launcher instead of starting the CLI defaults. This lets double-click users get a window while scripts and power users keep using commands such as:

```powershell
lmu-ep-client.exe --registration-id <uuid> --practice --practice-team-member-id <uuid>
```

## Technology Choice

Use PySide6/Qt for the GUI.

Reasons:

- Better fit for a richer Windows desktop app than a minimal Tkinter window.
- Good path toward a later live status dashboard.
- Native widgets for forms, dropdowns, status panels, file pickers, and logs.
- Acceptable packaging complexity for an internal tool.

The PyInstaller build must include PySide6/Qt runtime files. Keep a console-capable executable so argument-based CLI usage still prints output and errors in terminals. No-argument launches open the GUI window from the same executable.

## Main Window

The launcher has one main window with these sections:

- API
- Event selection
- Mode selection
- Practice driver selection
- Advanced settings
- Status and actions

### API

The API section contains:

- API key password field.
- Save key button.
- Refresh registrations button.
- Clear validation messages when the key is missing or invalid.

The API key is saved to the existing config location and format already supported by the CLI:

```toml
[tracking]
api_key = "lmu_..."
```

The GUI reads and writes the same default config path as the CLI. It may prefill from an explicit environment variable if present, but saving always writes the default config file.

### Event Selection

After a valid API key is available, the GUI fetches registrations using the existing `TrackingClient.list_registrations()` behavior.

The event dropdown displays human-readable registration details:

- Start time
- Track and layout
- Car
- Event title when available
- Whether a tracking session already exists

The selected registration supplies the `registration_id` passed to `run(...)`.

### Mode Selection

The mode control offers:

- Race
- Practice

Race mode starts tracking against the selected registration without a practice team member.

Practice mode reveals or enables the practice driver dropdown and requires a driver selection before Start is enabled.

### Practice Driver Selection

When Practice mode is selected, the GUI fetches team members for the selected registration using `TrackingClient.list_team_members(registration_id)`.

The dropdown displays:

- User name
- Team role when available
- LMU driver name when available

The selected member supplies `practice_team_member_id` passed to `run(...)`.

### Advanced Settings

Advanced settings are visible but secondary. They include:

- Output directory, defaulting to the existing `./sessions/` behavior.
- Optional tracking target fields matching CLI behavior: team name, driver name, or slot ID.
- Debug logging toggle.

The first implementation can keep these controls compact and avoid adding new behavior beyond the existing CLI flags.

## Starting And Running

The Start button validates:

- API key exists if API-backed tracking is selected.
- Registration is selected.
- Practice driver is selected when in Practice mode.
- Slot ID is numeric if provided.

On Start, the GUI invokes the existing client logic directly instead of shelling out to a separate process. It passes the same values currently passed by `cli.main()` into `poller.run(...)`:

- `output_dir`
- `team_name`
- `driver_name`
- `slot_id`
- `api_url`
- `api_key`
- `registration_id`
- `practice_team_member_id`

The polling loop should run on a background worker thread so the Qt window stays responsive. Stop should request graceful shutdown with the same final flush behavior that `Ctrl+C` gives CLI users.

## Status And Errors

The first GUI shows a compact status area:

- API key saved or missing.
- Registrations loaded count.
- Selected registration.
- Practice driver selection state.
- LMU shared memory waiting/running/error state.
- Output directory.
- Current running/stopped state.

Errors should be shown in the window with actionable text:

- Invalid API key or API request failed.
- No registrations found.
- No team members found for practice.
- LMU is not running or shared memory is unavailable.
- Output directory cannot be created or written.

Debug details can go to an expandable log area or a log file. The first version should not require teammates to inspect a terminal.

## Reuse And Boundaries

The GUI should reuse existing modules instead of duplicating business logic:

- `cli._resolve_api_key()`, `_default_config_path()`, and `_config_api_key()` for config behavior.
- `TrackingClient` for API calls.
- Existing registration and team member formatting ideas from `interactive.py`.
- `poller.run(...)` for tracking behavior.

New GUI-specific code lives in `src/lmu_ep_client/gui.py`, with a small entrypoint branch in `cli.main()` that chooses GUI only when `len(sys.argv) == 1`.

Shared memory field work is not expected for the first GUI beyond existing polling behavior. If future GUI status reads shared memory directly, implementation must first verify field names and enum values in `vendor/pyLMUSharedMemory/lmu_data.py`.

## Packaging

The package dependencies add `PySide6`.

The PyInstaller spec needs updates to collect PySide/Qt runtime assets. The executable should support two modes:

- No args: launch GUI window.
- Args present: run existing CLI path.

The build should be tested by running both the source entrypoint and the packaged executable paths.

## Testing

Focused automated tests should cover:

- No-argument entrypoint chooses GUI launcher.
- Argument-based entrypoint preserves existing CLI behavior.
- API key save/load writes the existing config format.
- Registration selection maps to the correct `registration_id`.
- Practice selection requires and passes `practice_team_member_id`.
- Start validation blocks incomplete states.

Manual verification should cover:

- Double-click/no-args window startup on Windows.
- Existing commands still work with arguments.
- Packaged executable includes Qt runtime files.
- GUI can save an API key, refresh registrations, select Race, select Practice, and start the client.

## Deferred

These are intentionally not part of the first version:

- Full live telemetry dashboard.
- Rich session charts.
- Account management.
- Automatic install/update flow.
- Public onboarding polish.
- Replacing the CLI interactive prompts.
