# Sim runs but rover never moves — V6 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V5.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (2197 lines, ~52 s runtime)
Autopilot log: operator paste (`06:21:00 → 06:22:50`)

## TL;DR — all V5 fixes worked, and the rover still doesn't move

V5 added three guards; every one of them fired as designed in this
run. Extracted from `/tmp/sim.log`:

- **HOLD stickiness** (V5 §1) — `Re-asserted HOLD (autopilot flipped
  to AUTO before EKF healthy)` printed **≥ 7 times** between t=0.8 s
  and t=36.2 s. Some external actor (QGC or the autopilot itself) is
  aggressively trying to flip to AUTO.
- **Forced HOLD→AUTO cycle at gate** (V5 §2) — `Engaged HOLD→AUTO →
  MISSION_START @ seq=1` printed once at `t=36.3 s` after
  `EKF+AHRS healthy (flags=831)`.
- **Stable-yaw ATTITUDE read** (V5 §3) — ran without the "not
  settled" warning, meaning yaw was stable across ≥ 3 samples. Still
  returned `0.0°` though — see Issue 3 below.

Only **2 boots** this run (V5 saw 3). The "spontaneous reboot after
`Flight plan received`" from V5 §1 did not recur.

Despite all of that: `throttle=0%`, `L=+0.00(1500) R=+0.00(1500)`,
`spd=0.00 m/s` from `t=0` to `t=52 s`. Post-engagement nav
telemetry (constant from `t=36 s` onward):

```
sys: gps=OK ahrs=OK
nav: wp_dist=5 m target_bearing=15° xtrack_err=0.00 m nav_bearing=0°
ekf: vel_var=0.00 pos_horiz_var=0.00 flags=831
lpos: x=0 y=0 vx≈0 vy≈0    (LPOS flowing at 320% of 1 Hz sub)
```

Everything *looks* healthy. The autopilot is just declining to command
throttle.

---

### Issue 1 (NEW) — SYS_STATUS AHRS-health bit *flaps*, stalling the gate for 36 s

Count across the session:

- `sys: gps=OK ahrs=OK`      — **9 occurrences** (lines 71, 1701, 1753…)
- `sys: gps=OK ahrs=BAD(disabled)` — **57 occurrences** (lines 169…2076)

