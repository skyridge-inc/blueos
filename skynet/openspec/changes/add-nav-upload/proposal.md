## Why

The `skynet nav plan` command generates QGC WPL 110 `.waypoints` files (e.g.,
`./output/700_long_mower1.waypoints`) from KML field boundaries, but there is
currently no way to push those files onto the autopilot from the CLI. Operators
must open Mission Planner / QGroundControl, connect manually, and load the
mission file by hand — which is slow, error-prone, and breaks the otherwise
end-to-end "file in, mower running" provisioning story.

A companion upload command closes that gap: it reads a `.waypoints` file and
uploads it to a Pixhawk Cube Orange+ running ArduPilot Rover over MAVLink,
using the existing BlueOS mavlink proxy (`tcp:<host>:5760`) that every other
MAVLink-touching command in this CLI already uses.

## What Changes

- **Add `nav upload` subcommand** under the existing `nav` Typer group that
  reads a QGC WPL 110 `.waypoints` file, opens a MAVLink connection using the
  shared `mavlink_connection()` context manager (same transport as
  `misc connect`), and uploads the mission to the autopilot via the MAVLink
  mission-upload protocol (`MISSION_COUNT` → `MISSION_REQUEST(_INT)` →
  `MISSION_ITEM_INT` → `MISSION_ACK`).
- **Add a `mission-planning` capability requirement** for a `read_waypoints`
  helper that returns the waypoint list including the home row (the existing
  `read_waypoints` skips home, which loses information the autopilot needs).
- **Add a new `mission-upload` capability** covering the MAVLink mission
  protocol state machine, retry behavior, and error mapping.
- Provide `--device` / `-d`, `--baud` / `-b`, `--yes` / `-y`, and `--dry-run`
  options consistent with the other MAVLink-mutating commands; default device
  remains `/dev/ttyACM0` and can be pointed at the BlueOS proxy via
  `-d tcp:<host>:5760` or the `MOWER_DEVICE` env var.
- Map MAVLink mission-protocol failures onto the existing
  `MowerProvisionerError` hierarchy (new `MissionUploadError`).

## Impact

- Affected specs:
  - `provisioning-cli` (ADDED Requirement: `nav upload` Command)
  - `mission-planning` (MODIFIED Requirement: QGC WPL 110 Waypoint File I/O —
    extend `read_waypoints` to optionally return home)
  - `mission-upload` (NEW capability spec)
- Affected code:
  - `src/skynet/cli.py` — new `nav_upload` command registered on `nav_app`
  - `src/skynet/mission_planning/waypoints.py` — extend reader to return home
  - `src/skynet/mission_upload.py` — NEW: MAVLink mission upload state machine
  - `src/skynet/exceptions.py` — NEW `MissionUploadError`
  - `tests/test_mission_upload.py` — NEW: mocked-MAVLink upload tests
  - `tests/test_cli.py` (if present) — CLI wiring tests
- No changes to calibration safety, BlueOS HTTP surface, or parameter flows.
