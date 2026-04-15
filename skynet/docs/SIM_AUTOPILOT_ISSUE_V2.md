# Sim runs but rover never moves — V2 analysis (updated with new diagnostics)

Date: 2026-04-14 (follow-up to `SIM_AUTOPILOT_ISSUE.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (623 lines, ~47 s under healthy-EKF AUTO)

## What changed since V1

The simulator was instrumented to stream `GPS_RAW_INT`,
`LOCAL_POSITION_NED` and `SYS_STATUS` at 1 Hz so that each of the four
`AR_WPNav::update()` guards could be observed independently. V1
hypothesised that `!_atc.get_forward_speed(speed)` (guard #4) was
firing, with `!AP::ahrs().get_location()` (guard #3) as secondary.

**The new diagnostics disprove V1.** All four `AR_WPNav::update()`
guards are passing; the failure is one level deeper, in
`AR_PosControl::update()` and `AR_WPNav::advance_wp_target_along_track()`.

## What the new telemetry shows

Observations from `/tmp/sim.log` after the mode cycle (t ≈ 23 s, EKF
healthy, flags=831):

- `gps_raw: fix=RTK_FIXED sats=20 hdop=0.50` — the `AP_GPS_MAV`
  driver reports a full RTK fix, so `AP::gps().status() >= FIX_3D` is
  true. The V1-suspected fallback path in
  `AR_AttitudeControl::get_forward_speed()` is available; guard #4
  cannot be firing on this basis.
- `sys: gps=OK ahrs=OK` — the autopilot's own `SYS_STATUS` sensor-
  health bits are clean (a single transient `gps=BAD` during the
  mode cycle, then OK for the rest of the run).
- `ekf: vel_var=0.01 pos_horiz_var=0.00 pos_vert_var=0.0x
  compass_var=0.00 flags=831` — velocity variance is now non-zero
  (the EKF innovation pipeline is running) and CONST_POS_MODE is
  clear. `HORIZ_POS_ABS|HORIZ_POS_REL|HORIZ_VEL|VERT_VEL` are all
  set.
- `lpos: x=±0.00m y=±0.00m vx=±0.003 vy=±0.003 vz=±0.02m/s` —
  `ahrs.get_velocity_NED()` is returning true with tiny thermal-
  noise velocities, which is exactly what we expect from a
  stationary vehicle. Guards #3 and #4 of `AR_WPNav::update()` are
  both passing.
- `wp_dist=5m`, `target_bearing=15°` — origin/destination set,
  `_orig_and_dest_valid=true`, so guard #2 passes.
- `Flight mode: AUTO`, `Throttle armed` — guard #1 passes.

Conclusion: `AR_WPNav::update()` enters the main body every tick.
The failure is now further downstream.

## The new root-cause candidate — `LOCAL_POSITION_NED` is being suppressed

This is the key new signal: **LOCAL_POSITION_NED is emitted only
4 times in ~47 s of healthy-EKF AUTO, despite being subscribed at
1 Hz** (expected ~47 emissions).

In `libraries/GCS_MAVLink/GCS_Common.cpp:3042-3051`:

```cpp
void GCS_MAVLINK::send_local_position() const
{
    const AP_AHRS &ahrs = AP::ahrs();
    Vector3f local_position, velocity;
    if (!ahrs.get_relative_position_NED_origin_float(local_position) ||
        !ahrs.get_velocity_NED(velocity)) {
        return;  // silently dropped
    }
    ...
}
```

We already know from `lpos` emissions that `get_velocity_NED()` is
returning true. Therefore the missing-message ratio is telling us
**`ahrs.get_relative_position_NED_origin_float()` is failing on
roughly 90% of ticks** — intermittently — even though the EKF
`flags` bits and `sys` status both look healthy.

## Why that turns into "no movement"

Both of these call sites guard on the exact same failing AHRS call:

1. `AR_PosControl::update()` at `APM_Control/AR_PosControl.cpp:114-125`:

   ```cpp
   void AR_PosControl::update(float dt)
   {
       Vector3p curr_pos_NED_m;
       Vector3f curr_vel_NED;
       if (!hal.util->get_soft_armed()
           || !AP::ahrs().get_relative_position_NED_origin(curr_pos_NED_m)
           || !AP::ahrs().get_velocity_NED(curr_vel_NED)) {
           _desired_speed          = _atc.get_desired_speed_accel_limited(0.0f, dt);
           _desired_lat_accel      = 0.0f;
           _desired_turn_rate_rads = 0.0f;
           return;
       }
       ...
   }
   ```

2. `AR_WPNav::advance_wp_target_along_track()` at
   `libraries/AR_WPNav/AR_WPNav.cpp:407-414`:

   ```cpp
   void AR_WPNav::advance_wp_target_along_track(const Location &current_loc, float dt)
   {
       Vector2f curr_pos_NE;
       Vector3f curr_vel_NED;
       if (!AP::ahrs().get_relative_position_NE_origin_float(curr_pos_NE)
           || !AP::ahrs().get_velocity_NED(curr_vel_NED)) {
           return;  // _pos_target is never advanced
       }
       ...
   }
   ```

Whenever `get_relative_position_N(E|ED)_origin*` fails:

- The S-curve target is not advanced → `_pos_target` / `_vel_desired`
  stay stale at the origin → `_pos_control` computes `_vel_target ≈ 0`.
- `AR_PosControl::update()` also hits its own early-return most
  ticks, zeroing `_desired_speed`, `_desired_lat_accel`, and
  `_desired_turn_rate_rads` directly.
- `AR_WPNav::update_steering_and_speed()` reads those zeroed values
  back out through `_pos_control.get_desired_speed()` /
  `get_desired_turn_rate_rads()` into its own internal state.
- `Mode::navigate_to_waypoint()` passes `wp_nav.get_speed() = 0` to
  `calc_throttle()`; that routes to the stop-controller branch at
  `Rover/mode.cpp:313-320`, producing `throttle_out = 0`.
- `calc_steering_from_turn_rate(0.0)` → `set_steering(0)`.

Skid-steer motor mixing of throttle=0 + steering=0 gives exactly
`L=1500`, `R=1500`, which is what we observe for the entire run.

The reason `nav_bearing` stays at `0°` is complementary: in the
non-pivot branch of `update_steering_and_speed()`
(`AR_WPNav.cpp:517-528`), `_desired_heading_cd` is **not** written
(only the pivot branch writes it), so it retains its init-time zero
value. `target_bearing=15°` still updates because it comes from
`update_distance_and_bearing_to_destination()`, which has a different
and much laxer guard (`_orig_and_dest_valid + ahrs.get_location()`).

## Why the EKF `flags` field disagrees with the AHRS call

`EKF_STATUS_REPORT.flags` is a point-in-time snapshot of which
internal state bits the EKF currently believes it owns.
`AP_AHRS::get_relative_position_NED_origin_float()` does **not** map
1:1 to those flag bits — it additionally requires:

- The selected EKF instance to have a valid origin at the moment of
  the call,
- AHRS to be able to project the current position into that origin
  frame without triggering a staleness/innovation timeout.

On a bench with `GPS_TYPE=MAV` driven at 5 Hz over a TCP tunnel, a
single late GPS_INPUT packet can take the velocity/position age
above the AHRS freshness threshold for a tick, during which the
getter returns false even though the flag bits remain set. This
matches the "mostly missing, occasionally emitted" pattern in our
log (4 emissions in 47 s, always tightly clustered after an
`ekf:` update line — i.e. right when a fresh innovation was fused).

Evidence supporting the staleness interpretation:

- `sys: gps=BAD ahrs=OK` transient immediately after the mode cycle.
- `EKF variance` CRITICAL at 21:23:10.538 (just before failsafe
  cleared) — the innovation pipeline was marginal during the
  boot-up phase and likely remains close to the threshold.
- The autopilot's **own** debug log repeats `EKF3 waiting for GPS
  config data` as late as 21:23:57, **35 seconds after** GPS was
  declared healthy and in use. `AP_GPS_MAV` never publishes the
  "GPS config data" capability bit, so the EKF's internal "trusted
  configuration source" state never fully latches, and marginal
  staleness checks downstream fall on the strict side of the
  threshold.

## Supporting evidence

- `gps_raw: fix=RTK_FIXED sats=20 hdop=0.50` every log block, i.e.
  the driver-level GPS fix is rock-solid.
- Only 4 `lpos` lines in the log, vs. ~47 expected at 1 Hz. This
  is the single most informative data point in the new run and is
  what flips the V1 hypothesis.
- `vel_var=0.01` (non-zero) post-mode-cycle, whereas V1's log had
  `vel_var=0.00` persistently. The EKF innovation path is
  measurably running now — but not steadily enough for the AHRS
  origin-relative getter.
- Servo outputs: 228 AUTO ticks, 0 non-neutral `L=` values. Same
  frozen signature as V1, despite the deeper-layer cause.

## Conclusion

Despite `EKF_STATUS_REPORT.flags=831` and `sys: gps=OK ahrs=OK`, the
autopilot's `AHRS::get_relative_position_NED_origin_float()` returns
false on roughly 90% of ticks. That single failing call gates
`AR_PosControl::update()` and `AR_WPNav::advance_wp_target_along_track()`,
both of which zero their outputs on failure — which is how AUTO ends
up commanding throttle=0% and steering=0 every tick even though the
mission is active and the waypoint target is known.

The previously-suspected `AR_WPNav::update()` 4-guard early-return
(V1) is **not** firing: the new `lpos` / `gps_raw` / `sys` streams
confirm armed + orig/dest + ahrs.get_location + forward speed are
all available. The failure is one level below that, at the
EKF-origin-relative position getter, and it correlates with the
`AP_GPS_MAV` driver never latching "GPS config data trusted" plus
the marginal 5 Hz GPS_INPUT rate over the TCP tunnel.

## What would decisively confirm this

(Intentionally not fixing anything here — only listing verification
steps for a future run.)

1. **Watch `lpos` emission density** under the current sim.
   Hypothesis predicts: missing >80% of the time.
2. **Raise GPS_INPUT rate to 10 Hz** (currently 5 Hz clamp-safe;
   20 Hz max). Hypothesis predicts: `lpos` density rises
   substantially, and the rover begins to drive.
3. **Inspect the autopilot's BIN log `XKF*` / `POS` / `ORGN`
   messages.** They expose EKF origin status and innovation age
   directly.
4. **Bypass `ModeAuto` via GUIDED + `SET_POSITION_TARGET_GLOBAL`**
   (already wired in `gps_sim.set_position_target_global`).
   If GUIDED also refuses to drive, the failure is deeper than the
   mission state machine (supports this analysis). If GUIDED works,
   something AUTO-specific (e.g. scurve init) is the additional
   factor.
5. **Probe `AP_GPS_MAV`'s capability-bit / `EKF3 waiting for GPS
   config data` behaviour.** The autopilot log shows this error
   re-firing long after GPS is declared in use, which is consistent
   with the "config data not trusted → AHRS origin-getter
   conservative" hypothesis.
