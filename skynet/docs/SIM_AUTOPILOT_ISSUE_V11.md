# Sim runs but rover never moves — V11 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V10.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1919 lines, ~45 s runtime)
Autopilot log: operator paste (`23:16:05 → 23:19:17`)

## TL;DR — heading injection confirmed, motor output path completely dead

V10 changes (10 m offset, 105° heading, yaw sweep) all worked:
spawn geometry is correct, heading injection drives the QGC display,
EKF healthy banner and engagement fire cleanly. **Servo output
stayed L=R=1500 for 100% of the session** — including during the yaw
sweep, confirming the motor output path is dead in AUTO mode.

### New finding: EKF3 regresses to "waiting for GPS config data" mid-session

Autopilot log shows `EKF3 waiting for GPS config data` repeating
every 10 s from `23:18:07` through `23:19:17` — a full **70 seconds**
of GPS rejection *without a reboot* (no `ArduRover V4.6.3` boot
banner in that window). The sim is streaming GPS_INPUT at 15 Hz the
entire time.

This means the EKF3's internal GPS state machine dropped from
"using GPS" back to "waiting for config data." Possible causes:

1. **`EK3_GPS_CHECK=0` did not persist across the reboot.** The sim
   writes it pre-reboot, but if the autopilot doesn't save it to
   NVM before rebooting, the post-reboot firmware reverts to the
   default (`EK3_GPS_CHECK=1`), which requires GPS health fields
   that `AP_GPS_MAV` doesn't fully populate.
2. **AP_GPS_MAV driver losing internal state.** The driver tracks
   `_new_data` and `_have_config` flags; if the MAVLink tunnel drops
   messages for a few seconds, these flags can reset.
3. **A second spontaneous reboot** that doesn't emit a boot banner
   in the onscreen log (e.g., a fast watchdog trip where only the
   IOMCU restarts, not the main CPU).

This regression is likely the *ultimate* reason throttle stays at 0:
the EKF is not in a state where `get_velocity_NED()` returns true,
so `AR_AttitudeControl::get_forward_speed()` early-returns, and
`AR_WPNav::update_steering_and_speed()` never computes throttle.

### Persistent pattern across V4–V11

| Signal              | Value      | Same since |
|---------------------|------------|------------|
| `wp_dist`           | 9 m        | V10 (was 5 m in V4–V9) |
| `target_bearing`    | 15°        | V4 |
| `xtrack_err`        | 0.00 m     | V4 |
| `nav_bearing`       | 0°         | V4 |
| `throttle`          | 0%         | V4 |
| `POSITION_TARGET`   | absent     | V9 |
| `L/R servo`         | 1500/1500  | V4 |

## Changes implemented

1. **Auto-arm after EKF healthy** — the sim now sends
   `MAV_CMD_COMPONENT_ARM_DISARM` (arm=1) once the EKF reports
   `flags=831` AND the vehicle is not yet armed. With
   `ARMING_CHECK=0`, this succeeds immediately. The operator no
   longer needs to arm via QGC — the full flow is:
   boot → param write → reboot → reconnect → GPS inject →
   EKF healthy → auto-arm → HOLD → engage AUTO → MISSION_START.
2. **Removed yaw sweep** — its diagnostic purpose (confirm heading
   injection and check for differential motor output) was fulfilled
   in V10. Keeping it would mask the real nav behaviour.

## What to try next

The EKF GPS regression mid-session is the strongest lead. Two
approaches:

1. **Verify `EK3_GPS_CHECK=0` persists post-reboot** — add a
   post-reboot param read for `EK3_GPS_CHECK` and log its value.
   If it reverted to 1, re-write it after reconnect (same as the
   VISO second-pass pattern).
2. **Switch to `EK3_SRC1_YAW=2` (GPS yaw)** as recommended by the
   ArduPilot GPS_INPUT documentation, instead of `EK3_SRC1_YAW=6`
   (ExternalNav). The vision backend path has more moving parts
   and may interact poorly with the GPS config check. The GPS yaw
   path is the officially supported path for GPS_TYPE=14.
