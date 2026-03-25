# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

BlueOS configuration and tooling for Skyridge autonomous mower fleet. Contains:

- **`mower_provisioner/`** — Python CLI (`mower-provision`) for MAVLink fleet provisioning of ArduPilot Rover/Mower vehicles on Pixhawk controllers. This is the primary codebase under active development.
- **MediaMTX configs** (`mediamtx*.yml`) — RTSP video streaming relay for onboard cameras.
- **`mavlink-camera-manager`** — Camera manager binary + settings for BlueOS video pipeline.
- **`docs/`** — BlueOS ArduPilot parameter management documentation (RC/PWM config).
- **`Dockerfile`** — Minimal Ubuntu dev container.

## Build & Test Commands

All commands run from `mower_provisioner/`:

```bash
# Install dependencies (uses uv, not pip)
cd mower_provisioner && uv sync

# Run all tests
uv run pytest

# Run tests verbose with short tracebacks
uv run pytest --tb=short -v

# Run a single test file
uv run pytest tests/test_config.py

# Run a single test class or method
uv run pytest tests/test_params.py::TestDiffParams::test_mixed_changes

# Install CLI globally for manual testing
uv tool install .

# CLI entry point (after install)
mower-provision --help
```

No linter or formatter is configured yet.

## Architecture — mower_provisioner

Python 3.11+, managed with `uv` and `hatchling`. Entry point: `mower_provisioner.cli:app`.

```
mower_provisioner/src/mower_provisioner/
├── cli.py         — Typer CLI commands (connect, read, write, diff, sync, backup)
├── config.py      — .param file I/O + CALIBRATION_PARAMS exclusion list
├── connection.py  — pymavlink context manager (heartbeat wait, connect/close)
├── params.py      — fetch_all_params, write_params, diff_params + ParamDiff dataclass
├── exceptions.py  — Exception hierarchy (all inherit MowerProvisionerError)
└── __init__.py    — Version string
```

**Key design decisions:**

- **Calibration protection**: `config.CALIBRATION_PARAMS` (frozenset) lists ~70 vehicle-specific params (IMU, compass, battery, RC, SYSID) excluded by default from all operations. The `--include-calibration` flag overrides this. This is the core safety mechanism — do not weaken it without explicit intent.
- **Connection management**: `connection.mavlink_connection()` is a context manager that handles connect → heartbeat wait → yield → close. All CLI commands use it.
- **Param fetch uses gap detection**: `params.fetch_all_params()` requests all params, then re-requests missing indices after a 2-second gap. Not a simple "request and wait" — the index-tracking logic matters.
- **Write uses retry + ack**: `params.write_params()` sends each param individually, waits for PARAM_VALUE ack, retries up to 3 times.
- **Float comparison**: `params.EPSILON = 1e-6` used in `diff_params()` for tolerance.

**Dependencies**: `typer` (CLI framework), `rich` (terminal UI/progress), `pymavlink` (MAVLink protocol). Dev: `pytest`, `pytest-mock`.

**Tests**: Mock the MAVLink connection (`conftest.py::mock_conn`). Tests cover config I/O, calibration filtering, param diff logic, write ack/retry, and fetch with progress callbacks. No integration tests against real hardware.

## .param File Format

Standard ArduPilot format — one param per line, comma-separated (`NAME,value`). Also supports space-separated. Comments with `#`. Integer-valued floats written without decimals (e.g., `3` not `3.0`).

## Hardware Context

- Target: Pixhawk Orange controllers running ArduPilot Rover firmware
- Default connection: USB serial `/dev/ttyACM0` at 115200 baud
- Protocol: MAVLink 2 via pymavlink
- Fleet size: 10+ mowers, hence the template-driven provisioning approach
