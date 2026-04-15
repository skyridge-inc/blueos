# Sim runs but rover never moves — V3 analysis

Date: 2026-04-14 (follow-up to `SIM_AUTOPILOT_ISSUE_V2.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1489 lines, ~45 s under healthy-EKF AUTO)
Change in this run: `GPS_INPUT` default bumped from 5 Hz → 15 Hz;
added `stats:` line every 5 s showing achieved send rate +
received `LOCAL_POSITION_NED` density.

## What V3 proves (and what it disproves)

### V3 disproves V2's root-cause

V2 concluded that the autopilot's
`AHRS::get_relative_position_NED_origin_float()` was failing on ~90%
of ticks, suppressing `LOCAL_POSITION_NED` and gating
`AR_PosControl::update()` / `AR_WPNav::advance_wp_target_along_track()`
into their early-return branches. The fix-under-test was raising
GPS_INPUT to 15 Hz.

The new `stats:` lines show the fix worked at that layer:

```
stats: gps_out=14.5Hz ... lpos_in=0/5 (0% of 1Hz sub)      ← pre-EKF-healthy
stats: gps_out=14.3Hz ... lpos_in=0/5 (0% of 1Hz sub)      ← pre-EKF-healthy
stats: gps_out=14.3Hz ... lpos_in=0/5 (0% of 1Hz sub)      ← pre-EKF-healthy
stats: gps_out=12.5Hz ... lpos_in=4/5 (80% of 1Hz sub)     ← HOLD→AUTO cycle
stats: gps_out=14.3Hz ... lpos_in=15/5 (300% of 1Hz sub)   ← post-healthy
stats: gps_out=14.3Hz ... lpos_in=16/5 (320% of 1Hz sub)   ← post-healthy
stats: gps_out=14.3Hz ... lpos_in=15/5 (300% of 1Hz sub)   ← post-healthy
stats: gps_out=14.3Hz ... lpos_in=15/5 (300% of 1Hz sub)   ← post-healthy
```

Once the EKF reaches `flags=831` at t=18.5 s, LOCAL_POSITION_NED
arrives at **~3 Hz**, three times the rate we subscribed to. ArduRover
is emitting it on its own internal stream cadence, which only fires
when `ahrs.get_relative_position_NED_origin_float()` succeeds. At
3 Hz for the full run, that getter is clearly succeeding on the vast
majority of ticks.

**Therefore both V2 candidate failure points are no longer plausible:**

- `AR_PosControl::update()` guard `!AP::ahrs().get_relative_position_NED_origin(...)` — passes.
- `AR_WPNav::advance_wp_target_along_track()` guard on `get_relative_position_NE_origin_float` — passes.

### V3 also reinforces that V1's 4-guard is not clearly firing

The `gps_raw`/`sys`/`lpos` triad confirms, post-EKF-healthy:

- `gps_raw: fix=RTK_FIXED sats=20 hdop=0.50` — `AP::gps().status() >= FIX_3D`.
- `sys: gps=OK ahrs=OK` — autopilot's own sensor-health bits clean.
- `lpos: vx=±0.003 vy=±0.003` — `ahrs.get_velocity_NED()` returning true.
- `ap_pos: lat=40.30069280 lon=-83.03813540` (from `GLOBAL_POSITION_INT`) —
  `ahrs.get_location()` returning true.
- `nav: wp_dist=5m target_bearing=15°` — `_orig_and_dest_valid=true`,
  `_wp_bearing_cd` populated.

All four guards of `AR_WPNav::update()` at `AR_WPNav.cpp:141-152`
look like they should pass. Yet:

```
484 AUTO ticks
0   non-neutral L=/R= PWM values
nav_bearing=0°  (never updates)
xtrack_err=0.00m (never updates, though this is expected since
                 vehicle stays at origin = on segment)
throttle=0%, groundspeed=0.00 m/s
```

## What V3 actually shows

Three anomalies that survive every fix tried so far:

### 1. `nav_bearing` never updates to 15°

`NAV_CONTROLLER_OUTPUT.nav_bearing` is `wp_nav.nav_bearing_cd() =
_desired_heading_cd`. This field is **only written inside the pivot
branch** of `AR_WPNav::update_steering_and_speed()` at
`AR_WPNav.cpp:518-521`:

```cpp
if (_pivot.active()) {
    _desired_speed_limited = _atc.get_desired_speed_accel_limited(0.0f, dt);
    _desired_heading_cd    = _reversed ? wrap_360_cd(oa_wp_bearing_cd() + 18000)
                                       : oa_wp_bearing_cd();   // ← only here
    _desired_turn_rate_rads = is_zero(_desired_speed_limited)
                              ? _pivot.get_turn_rate_rads(...)
                              : 0;
    _desired_lat_accel = 0.0f;
}
```

Two possible interpretations:

(a) **Early-return in `AR_WPNav::update()` is silently firing.** If
    the 4-guard at line 141 trips, `update_steering_and_speed()` is
    never called, `_desired_heading_cd` keeps its init-time zero, and
    we see `nav_bearing=0°` forever. This is consistent with
    `_cross_track_error=0` (also zeroed by the early-return branch),
    but we can't distinguish "set to 0 by the early-return" from "on
    the segment, legitimately 0" without further instrumentation.
    The V3 diagnostics argue against this, but each guard is
    AHRS-facade-based and the getters can be moment-by-moment flaky
    even when the broadcaster-level `get_relative_position_NED_origin`
    is succeeding (they use different internal freshness checks).

(b) **We are in the non-pivot branch every tick.** 15° of heading
    error is below the default `PIVOT_ANGLE` (60° in AR_PivotTurn
    defaults), so pivot never activates. In the non-pivot branch,
    `_desired_heading_cd` is never written at all, which also
    produces `nav_bearing=0°` forever.

Both (a) and (b) produce the same telemetry and we cannot tell them
apart from the current streams.

### 2. Servos are still frozen at neutral in the non-pivot branch (if that's where we are)

If we are in the non-pivot branch (possibility (b) above),
`update_steering_and_speed` writes:

```cpp
_desired_speed_limited  = _pos_control.get_desired_speed();
_desired_turn_rate_rads = _pos_control.get_desired_turn_rate_rads();
_desired_lat_accel      = _pos_control.get_desired_lat_accel();
```

These then feed `Mode::navigate_to_waypoint()`, which calls
`calc_throttle(wp_nav.get_speed(), false)` and
`calc_steering_from_turn_rate(desired_turn_rate_rads)`. Neutral
servos imply `_desired_speed_limited = 0` and
`_desired_turn_rate_rads = 0`, i.e. `AR_PosControl` is producing
zeros.

`AR_PosControl::update()` (`AR_PosControl.cpp:114`) computes
`_vel_target = _p_pos.update_all(_pos_target, curr_pos_NED_m.xy())`
only when `_pos_target_valid == true`. `_pos_target_valid` is set to
true only when `AR_WPNav::advance_wp_target_along_track()` calls
`_pos_control.set_pos_vel_accel_target(...)` at `AR_WPNav.cpp:453`.
That call happens unconditionally after the advance-guard passes — so
if the guard passes (which lpos at 3 Hz strongly implies), the
S-curve path *should* be populating pos-controller targets.

The remaining suspicion is the **S-curve itself**: if
`_scurve_this_leg` produces `target_vel ≈ 0` early on (e.g. it hasn't
yet accelerated, or its first tick returns a target identical to the
vehicle's position), `_vel_target` collapses to zero and the
stop-controller branch in `Mode::calc_throttle` at `mode.cpp:313-320`
produces `throttle_out = 0` — exactly what we see.

Against this: the S-curve accelerates over distance on subsequent
ticks. Even with `WPNAV_ACCEL` default ≈ 1 m/s², after >20 s of
continuous ticks the target velocity should be nowhere near zero.

### 3. EKF variance telemetry remains suspiciously uniform-zero

Across the entire run, post-healthy:

```
ekf: vel_var=0.00 pos_horiz_var=0.00 compass_var=0.00 flags=831
```

`pos_vert_var` varies (0.00..0.07) and occasionally flickers, but the
three horizontal variances are locked at 0.00. A real EKF's
`EKF_STATUS_REPORT.velocity_variance` is never literally zero once
fusion is running — even in V2's run with a flapping fix we got
`vel_var=0.01` briefly. The persistent zero across V1/V2/V3 is odd
and suggests the variance-report path is either skipped or is
rounding a sub-0.005 value. Not necessarily causal, but worth noting.

## What the *new* autopilot-side log adds

One fresh data point from the autopilot STATUSTEXT log:

```
[22:27:16.355 ] Info: Flight plan received
[22:27:26.759 ] Info: EKF3 IMU0/1/2 origin set
[22:27:26.759 ] Info: Mission: 1 WP                ← mission started the MOMENT origin was set
[22:27:35.706 ] Info: Mission: 1 WP                ← restart ~9 s later
[22:27:35.752 ] Critical: EKF failsafe cleared
[22:27:35.809 ] Info: Mission: 1 WP                ← another restart 100 ms later
```

`mission.start_or_resume()` is called in `ModeAuto::update` the first
tick after `ahrs.get_origin()` succeeds (`mode_auto.cpp:54-64`). That
happens at 22:27:26.759 — **while the EKF still has
`CONST_POS_MODE=1` (flags=167)**. At that instant,
`AR_WPNav::set_desired_location` → `set_origin_and_destination_to_stopping_point`
→ `get_stopping_location` → `AP::ahrs().get_location(current_loc)`
could easily fail (no absolute position). When it fails,
`set_desired_location` returns false; `do_nav_wp` returns false.

The retries at 22:27:35.706/.809 are the mode cycle and should have
succeeded, since by then the EKF is healthy. But if the first-failed
attempt left any `_nav_control_type` / `_fast_waypoint` / scurve state
inconsistent, subsequent `set_desired_location` calls go through the
`re-initialise if inactive` branch at `AR_WPNav.cpp:206-213`, which
should self-heal but depends on `set_origin_and_destination_to_stopping_point`
succeeding again and the scurve `calculate_track` producing a valid
leg for the 5 m segment. Without BIN-log-level introspection we
cannot confirm.

Also notable: the autopilot log no longer contains `EKF variance`
(it did in V1/V2). Only `EKF failsafe cleared`. EKF stayed healthy
for the rest of the run (`AHRS: DCM active` at the end is the
post-sim reboot fallback, expected).

## Summary of the bug as it stands

- GPS_INPUT 15 Hz works: sim sends at ~14.3 Hz, tunnel delivers.
- AHRS origin-relative position getter works: LOCAL_POSITION_NED at 3 Hz.
- EKF reaches `flags=831`, no variance events, no failsafes.
- GPS driver at RTK_FIXED, 20 sats, HDOP 0.50.
- `sys: gps=OK ahrs=OK` stays clean.
- Armed, AUTO, mission seq=1 active, wp_dist=5 m, target_bearing=15°.
- **Yet: 484/484 AUTO ticks produce neutral L=R=1500 PWM, 0% throttle.**

The V2 fix (15 Hz GPS) addressed a real problem (LOCAL_POSITION_NED
suppression) but that was not the *only* thing keeping the rover
from moving. The remaining cause is one of:

1. `AR_WPNav::update()` still hits its 4-guard early-return despite
   everything looking healthy. Distinguishable only by probing one
   of those guards directly.
2. The S-curve/pos-controller pipeline runs but produces persistent
   zero outputs (e.g. scurve `target_vel` stuck near zero for the
   first-leg init, or `_pos_target_valid` never latched because
   `do_nav_wp` failed the first time at 22:27:26.759 and the retry
   left residual state).
3. Pivot is disabled/mis-tuned and the non-pivot branch never
   produces non-zero steering/throttle for this geometry (15°
   heading error, 5 m distance). That would typically still produce
   a small turn rate, but with WPNAV / ATC parameters at defaults
   on a mower frame the effective commanded turn rate/speed could
   round to zero under accel-limiting for the first tick, then get
   stuck if the vehicle never actually moves.

The three are not distinguishable from the MAVLink telemetry we're
streaming today.

## What would decisively move V3 forward

(Explicitly not fixing anything here — summary only.)

1. **Download the BIN/onboard log after the next sim run** and
   inspect: `CTRL` / `RATE` / `PIDS` / `STER` / `THR` / `NTUN` /
   `WP` messages. These directly expose `_desired_speed_limited`,
   `_desired_turn_rate_rads`, and scurve target-position/velocity.
2. **Probe `_pivot.active()` indirectly**: read the Rover-specific
   param `WP_PIVOT_ANGLE` and `WP_PIVOT_RATE`. If `PIVOT_ANGLE=0`
   pivot is disabled entirely and only scurve steering runs.
3. **Bypass AUTO via GUIDED mode** (already wired:
   `gps_sim.set_position_target_global`). If GUIDED drives the
   rover, the bug is AUTO-specific (mission state machine or the
   first-failed `do_nav_wp` leaving scurve/pos-control residual
   state). If GUIDED also fails, the bug is in the common
   AR_PosControl / AR_WPNav layer regardless of mode.
4. **Re-order sim startup so `MISSION_START` and first AUTO entry
   are issued only after `flags=831`** rather than at arm. The
   current sim code defers `MISSION_START` until EKF healthy, but
   `ModeAuto::_enter` runs the moment AUTO is set at arm-time, and
   `update()` kicks off the mission the instant `get_origin()`
   returns true — before the EKF has HORIZ_POS_ABS. The first
   `do_nav_wp` can fail silently as described above. Holding the
   mode at HOLD (or GUIDED) until `flags=831` and only then
   switching to AUTO would eliminate that race.
