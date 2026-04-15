# Sim runs but rover never moves — root-cause analysis

Date: 2026-04-14
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (673 lines, ~90 s)

## What we observed

From `/tmp/sim.log`:

- Autopilot armed, AUTO mode confirmed (`Flight mode: AUTO`).
- Mission active: `Mission current seq: 1`.
- Navigation target known to the autopilot:
  `nav: wp_dist=5m target_bearing=15° xtrack_err=0.00m nav_bearing=0°`
- EKF reached full health: `EKF healthy (t=23.4s, flags=831)`.
  `831 = ATTITUDE | HORIZ_VEL | VERT_VEL | HORIZ_POS_REL | HORIZ_POS_ABS |
  VERT_POS | PRED_HORIZ_POS_REL | PRED_HORIZ_POS_ABS` — CONST_POS_MODE cleared.
- Sim cycled AUTO→HOLD→AUTO (t≈23.6 s). Operator also cycled manually
  from QGC several times (autopilot log shows 4–5 `Mission: 1 WP`
  re-starts over 55 s).
- Despite all of the above, for the entire run:
  `L=+0.00(1500)  R=+0.00(1500)`, `throttle=0%`, `groundspeed=0.00 m/s`,
  `nav_bearing=0°`, `xtrack_err=0.00 m`.

Autopilot STATUSTEXT log (provided by user): only two critical events —
`EKF variance` (once, during initial convergence) and `EKF failsafe
cleared` — both benign once healthy. No arming-inhibit, no
failsafe, no mode rejection, no "AUTO triggered off". The repeated
`Field Elevation Set: 0m` lines are just QGC telemetry noise.

## Why the autopilot is not commanding servos

Tracing `ArduRover`'s AUTO path (`mode_auto.cpp` → `Mode::navigate_to_waypoint`
→ `g2.wp_nav.update()`), the observed telemetry pattern — wp_dist and
target_bearing populated, but `nav_bearing=0°` and `xtrack_err=0.00 m`
constant, plus zero desired-turn-rate and zero desired-speed (→ stop
controller → throttle 0 → servos 1500) — is the **exact** signature of
the early-return branch in `libraries/AR_WPNav/AR_WPNav.cpp:141-152`:

```cpp
void AR_WPNav::update(float dt)
{
    Location current_loc;
    float speed;
    if (!hal.util->get_soft_armed()
        || !_orig_and_dest_valid
        || !AP::ahrs().get_location(current_loc)
        || !_atc.get_forward_speed(speed)) {
        _desired_speed_limited  = _atc.get_desired_speed_accel_limited(0.0f, dt);
        _desired_lat_accel      = 0.0f;
        _desired_turn_rate_rads = 0.0f;
        _cross_track_error      = 0;
        return;
    }
    ...
}
```

When this branch fires, `_distance_to_destination` and the bearing
cached by `set_desired_location()` are preserved (which is why we
still see `wp_dist=5m` and `target_bearing=15°` in
`NAV_CONTROLLER_OUTPUT`), but the navigation outputs that
`Mode::navigate_to_waypoint()` feeds into `calc_throttle` and
`calc_steering_from_turn_rate` are all zeroed — producing exactly the
throttle=0%, neutral-servos behavior we see.

`check_trigger()` is **not** the cause:
`AUTO_KICKSTART=0` is in the sim's SIM_PARAMS set (`gps_sim.py:102`),
and no `auto_trigger_pin` is configured, so `check_trigger()`
auto-succeeds on the first call (`mode_auto.cpp:426-429`).
Additionally, the user's parameter baseline has `ARMING_CHECK=0`
("Arming Checks Disabled" warning in the autopilot log).

## Which of the four guards is failing — hypotheses, ranked

(1) **`!_atc.get_forward_speed(speed)` (most likely).**
    `AR_AttitudeControl::get_forward_speed` (`AR_AttitudeControl.cpp:990`)
    first tries `AP::ahrs().get_velocity_NED(velocity)`. If the EKF
    reports velocity unavailable, it falls back to
    `AP::gps().status() >= FIX_3D`. We are on `GPS_TYPE=MAV` (AP_GPS_MAV
    driver). Two things can make both paths fail silently in HIL:
    (a) `AP_GPS_MAV` is known not to publish the "GPS config data"
    capability bit and can leave the driver status below `FIX_3D` even
    when `GPS_INPUT` messages are being consumed — this is exactly the
    reason the sim sets `GPS_TYPE=14` and sends RTK-quality fields
    (see `gps_sim.py:65-78, 500-517`), but the AP_GPS_MAV status check
    is firmware-dependent. (b) The EKF's `get_velocity_NED` implementation
    requires the velocity-state covariance to be valid; the persistent
    `ekf: vel_var=0.00` line in the log is consistent with the field
    never being populated by the health check (a real converged EKF
    shows non-zero variance), suggesting `EKF_STATUS_REPORT` is
    reporting zeros while the AHRS velocity getter silently returns
    false.

(2) **`!AP::ahrs().get_location(current_loc)`.**
    Should succeed given `HORIZ_POS_ABS` is set in flags=831, but the
    same `vel_var=pos_horiz_var=0.00` constants across the entire run
    are a warning sign that something about the position solution
    isn't being fully endorsed internally, even when the status flag
    bits suggest it should be.

