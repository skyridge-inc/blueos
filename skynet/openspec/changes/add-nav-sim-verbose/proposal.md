## Why

When debugging the `skynet nav sim` loop against a real Pixhawk, the
operator has no visibility into what the sim is doing tick-by-tick. The
only output is the initial config table and the final stop-reason line.
If the rover isn't tracking the mission or the heading seems wrong, the
operator has to guess whether the issue is in the kinematic model, the
servo normalization, the GPS_INPUT injection, or the autopilot's EKF.

A `--verbose` / `-v` flag that prints per-tick state (position, heading,
speed, servo PWM → normalized, and any state transitions like arm/disarm
or mission-reached) gives the operator a live telemetry feed without
having to connect a second tool.

## What Changes

- Add `--verbose` / `-v` boolean flag to the `nav sim` command.
- When enabled, print a one-line status per GPS_INPUT tick showing:
  lat, lon, heading, speed (m/s), left/right normalized throttle, and
  the raw servo PWM values.
- Print state transitions (armed, disarmed, mission-item-reached) as
  they happen regardless of the `--verbose` flag — these are always
  useful. Currently only the "armed" banner prints; add the others.
- No changes to the kinematic model, emitter, or stop watcher.

## Impact

- Affected spec: `provisioning-cli` (MODIFIED Requirement: `nav sim` Command)
- Affected code: `src/skynet/cli.py` only — the verbose output is purely
  a presentation concern in the CLI layer.
- No new modules, exceptions, or dependencies.
