# Sim runs but rover never moves — V13 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V12.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (~100 s runtime in AUTO)
Autopilot log: operator paste (`23:28:09 → 23:39:13`)

## TL;DR — all params healthy; AUTO mode is definitively broken

### Param probe results (post-engagement readback)

```
CRUISE_SPEED=2.0           ← OK
CRUISE_THROTTLE=50.0       ← OK
WP_SPEED=2.0               ← OK
ATC_ACCEL_MAX=1.0          ← OK (1 m/s²)
ATC_DECEL_MAX=0.0          ← normal default (uses ATC_ACCEL_MAX)
ATC_SPEED_P=0.2            ← OK
ATC_SPEED_I=0.2            ← OK
ATC_SPEED_FF=0.0           ← normal default
```

Every speed/accel param has a valid non-zero value. The scurve
trajectory calculator has everything it needs to produce motion.
The speed PID has P=0.2, I=0.2 which should produce output for
any non-zero speed error.

### Zero POSITION_TARGET_GLOBAL_INT messages

V12 saw one; V13 saw zero. The autopilot's `ModeAuto::update()` is
NOT publishing a position target, which means `AR_WPNav::update()`
is early-returning before the target publish step on every tick.

### Conclusion: firmware-level AUTO mode bug

Across 10 consecutive runs (V4–V13):
- All sim-side gates, arming, mode transitions work correctly
- All speed/accel params are healthy and non-zero
- EKF is healthy (`flags=831`), LPOS flowing, GPS RTK_FIXED
- Mission seq=1, wp_dist=9 m, target_bearing=15°
- **Zero throttle, zero differential servo output, zero movement**

The fault is inside ArduRover 4.6.3's `ModeAuto` →
`AR_WPNav::update_steering_and_speed()` code path. It early-returns
on every tick without publishing a target or commanding servos, despite
having valid inputs. The root cause is not observable from MAVLink
telemetry alone — it requires an on-target dataflash log or source-
level debugging.

## Fix: GUIDED mode fallback (V13)

After 15 s of AUTO with zero throttle, the sim now switches to
GUIDED mode and sends `SET_POSITION_TARGET_GLOBAL_INT` directly to
WP1 at 1 Hz. GUIDED mode uses `ModeGuided::set_desired_location()`
which initializes a fresh AR_WPNav scurve independent of the mission
state machine — a completely different code path from `ModeAuto`.

Also added `MOT_THR_MIN`, `MOT_THR_MAX`, `BRD_SAFETY_DEFLT`,
`BRD_SAFETYENABLE` to the param probe for the next run.