(3) **`!_orig_and_dest_valid`.** Lower likelihood. `wp_dist=5m` and
    `target_bearing=15°` being reported proves
    `set_desired_location()` ran `update_distance_and_bearing_to_destination()`
    at least once (they're cached together). However, `_orig_and_dest_valid`
    could have been set true and then some later call did not clear it.
    Unlikely to be *the* intermittent guard but worth ruling out.

(4) **`!hal.util->get_soft_armed()`.** Ruled out — the heartbeats and
    the autopilot log (`Throttle armed`) confirm the vehicle is armed,
    and the mode cycle to AUTO succeeded.

## Supporting evidence from the logs

- `ekf: vel_var=0.00 pos_horiz_var=0.00 pos_vert_var=0.0x compass_var=0.00`
  every 2 s for the entire run. Real EKF convergence produces non-zero
  variances (typically 0.1–0.5). Zero everywhere suggests the fields
  are uninitialized / the innovation pipeline is not running.
- `Mission: 1 WP` repeats ~5 times in the autopilot log, matching the
  mode cycles. Each mode re-entry calls `do_nav_wp → set_desired_location
  → wp_nav.set_desired_location`, which re-caches `_distance_to_destination`
  (hence `wp_dist=5m` keeps re-appearing). But `update()` still early-returns.
- `Warning: mission re-upload: Timeout waiting for MISSION_ACK after
  sending 5 items`. The autopilot did log `Mission: 1 WP` after reboot,
  so the *first* NAV_WAYPOINT did make it through (enough to exercise
  the above code path). Not directly responsible for the no-motion
  condition, but worth re-confirming with a clean re-upload.
- Sim simulator's own kinematic model is driven off
  `SERVO_OUTPUT_RAW` normalized through `PwmNormalizer` (`gps_sim.py:316`).
  With PWM stuck at 1500 the model integrates zero motion, sends
  `vn=ve=0` in GPS_INPUT — this is *correct* bench behavior, not a
  sim bug.

## Why cycling HOLD→AUTO in QGC didn't help

Every AUTO re-entry calls `ModeAuto::_enter()` which sets
`waiting_to_start=true` and resets submode to Stop. On the next
`update()` tick, once `ahrs.get_origin()` succeeds,
`mission.start_or_resume()` re-fires command 1 → `do_nav_wp` →
`set_desired_location` → `wp_nav.set_desired_location`. That last
call re-populates `_distance_to_destination` and `_wp_bearing_cd`
(hence the periodic `Mission: 1 WP` log lines and the
continuously-present `wp_dist=5m`). But it does **not** un-stick the
early-return in `AR_WPNav::update()` because the failing guard is
**state-independent** (it's a per-tick check of armed + origin/dest
valid + ahrs location + forward speed). Re-running `_enter()` does
not change any of those inputs, so the rover stays frozen.

## Next actions to isolate

In priority order:

1. **Verify `AP_GPS_MAV` driver status on the autopilot.**
   Look at `sys_status` or add a probe: what does `AP::gps().status()`
   return while the sim is running? If it stays `< FIX_3D`, that is
   the fallback the sim is relying on. If it is `NO_FIX`, guard #1
   is confirmed.
2. **Read `EKF_STATUS_REPORT.velocity_variance` from a BIN log (not
   the telemetered field).** The telemetered zeros may be normal if
   the field is in a range that rounds to 0.00; the BIN log
   (`NKF*` messages) will tell us whether the EKF has actually
   fused any velocity/position innovations.
3. **Check `AR_WPNav::_atc.get_forward_speed` directly.** If you can
   add a one-off debug line or pull the `XKF*` `forward_speed`
   computation, you'll know immediately which branch in
   `get_forward_speed` is taken.
4. **Raise GPS_INPUT rate from 5 → 10 Hz and confirm AP_GPS_MAV
   stays at `FIX_3D`.** `gps_sim.py` clamps rate to 20 Hz; 5 Hz
   meets the minimum but leaves little margin if the TCP tunnel
   reorders or drops packets.
5. **Re-upload the mission cleanly** (the sim re-upload timed out
   mid-send). Even though the autopilot logged `Mission: 1 WP`,
   a partially-received mission list could leave `_origin`/
   `_destination` in an odd state on the autopilot.
6. **Bypass AUTO mode.** `gps_sim.set_position_target_global` is
   already wired (`gps_sim.py:815`). Switch the autopilot to
   GUIDED and send a single position target at sim start — this
   bypasses `ModeAuto`'s mission state machine and most of the
   `wp_nav` pivot/scurve path, isolating whether the freeze is in
   AUTO-specific code or deeper (wp_nav / attitude_control / AHRS).

## Conclusion

The rover is stuck in `AR_WPNav::update()`'s early-return branch
every tick, which is the unique failure pattern that produces the
exact telemetry we see (wp_dist/target_bearing populated;
nav_bearing/xtrack/turn-rate/desired-speed all zero; throttle 0%;
servos at 1500). The most likely failing guard is
`!_atc.get_forward_speed(speed)`, with
`!AP::ahrs().get_location()` as a secondary suspect. Both point at
the AHRS/EKF layer not delivering a trusted velocity (and possibly
position) state to the navigation controller despite the
`EKF_STATUS_REPORT.flags` field reporting healthy — consistent with
the persistent all-zero `vel_var/pos_horiz_var/compass_var` values
in the log. Mode cycling cannot fix it because the failing guards
are recomputed every tick from inputs that don't change on re-entry.
