## MODIFIED Requirements

### Requirement: nav sim Command — verbose output

The `nav sim` command SHALL accept an additional `--verbose` / `-v`
boolean flag (default `False`).

When `--verbose` is enabled, the command SHALL print a single-line
status to the console after each GPS_INPUT tick. The line SHALL include:
the current simulation time (seconds since loop start), latitude,
longitude, heading (degrees), ground speed (m/s), left and right
normalized throttle values (`[-1.0, +1.0]`), and the raw servo PWM
values for channels 1 and 3.

The output format SHALL be a compact fixed-width line suitable for
terminal streaming at 5 Hz without overwhelming the display:
```
t=  1.2  lat=40.28768272  lon=-83.01473719  hdg=045.3°  spd=0.89m/s  L=+0.50(1750)  R=+0.50(1750)
```

Regardless of `--verbose`, the command SHALL print one-line notices for
the following state transitions as they occur during the sim loop:
- Autopilot armed (already implemented).
- `MISSION_ITEM_REACHED` with the seq number.
- Autopilot disarmed (when the stop watcher trips on DISARM).

The `--verbose` flag SHALL have no effect on the kinematic model,
GPS_INPUT emission, param management, or stop conditions.

#### Scenario: Verbose output per tick
- **WHEN** the operator runs `skynet nav sim -v --yes`
- **THEN** each GPS_INPUT tick prints a status line with lat, lon,
  heading, speed, and servo state
- **AND** the lines stream at the configured `--rate` Hz

#### Scenario: Verbose off by default
- **WHEN** the operator runs `skynet nav sim --yes` without `-v`
- **THEN** no per-tick status lines are printed during the sim loop

#### Scenario: Mission-reached notice
- **WHEN** the autopilot emits `MISSION_ITEM_REACHED(seq=3)` during the
  sim loop
- **THEN** the CLI prints a notice line like `Reached waypoint 3`
  regardless of `--verbose`

#### Scenario: Dry run ignores verbose
- **WHEN** the operator runs `skynet nav sim --dry-run -v`
- **THEN** the dry-run output is unchanged — no per-tick lines are
  printed (there is no loop to tick)
