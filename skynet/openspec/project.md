# Project: skynet

## Purpose
Skynet is a Python CLI (`mower-provision` / `skynet`) for fleet provisioning of Skyridge autonomous mowers. It manages two device surfaces over two transports:

1. **ArduPilot Rover/Mower autopilot** on Pixhawk Orange controllers — accessed via MAVLink (USB serial or TCP). Provides parameter read/write/diff/sync/backup with calibration safety.
2. **BlueOS companion computer** — accessed via HTTP REST APIs (Beacon, Kraken, Bag of Holding, Cable Guy, Wifi Manager, file browser). Provides extraction and upload of full device configuration (identity, extensions, network, MediaMTX RTSP relay) as YAML.

The goal is repeatable, safe provisioning of a fleet of 10+ mowers from version-controlled templates without overwriting per-vehicle calibration.

## Tech Stack
- **Language**: Python 3.11+
- **Package manager**: `uv` + `hatchling` (never `pip`)
- **CLI framework**: Typer with Rich for terminal output (tables, progress bars)
- **MAVLink**: `pymavlink` (MAVLink 2)
- **HTTP**: `httpx` (sync client)
- **Serialization**: PyYAML, plain `.param` files
- **Testing**: `pytest` + `pytest-mock`. Mocked MAVLink/HTTP — no hardware integration tests.

## Conventions
- Calibration parameters (`config.CALIBRATION_PARAMS`, ~70 entries covering IMU, compass, battery, RC, SYSID, runtime stats, baro ground pressure, gyro caltemps) are excluded from all read/write/diff operations by default. The `--include-calibration` flag is the only override. `backup` always includes them; `sync` passes `include_calibration=True` to `write_params` because diff has already filtered.
- `.param` files use comma-separated `NAME,value` (space-separated also accepted on read). Integer-valued floats are written without decimals.
- Float comparison uses `EPSILON = 1e-6`.
- All MAVLink commands flow through the `mavlink_connection()` context manager (connect → wait_heartbeat → yield → close).
- Connection defaults: `/dev/ttyACM0` at 115200 baud (USB) or `tcp:<host>:5760` (BlueOS).
- Exception hierarchy is rooted at `MowerProvisionerError`; connection, parameter, file, and BlueOS errors form separate branches.
- No linter or formatter is configured.

## Out of Scope
- Real-hardware integration tests
- ArduPilot firmware flashing
- Mission/waypoint planning (handled by the sibling `nav_planning` project)
