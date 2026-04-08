# PRD: Mower Provisioner — MAVLink Fleet Provisioning CLI

## Problem Statement

Fleet provisioning of ArduPilot Rover/Mower vehicles on Pixhawk Orange controllers currently requires manual parameter management via QGroundControl or Mission Planner. This is slow (~30 min/vehicle) and error-prone for fleets of 10+ mowers.

## Goals

1. **Reduce provisioning time** from ~30 min to <5 min per vehicle
2. **Eliminate manual errors** through template-driven parameter management
3. **Support fleet consistency** via golden templates and diff-based sync
4. **Preserve vehicle-specific calibration** data during template writes

## Non-Goals

- Firmware flashing (handled by Mission Planner / BetaFlight)
- Mission/waypoint management
- Real-time telemetry monitoring
- Multi-vehicle simultaneous provisioning (future)

## User Stories

1. As a fleet operator, I want to **read all parameters** from a mower so I can create a baseline template.
2. As a fleet operator, I want to **write a template** to a new mower so I can provision it in minutes.
3. As a fleet operator, I want to **diff a template** against a mower to see what's different.
4. As a fleet operator, I want to **sync only changed parameters** to minimize write time and risk.
5. As a fleet operator, I want to **backup** a mower's complete configuration before making changes.
6. As a fleet operator, I want **calibration data protected** by default so template writes don't destroy sensor calibration.

## Parameter Exclusion Policy

Calibration parameters (IMU offsets/scales, compass offsets, battery calibration, RC min/max/trim, SYSID_THISMAV) are excluded from read/write/diff/sync operations by default. Users can include them with `--include-calibration`.

## Connection Specification

- **Default**: USB serial `/dev/ttyACM0` at 115200 baud
- **Supported**: Any MAVLink-compatible connection string (UDP, TCP, serial)
- **Protocol**: MAVLink 2 via pymavlink
- **Heartbeat timeout**: 10 seconds

## Success Metrics

- All 6 CLI commands functional with Pixhawk Orange over USB
- Round-trip read → write → diff shows zero differences
- Calibration params preserved across template writes
- Unit tests pass with >90% coverage on config and params modules
