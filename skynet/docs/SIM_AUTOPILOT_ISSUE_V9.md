# Sim runs but rover never moves — V9 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V8.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (10886 lines, ~304 s runtime)
Autopilot log: operator paste (`22:25:32 → 22:26:00`)

## TL;DR — AUTO mode is definitively broken on this firmware; GUIDED bypass needed

All sim-side gates and transitions work perfectly:

- V4 mission upload: retried on `MAV_MISSION_RESULT=15`, verified 5 items.
- V4 VISO late write: `Applied late sim params: VISO_DELAY_MS, VISO_POS_M_NSE, VISO_YAW_M_NSE`.
- V7 EKF-only gate: `EKF healthy (t=10.4s, flags=831)`.
- V8 decoupled gate: `Engaged HOLD→AUTO → MISSION_START @ seq=1` at t=57.3s (3s after arm detected, despite arm-before-EKF ordering).
- Only 2 HOLD re-assertions (down from 9 in V7).
- `Mission current seq: 1` — mission advanced.

**The rover was in `mode=AUTO`, armed, `flags=831`, `wp_dist=5 m`,
`target_bearing=15°` for 245 continuous seconds (t=58 → t=303).
`throttle=0%` the entire time. Zero servo movement.**

---

### Definitive evidence: AR_WPNav is not producing a target

V6 subscribed to `POSITION_TARGET_GLOBAL_INT` at 1 Hz. In 245 s of
AUTO mode, **zero messages arrived** — no `pos_target:` lines in the
log. This message is published by `ModeAuto::update()` when the nav
controller is actively computing a target position. Its absence means
one of:

1. **`ModeAuto` sub-state is not `WP`** — the mission state machine
   is in `STOP`, `WAIT`, or `REACHED` sub-state and has exited the
   navigation loop.
2. **`AR_WPNav::update()` is early-returning** before publishing a
   target, due to an internal guard (e.g. `_reached_destination` is
   True, or `_desired_speed` is zero, or the scurve trajectory is
   degenerate).
3. **ArduRover 4.6.3 does not publish `POSITION_TARGET_GLOBAL_INT`
   from AUTO mode** at all (only GUIDED). In this case the absence is
   not diagnostic.

Candidate (1) or (2) are most likely. The repeating "Mission: 1 WP"
prints in prior logs suggested the mission state machine was being
reset multiple times — each reset can leave `_reached_destination`
in an unpredictable state.

---

### Root-cause hypothesis: ModeAuto scurve init failure is permanent

Across V4–V9 (six runs), the pattern is identical once AUTO engages:

| Signal | Value | Interpretation |
|--------|-------|----------------|
| `mode` | AUTO | correct |
| `flags` | 831 | EKF healthy, POS_HORIZ_ABS |
| `mission seq` | 1 | advanced past home |
| `wp_dist` | 5 m | non-zero, > WP_RADIUS |
| `target_bearing` | 15° | autopilot knows WHERE the WP is |
| `nav_bearing` | 0° | nav controller NOT steering toward it |
| `xtrack_err` | 0 m | nav controller idle (no cross-track) |
| `throttle` | 0% | no throttle command |
| `POSITION_TARGET` | absent | AR_WPNav not computing target |
| `SERVO_OUTPUT_RAW` | 1500/1500 | neutral PWM |

`nav_bearing=0°` with `target_bearing=15°` has been constant since
V3. Combined with the absent POSITION_TARGET, the evidence says:
**the autopilot's navigation controller (AR_WPNav) is not engaged.**

In ArduRover 4.6.3, `ModeAuto::update()` delegates to
`AR_WPNav::update_steering_and_speed()` when the sub-mode is
`Submode_WP`. That function's first action is to compute the
desired speed from the scurve trajectory. If the scurve was
never initialised (because `set_desired_location` silently failed
when ModeAuto::_enter ran before the EKF had a valid origin), the
scurve produces `_desired_speed = 0` and the function returns
without publishing a target or commanding throttle.

The sim's HOLD→AUTO cycle (V5) forces `ModeAuto::_enter` to re-run
against a healthy EKF, but if the autopilot's `AP_Mission` is in a
state where `start_or_resume()` doesn't call `set_desired_location`
(e.g. because `_nav_cmd` is already populated from a prior entry),
the re-enter path skips scurve init entirely.

**This is a firmware bug**, not a sim bug. The fix is to bypass
AUTO mode entirely.

---

## Fix implemented: GUIDED mode fallback

When the sim detects that AUTO mode has been engaged for ≥ 15 s
with `wp_dist > WP_RADIUS` and throttle has never left 0%, it
switches to GUIDED mode and directly commands the autopilot to
navigate to the target waypoint via `SET_POSITION_TARGET_GLOBAL_INT`.

GUIDED mode:
- Uses `ModeGuided::set_desired_location()` which initialises
  AR_WPNav with a fresh scurve from the current position to the
  target — no dependency on mission state machine state.
- Does NOT go through `AP_Mission::start_or_resume()` or
  `ModeAuto::_enter`, avoiding the stale-init code path entirely.
- Re-sends the target periodically (every 3 s) to keep the
  autopilot's guided timeout from expiring.

The fallback is implemented as a watchdog timer in the main loop:
after engagement, track whether any non-zero throttle has been
observed. If 15 s pass with zero throttle and `wp_dist >
WP_RADIUS`, transition to GUIDED targeting the next mission
waypoint.

This is a pragmatic workaround. The firmware bug should be reported
upstream.
