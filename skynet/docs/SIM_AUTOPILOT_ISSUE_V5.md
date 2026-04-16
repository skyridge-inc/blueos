# Sim runs but rover never moves — V5 analysis

Date: 2026-04-14 (follow-up to `SIM_AUTOPILOT_ISSUE_V4.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1134 lines, ~32 s runtime)
Autopilot log: operator paste (`23:23:34 → 23:25:00`)

## TL;DR

V4's four fixes landed cleanly and every one of them is observable in
the log:

- `Mission restored & verified: 4 waypoints + home (autopilot reports
  5 items)` — upload-and-verify worked; no silent 1-WP stub.
- `EKF+AHRS healthy (t=11.3s, flags=831). AUTO mode can now drive` —
  the dual EKF+AHRS gate replaced the old EKF-only gate.
- Pre-AUTO `MISSION_COUNT` gate queried and passed.
- `lpos_in=15/5 (300% of 1Hz sub)` once the EKF went healthy — V3's
  position-feedback chain is fine.

The rover still doesn't move. `throttle=0%`, `L=+0.00(1500)
R=+0.00(1500)` persist from `t=0` to `t=32 s` (session end) despite
every observable precondition being satisfied:

- `mode=AUTO`, armed
- `flags=831`, `sys: gps=OK ahrs=OK`
- `Mission current seq: 1`
- `nav: wp_dist=5 m target_bearing=15° xtrack_err=0 m`
- `lpos:` flowing with near-zero vx/vy (EKF publishing velocity state)

Two new issues appeared in this run, and one long-standing issue is now
dominant.

---

### Issue 1 (NEW — confirmed) — Autopilot spontaneously reboots ~86 ms after mission upload

Autopilot log, ordered by time:

```
23:23:39.325  ArduRover V4.6.3    ← boot #2 (sim-triggered, expected)
23:23:44.100  GPS 1: specified as MAV
23:23:50.174  EKF3 IMU initialised
23:23:57.216  Flight plan received   ← sim's upload_and_verify completes
23:23:57.302  ArduRover V4.6.3    ← boot #3 ( +86 ms, UNEXPECTED )
23:24:10.355  Throttle armed
23:24:28.377  Set HOME to 40.30069 -83.03814 at 0.00m
23:24:28.515  EKF3 IMU yaw aligned
23:24:38.453  EKF3 IMU origin set
23:24:38.456  Mission: 1 WP
```

The autopilot rebooted itself 86 ms after printing `Flight plan
received`. The sim sent exactly one `PREFLIGHT_REBOOT_SHUTDOWN`
(at 23:23:39) and no further reboot commands, so this is initiated
autopilot-side. Hypothesis shortlist:

- EEPROM/flash commit of the mission tripped a watchdog (MAVFTP/mission
  storage on the CubeOrangePlus with `IOMCU: 420 1001 411FC231` has
  had spurious-reset reports historically).
- Writing a rebootable param landed in the same window — but the sim
  only writes sim-override params *before* the first reboot. Ruled
  out unless the second-pass late-VISO write path fired (log shows it
  didn't: "Warning: late param re-check failed").
- A lua / AP_Scripting fault in the on-controller init, triggered by
  the mission accept. Not inspected.

This boot is the root cause of several downstream symptoms in
Issue 2 and Issue 3 — the post-upload state is not preserved.

**V5 boot count: 3 (one expected, two unexpected in quick succession):**
`23:23:34`, `23:23:39`, `23:23:57`. The first one (23:23:34) is the
session-start boot the sim observed during its initial connect; it's
only surprising because the sim hadn't yet issued a reboot at that
time, suggesting the autopilot was *already* in a reboot loop when
the sim attached.

---

### Issue 2 (NEW) — Post-reboot `fetch_all_params` times out after 456/960 params

Sim log line 38:

```
Warning: late param re-check failed: Timeout after 30.0s —
received 456/960 params. Continuing — sim may be missing some
nice-to-have overrides but not blockers.
```

This is the V4 "Issue 3 fix" firing. The 30 s timeout is budgeted
around one boot cycle, but the autopilot rebooted *during* the fetch
(the 23:23:57 boot in Issue 1), so the param stream was cut mid-way
through. The downgrade to warning is correct in principle — `VISO_*`
and `DISARM_DELAY` are not the movement blockers — but the warning
masks an important signal: *the fact that this timed out at ~47 % of
a full param set is itself evidence of a mid-fetch reboot.* A more
useful behaviour would be to detect the "param count dropped to zero
and restarted" pattern and re-trigger the fetch from scratch, rather
than accepting a partial.

---

### Issue 3 (NEW or downstream) — `Start heading: 0.0°` read too early

Sim log line 40:

```
Start heading: 0.0° (from autopilot ATTITUDE)
```

`read_autopilot_yaw()` runs immediately after the post-reboot
reconnect and mission re-upload, ~1 s before the autopilot's EKF
finishes IMU tilt/yaw alignment (`EKF3 IMU yaw aligned` doesn't land
until `23:24:28.515`, which is *after* this read). The ATTITUDE
message it consumes is coming from the DCM fallback (`AHRS: DCM
active`), not from EKF3, and has not converged — reading `0.0°` is
almost certainly garbage, not a real heading.

The SkidSteerModel is then seeded with `start_heading=0°`. Any
discrepancy between the autopilot's actual EKF yaw and the sim's
kinematic heading feeds back into the sim's GPS_INPUT yaw (which
floors `yaw=0` to 1 cdeg). In a normal run with no second reboot
this would settle quickly, but the third reboot (23:23:57) throws
the sim's yaw assumption out of phase with the freshly-reinitialised
EKF.

---

### Issue 4 (DOMINANT / unchanged since V3) — `throttle=0%` persists even with all preconditions met

With V4's guards all satisfied — armed, AUTO, flags=831, AHRS healthy,
mission seq=1, wp_dist=5 m, target_bearing=15°, LPOS flowing — the
autopilot still commands zero throttle for the full ~20 s of the
observed window between `t=11.3 s` and session end. Candidates ranked
by likelihood given the V5 evidence:

1. **Stale ModeAuto scurve / pos-control state from the pre-healthy
   AUTO entry.** At `t=0.9 s` the sim observed `Flight mode: AUTO`
   (user armed in AUTO via GCS), then at `t=1.0 s` forced HOLD. So
   `ModeAuto::_enter` ran once against an EKF with flags=167 — the
   V3-documented failure mode where
   `set_origin_and_destination_to_stopping_point` silently fails and
   leaves stale scurve/pos-control state that the retry-via-mode-cycle
   doesn't always clear. When the sim later re-engages AUTO at
   `t=11.3 s`, `ModeAuto::_enter` runs again, but if it's guarded
   against re-init (e.g. only running on HOLD→AUTO transition with a
   specific sub-state), the pre-healthy stale state persists.

2. **Mission contents were lost across the 23:23:57 reboot.** The
   pre-AUTO `MISSION_COUNT` gate passed at `t=11.3 s` with count
   ≥ 5, so the mission *is* present in the autopilot at that moment
   — the evidence here is weaker than (1). But given that boot
   `23:23:57` came only 86 ms after `Flight plan received`, there is a
   real risk that the mission commit to NVM was interrupted and some
   items are placeholders. Worth correlating by dumping all 5 mission
   items back from the autopilot after the gate passes and diffing
   against what the sim uploaded.

3. **AR_WPNav early-return on the `get_velocity_NED` guard feeding a
   chicken-and-egg with GPS_INPUT velocity.** The sim's GPS_INPUT
   `vn/ve` is fed from SkidSteerModel which only integrates when
   SERVO_OUTPUT_RAW shows non-neutral PWM — so while throttle is 0 %,
   velocity is reported as 0. `ahrs.get_velocity_NED()` should still
   return true with a zero vector (the velocity *state* exists), but
   an inequality rather than a non-null check in firmware would break
   the bootstrap. Specifically AR_WPNav sometimes requires the
   *magnitude* of the estimated velocity to exceed a threshold before
   engaging; that would deadlock the sim.

4. **ARMING_CHECK / pre-arm residual suppression.** `Throttle armed`
   and `Arming Checks Disabled` both appear in the autopilot log, so
   the mode accepts arming — but ArduRover has a separate
   "safety-armed vs throttle-allowed" path. With
   `BRD_SAFETY_ENABLE`/`SAFE_DISARM_PWM` configured a particular way,
   the motors may be masked off even though the vehicle reports armed.
   No evidence either way in the current log; would need
   `RC_CHANNELS` + `SERVO_OUTPUT_RAW` raw inspection at the IOMCU
   level.

The "keeping the first-AUTO entry healthy" strategy (V3's
HOLD → AUTO cycle, kept in V4) does not appear to be sufficient on
this firmware version when a *user-initiated* AUTO arm beats the sim
to the transition. Options 1 and 2 are the most tractable to narrow.

---

## Symptom timeline (sim clock)

| t (s) | Event | Source |
|-------|-------|--------|
| 0.9   | User armed in AUTO | sim observed `Flight mode: AUTO` |
| 1.0   | Sim forced HOLD    | `Forced mode=HOLD. Switching to AUTO…` |
| 6.2   | Mode flipped back to AUTO (unexpected — sim didn't do it) | sim observed `Flight mode: AUTO` |
| 10.5  | `Mission current seq: 1` | advance past home |
| 11.3  | `EKF+AHRS healthy (flags=831)`; sim engaged AUTO + MISSION_START | sim |
| 11.3→32 | `throttle=0%`, servos neutral, position static | continuous |

Note the unexplained AUTO-at-t=6.2 s: some external actor (likely
QGC) re-commanded AUTO between our HOLD force and the EKF-healthy
banner. This re-invokes the V3 "first ModeAuto::_enter fires against
an unhealthy EKF" failure mode a second time, on top of the one at
t=0.9. Any mitigation should (a) suppress external AUTO commands
while the sim is holding, or (b) recover cleanly from multiple such
transitions.

---

## What to investigate next

1. **Read back the full mission** after the pre-AUTO gate passes (not
   just the count) and diff against the uploaded items. This rules in
   or out the "reboot corrupted items 1..4" hypothesis.
2. **Force HOLD stickiness:** after the sim's first HOLD force,
   subscribe to HEARTBEAT mode and re-assert HOLD whenever the
   custom_mode changes to anything else before EKF-healthy. Prevents
   external AUTO re-commands from poisoning ModeAuto::_enter twice.
3. **Instrument `_desired_speed` / `_desired_heading_cd`:** request
   `POSITION_TARGET_GLOBAL_INT` at 1 Hz so the sim can see whether
   the autopilot is publishing *any* position target at all during
   the throttle=0 window.
4. **Autopilot spontaneous-reboot cause:** needs host-side
   investigation — dmesg equivalent on the flight controller,
   `@SYS/boot_count.txt` over MAVFTP, recent `dataflash` LOG line
   around the flight-plan accept.
5. **Fix Issue 2 in-sim:** detect param-stream reset (index resets to
   0) mid-fetch and restart rather than accept a partial.
6. **Fix Issue 3 in-sim:** defer `read_autopilot_yaw()` until after
   the first `EKF_STATUS_REPORT` with `POS_HORIZ_ABS` set.

No fixes applied yet — this document is analysis only; the live-code
fix pass is covered in the commit alongside this file.
