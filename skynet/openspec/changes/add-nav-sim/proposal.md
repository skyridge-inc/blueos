## Why

`skynet nav plan` generates missions, `skynet nav upload` pushes them to the
autopilot, but there is currently no way to *exercise* those missions against
a real Pixhawk Cube Orange+ without driving the vehicle outside and waiting
for a real ArduSimple RTK fix. That makes the dev loop slow and risky: every
bench-test iteration requires moving hardware, finding sky, and burning
batteries.

The idea is a software-in-the-loop GPS/heading simulator that runs on the
BlueOS companion computer, talks to the Pixhawk over the same MAVLink proxy
(`tcp:<host>:5760`) every other skynet MAVLink command uses, subscribes to
the autopilot's `SERVO_OUTPUT_RAW` stream, runs a skid-steer kinematic model,
and injects the resulting position and heading back as `GPS_INPUT` messages.
To ArduRover, the loop looks like a real ArduSimple UM982 dual-antenna RTK
GPS reporting position and true heading. The autopilot can then fly an
uploaded mission in AUTO mode with a real Pixhawk in the loop — real IMUs,
real EKF, real motor controllers — but simulated positioning.

This closes the `nav plan → nav upload → nav sim → observe` bench loop
without a single field test.

## What Changes

- **Add `nav sim` subcommand** under the existing `nav` Typer group that
  downloads the current mission from the autopilot via MAVLink, validates
  the vehicle is a skid-steer ArduRover, saves the autopilot's EKF/GPS
  source params to a crash-recovery sidecar, rewrites them for external GPS
  input, then runs a closed-loop kinematic simulation that feeds `GPS_INPUT`
  to the Pixhawk while watching `SERVO_OUTPUT_RAW` for motor commands.
- **New `mission-download` capability** covering the inverse of the existing
  `mission-upload` state machine: `MISSION_REQUEST_LIST` → `MISSION_COUNT`
  → `MISSION_REQUEST_INT` → `MISSION_ITEM_INT` → `MISSION_ACK`.
- **New `gps-simulator` capability** covering the kinematic model, servo
  PWM normalization, `GPS_INPUT` emission loop, crash-safe param
  save/restore, and the stop-condition watcher (DISARM or
  `MISSION_ITEM_REACHED` on the last seq, plus optional `--duration` and
  SIGINT).
- **Extend `provisioning-cli`** with the `nav sim` command requirement.
- Use the same connection plumbing (`mavlink_connection()`) as every other
  MAVLink skynet command — no new transport.
- New exceptions `MissionDownloadError`, `GpsSimError`, and
  `FrameMismatchError` joining the `MowerProvisionerError` hierarchy.

## Impact

- Affected specs:
  - `provisioning-cli` (ADDED Requirement: `nav sim` Command)
  - `mission-download` (NEW capability)
  - `gps-simulator` (NEW capability)
- Affected code (implementation deferred to `/opsx:apply add-nav-sim`):
  - `src/skynet/cli.py` — new `nav_sim` command registered on `nav_app`
  - `src/skynet/mission_download.py` — NEW: mission-download state machine
  - `src/skynet/gps_sim.py` — NEW: kinematic model + MAVLink I/O loop
  - `src/skynet/exceptions.py` — NEW `MissionDownloadError`, `GpsSimError`,
    `FrameMismatchError`
  - `tests/test_mission_download.py` — NEW: mocked-MAVLink state-machine tests
  - `tests/test_gps_sim.py` — NEW: kinematic-model, param save/restore, and
    CLI smoke tests
- No changes to calibration safety, BlueOS HTTP surface, parameter flows,
  mission upload, or nav planning.
- **Not a field-use tool.** The spec explicitly disclaims altitude, fences,
  sensor noise, terrain effects, and outdoor operation. It is a dev-loop
  accelerator, not a flight-sim replacement.
