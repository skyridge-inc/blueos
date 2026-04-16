# Sim runs but rover never moves — V12 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V11.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (2021 lines, ~57 s runtime)
Autopilot log: operator paste (`23:28:09 → 23:29:53`)

## TL;DR — nav controller IS alive, published 1 valid target, then stopped

### Breakthrough: `POSITION_TARGET_GLOBAL_INT` arrived once

```
pos_target: lat=40.3007362 lon=-83.0381200 alt=0.00m mask=0xFDF8
```

This is the FIRST time across V4–V12 that we've seen the autopilot
publish a position target. The coordinates match WP1 exactly. The
type_mask `0xFDF8` = position-only (lat/lon/alt active, velocity
/accel/yaw ignored).

**The nav controller is NOT dead.** It ran at least once, computed
the correct target, and published it. Then it stopped — only 1
message arrived in a 45 s session at 1 Hz subscription. Something
causes `AR_WPNav` to early-return on all subsequent ticks after the
first computation.

### Auto-arm confirmed working

```
EKF healthy (t=10.5s, flags=831). AUTO mode can now drive
Auto-arm command sent.
GPS lock established. Autopilot is armed.
Forced mode=HOLD. Switching to AUTO once EKF reports flags=831.
Engaged HOLD→AUTO → MISSION_START @ seq=1.
```

Full automated flow — no QGC interaction required.

### Autopilot log: clean run with one late reboot

Autopilot log shows 3 boots (23:28:09, 23:28:14, 23:28:46) during
setup, then a fourth at 23:29:53 (`ArduPilot Ready`, `AHRS: DCM
active`) about 50 s into the session. The sim's telemetry continued
flowing through the BlueOS proxy, so the sim didn't notice the
reboot. No `EKF3 waiting for GPS config data` messages in this
session — the V11 EKF regression did not recur.

### Hypothesis: scurve trajectory degenerates to zero length

The single POSITION_TARGET message proves `AR_WPNav::update()` ran
once and produced a valid target. On subsequent ticks, it
early-returned — most likely because
`_reached_destination` latched `true` after the scurve trajectory
computed a zero-length path.

In ArduRover 4.6.3's `AR_WPNav::set_desired_location()`:

1. Origin is set from the autopilot's current position estimate
2. Destination is set from the mission waypoint
3. If the scurve's `_track_length` (distance from origin to
   destination) is below a threshold, the trajectory reports
   "reached" immediately

The sim's spawn is 10 m from WP1, but the autopilot's internal
position estimate (from `AHRS::get_location()`) might differ from
the GPS_INPUT position due to EKF smoothing. If the EKF's position
is closer to WP1 than expected (e.g., due to the HOME→WP1 track
extrapolation or origin re-centering), the scurve origin could end
up near WP1, producing a near-zero track.

**What would prove/disprove this:** the param probe added in this
version reads `CRUISE_SPEED`, `WP_SPEED`, `ATC_ACCEL_MAX`,
`ATC_DECEL_MAX`, `ATC_SPEED_P`, `ATC_SPEED_I`, `ATC_SPEED_FF`
after engagement. If all are non-zero, the speed controller has
valid gains and the issue is in the trajectory itself. If any are
zero (especially `ATC_ACCEL_MAX`), the scurve can't accelerate.

## Changes implemented

1. **Post-engagement param probe** — reads 8 speed/accel params via
   `PARAM_REQUEST_READ` immediately after HOLD→AUTO engagement and
   logs them. Any zero value is flagged with `[ZERO!]`. This runs
   next session and will appear as:
   ```
   Post-engage param probe:
     CRUISE_SPEED=2.0
     WP_SPEED=2.0
     ATC_ACCEL_MAX=???
     ...
   ```
2. **Yaw sweep removed** (carried forward from V11).
3. **Auto-arm** (carried forward from V11).