The AHRS health bit went `OK` once at t=0.5 s (likely the DCM
fallback's early self-reported health), then stayed `BAD(disabled)`
for ~35 s, coming back to `OK` only at `t=36.2 s` — which is why
the V4/V5 EKF+AHRS gate waited so long.

Correlated autopilot log events during that window:

```
06:22:03.640  EKF3 IMU origin set
06:22:04.507  Mission: 1 WP              (sim didn't start mission yet!)
06:22:04.601  Critical: EKF variance     ← variance spike
06:22:05.582  EKF3 IMU is using GPS
06:22:06.551  Critical: EKF failsafe cleared
```

The EKF variance spike at `06:22:04.601` comes from the EKF
re-initialising after origin set, which flips `AP::ahrs().healthy()`
false transiently. Our SYS_STATUS handler latches the current state
per message rather than debouncing, so each 1 Hz SYS_STATUS that
lands during the transient clears `ahrs_healthy`. Net effect: the
gate correctly refuses to engage AUTO during the spike, but it *also*
stays refused for the ~35 s tail while the AHRS bit slowly comes
back.

Worth noting the out-of-order event: `Mission: 1 WP` at
`06:22:04.507`, one second *before* `EKF failsafe cleared`, and
long before the sim engaged AUTO at sim-time `t=36.3 s`. Something
inside the autopilot or QGC fired MISSION_START itself.

---

### Issue 2 (NEW) — `Mission: 1 WP` printed **4 times** around the sim's MISSION_START

```
06:22:25.764  Mission: 1 WP
06:22:29.667  Mission: 1 WP
06:22:30.246  Mission: 1 WP
06:22:30.446  Mission: 1 WP
```

These clump at the moment the sim fires the HOLD→AUTO→MISSION_START
sequence (sim t≈36.3 s). A single MISSION_START should produce one
"Mission: 1 WP" line. Four repetitions mean either:

- The autopilot is receiving and processing MISSION_START four times
  (sim-side retries + a QGC retry + a MODE_AUTO re-entry).
- `ModeAuto::_enter` is being invoked multiple times because the
  mode is bouncing HOLD ↔ AUTO faster than sim/QGC observe it — each
  re-entry resets the mission state machine and reprints.

Either way, multiple `_enter` calls is the exact V3-documented
failure mode that leaves `AR_WPNav` with stale scurve / pos-control
state: each `_enter` calls
`set_origin_and_destination_to_stopping_point`; if two fire in quick
succession the second can race the first's async origin resolution
and corrupt the scurve trajectory to an all-zero state. **This is the
most likely explanation for why throttle stays at zero after
engagement.**

The V5 "force HOLD→AUTO cycle once" wasn't enough because we're also
contending with external AUTO commands during the same window.

---

### Issue 3 (V5 §3 fix ineffective) — `Start heading: 0.0°` still happens

V5 replaced `read_autopilot_yaw` with a "wait for 3 consecutive
ATTITUDE samples within 1°" loop to reject DCM fallback values. In
this run the function returned `0.0°` without issuing its "not
settled" warning — meaning it *did* get three stable samples at 0.0°.

The DCM fallback emits `yaw=0` as a stable, consistent value. The
new check can't distinguish "three samples at 0° because EKF yaw is
converged pointing north" from "three samples at 0° because we're
on DCM fallback and the fallback always reports 0." Both pass the
stability test.

The autopilot log shows `EKF3 IMU yaw aligned` at `06:21:53.682`,
which is **~35 s after** sim reconnect (sim reads ATTITUDE right
after reconnect, i.e. around `06:21:18`). So the read was
unambiguously too early and got the DCM 0°. The fix needs a
different discriminator: e.g., gate the read on
`EKF_STATUS_REPORT.flags & POS_HORIZ_ABS`, or correlate with the
`AHRS: EKF3 active` STATUSTEXT.

---

### Issue 4 (V5 §2 unchanged, now DOMINANT) — `throttle=0%` after full engagement

With every V5 guard satisfied at `t=36.3 s`:

- armed (autopilot log: `Throttle armed` at `06:21:34.942`)
- `mode=AUTO`
- `flags=831`, `sys: gps=OK ahrs=OK`
- `Mission current seq: 1`
- `nav: wp_dist=5 m target_bearing=15° xtrack_err=0 m`
- `lpos_in=16/5 (320% of 1 Hz sub)` — EKF velocity state published

…the autopilot commands `throttle=0%` for the entire remaining 15 s
window (t=36.3 → t=51.8 s, session end).

Candidate causes ranked:

1. **Mission state corrupted by repeated `ModeAuto::_enter`** (see
   Issue 2). The scurve / pos-control state ends up with
   `_desired_speed = 0` and never recovers without a full mission
   re-upload + re-engage.
2. **AR_WPNav early-return guard** in this firmware version checking
   a precondition we don't observe. No STATUSTEXT is being emitted
   for the refusal, so we can't see which guard trips. Needs a
   `POSITION_TARGET_GLOBAL_INT` stream subscription to discriminate
   "AR_WPNav computing and publishing target" vs "AR_WPNav
   early-returned before even setting a target".
3. **`ATC_ACCEL_MAX` / pos-control acceleration params left at
   defaults** that produce a stopping-distance > 5 m, so scurve
   decides it should brake the whole way. Sim log shows
   `ATC_STR_ACC_MAX=120` (steering accel); the forward-accel
   counterpart `ATC_ACCEL_MAX` isn't logged. Worth adding to the
   startup diagnostics.

Tractable next steps are ranked in the "What's implemented / next"
section below.

---

### Issue 5 (NEW low severity) — Autopilot emits mid-session `RCOut: PWM:1-14`

Autopilot log, last line:

```
06:22:50.484  Info: RCOut: PWM:1-14
```

`RCOut: PWM:1-14` is normally a boot-time line printed when the
servo output channels initialise. Seeing it ~1 minute into a running
session implies the IOMCU or the PWM subsystem re-initialised. It
coincides with the sim session ending, so it may simply be a disarm
or a sim-initiated teardown side effect. Worth a follow-up if it
reappears reliably.

---

## Fixes implemented in this run

1. **Debounce the AHRS-health bit** — require AHRS `OK` for **≥ 2
   consecutive SYS_STATUS messages (~2 s)** before flipping
   `ahrs_healthy` true, and ignore single-message BAD flaps while
   holding. This stops the `AHRS=BAD` transient during EKF variance
   spikes from resetting the gate. The debounce window can't be
   much shorter than the transient, because SYS_STATUS is only a
   1 Hz message.
2. **Drain stale mission-protocol traffic at the HOLD→AUTO edge** —
   before firing `set_rover_mode(AUTO)` + `start_mission`, drain any
   pending `MISSION_REQUEST*` / `MISSION_ACK` / `COMMAND_ACK` to
   suppress late retries from QGC that otherwise produce duplicate
   MISSION_START handling (Issue 2).
3. **Subscribe to `POSITION_TARGET_GLOBAL_INT` at 1 Hz** so the next
   run shows whether AR_WPNav is publishing a target at all. This is
   diagnostic, not a functional fix — but without it, Issue 4's
   candidate (2) is untestable.

## Not fixed (flagged for next iteration)

- Issue 3: `read_autopilot_yaw` DCM-fallback detection. Proper fix
  needs correlation with `EKF_STATUS_REPORT.flags`, not ATTITUDE
  stability alone.
- Issue 4 root cause: likely needs an on-target dataflash `LOG`
  dump via MAVFTP (`@SYS/dataflash/...`) to see the actual
  `_desired_speed` and `_desired_heading_cd` values AR_WPNav is
  computing during the throttle=0 window.
- Issue 5: needs a reliably reproducing signature to investigate.
