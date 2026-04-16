# Sim runs but rover never moves — V4 analysis

Date: 2026-04-14 (follow-up to `SIM_AUTOPILOT_ISSUE_V3.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1604 lines, ~44 s runtime; EKF healthy at t=19.1 s)
Autopilot log: operator paste (`22:50:28 → 22:51:44`)

## TL;DR — summary of observed issues (no fixes applied)

The rover stays at `L=+0.00(1500) R=+0.00(1500)`, `spd=0.00 m/s`,
`throttle=0%` for the entire session in AUTO while armed. The autopilot
*is* producing valid navigation math (`wp_dist=5 m`, `target_bearing=15°`,
`xtrack_err=0 m`) but never commands throttle. V3's "raise GPS_INPUT to
15 Hz" mitigation is in place and the EKF does go healthy (flags
`167 → 831` at t=19.1 s), so the EKF/velocity path is no longer the
blocker. The new blockers are upstream of `AR_WPNav`:

---

### Issue 1 — Mission re-upload rejected; autopilot kept a 1-WP stub

Sim log, line 37:

```
Warning: mission re-upload: Mission rejected early at seq 1:
MAV_MISSION_RESULT=13
```

`MAV_MISSION_RESULT=13` is `MAV_MISSION_INVALID_SEQUENCE` — the
autopilot rejected the upload mid-protocol after it accepted `MISSION_COUNT`
but before item 1 landed. The sim's `mission_upload.py::_send_mission`
(lines 72–83) treats this as a hard failure and `cli.py:978` downgrades
it to a yellow warning and continues.

The autopilot log confirms the outcome:

```
22:50:52.780  Warning: Mission upload timeout
22:51:03.660  Info: Mission: 1 WP
22:51:08.497  Info: Mission: 1 WP
```

Only **1 mission item** is actually stored — almost certainly just the
home slot (seq 0). The sim meanwhile reports `Downloaded 4 waypoints
(+ home) from autopilot` on startup, so its view of the mission and the
autopilot's view are desynchronised for the rest of the run. Consistent
with that:

- `Mission current seq: 0` is the only value printed for the entire
  session (line 110). AR_Mission never advances to seq 1 because there
  is no seq 1 on the autopilot.
- `nav: wp_dist=5 m target_bearing=15° nav_bearing=0°` is stale/degenerate
  output from `ModeAuto::update()` with no valid active NAV_WAYPOINT —
  the autopilot is essentially holding at the home slot while AUTO is
  engaged, which produces zero throttle.

**Why the re-upload fails at seq 1:** the re-upload path in
`cli.py` fires after the `GPS_TYPE → MAV` reboot. The post-reboot
`MISSION_REQUEST` stream can race the MAVLink re-handshake (target
system/component resolution, link resync); the autopilot appears to
receive a stale or out-of-order item and answers `INVALID_SEQUENCE`.
V3's flow did not trigger this because V3 didn't force a reboot on every
run.

---

### Issue 2 — Autopilot rebooted **twice** during startup

Autopilot log shows two full boot banners and two full EKF init
sequences:

```
22:50:28  ArduRover V4.6.3 (3fc7011a)   ← boot #1
22:50:37  ArduPilot Ready
22:50:41  AHRS: EKF3 active
22:50:59  EKF3 IMU origin set
22:51:08  EKF failsafe cleared
…
22:51:37  ArduPilot Ready                ← boot #2 (unexpected)
22:51:44  EKF3 waiting for GPS config data
```

The sim issues exactly one `reboot_autopilot()` ("Rebooting autopilot
for GPS_TYPE change…", line 35), yet the controller boots a second
time ~60 s later. At the second boot the EKF regresses to *"waiting
for GPS config data"*, which on `GPS_TYPE=MAV` requires another
`GPS_INPUT` burst to clear. The sim is still streaming GPS_INPUT at
15 Hz, so it probably would have cleared, but the session was stopped
first.

The cause of the second boot is not visible in the logs we have.
Candidates worth checking next: a watchdog trip from an unhandled
message flood, a duplicate `MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN` (the
sim's param-write path includes a reboot when any of
`GPS_TYPE/EK3_SRC1_*` change — if the second param write triggered
another reboot, that would explain it), or a BRD_SAFETY/RC fallback.

---

### Issue 3 — Three sim params silently missing on the autopilot

Sim log, lines 31–34:

```
Sim param VISO_DELAY_MS    (and alias none) not found on autopilot
Sim param VISO_POS_M_NSE   (and alias none) not found on autopilot
Sim param VISO_YAW_M_NSE   (and alias none) not found on autopilot
Sim param DISARM_DELAY     (and alias none) not found on autopilot
```

`resolve_sim_params()` in `gps_sim.py:115` logs a `WARNING` and drops
the param when neither the canonical name nor its alias is present in
the fetched param dict. The dropped values matter:

- **`VISO_*` (three params).** The V3 design relies on
  `EK3_SRC1_YAW=6` (ExternalNav) + `VISO_TYPE=1` + explicit
  `VISO_DELAY_MS/POS_M_NSE/YAW_M_NSE` to feed
  `VISION_POSITION_ESTIMATE` yaw into the EKF (comments at
  `gps_sim.py:59–68` are explicit that "VISO_TYPE=1 alone is necessary
  but not sufficient"). If those three noise/delay params never reach
  the autopilot, the vision backend is trusted with defaults that may
  or may not permit yaw fusion. EKF3 *did* report `yaw aligned` on
  boot 1, so the current run got lucky, but this is latent fragility.
  Likely cause: `VISO_TYPE=1` is only persisted after a reboot, and
  the `AP_VisualOdom_MAV` backend instantiates its params on that
  reboot. On the first sim connect (before the GPS_TYPE reboot) the
  `VISO_*` params don't exist yet, so `fetch_all_params()` can't see
  them; the sim then refuses to write them.
- **`DISARM_DELAY`.** On ArduRover 4.6 this *should* exist as a
  top-level param. It is missing from the fetch. Two explanations are
  plausible: (a) `params.fetch_all_params()`'s gap-detection finished
  without re-requesting this index, or (b) the param has been renamed
  to something not in `_PARAM_ALIASES`. Not the movement blocker (the
  `StopWatcher` never tripped a DISARM and the autopilot would have
  emitted a disarm STATUSTEXT which we don't see), but the sim believes
  it has disabled idle auto-disarm when it has not.

---

### Issue 4 — `ahrs=BAD(disabled)` persists ~43 s past EKF-healthy banner

`sys: gps=OK ahrs=BAD(disabled)` continues until t≈43 s, while
`EKF healthy (t=19.1 s, flags=831)` banner fires at t=19.1 s. The
disagreement is between `SYS_STATUS.onboard_control_sensors_health`
(the AHRS bit) and `EKF_STATUS_REPORT.flags`. This implies
`AP::ahrs().healthy()` returned false for ~24 s after EKF3 otherwise
looked fine — which is exactly the regime in which
`AR_AttitudeControl::get_forward_speed()` falls back from
`ahrs.get_velocity_NED()` to GPS speed, and
`AR_WPNav::update_steering_and_speed()`'s early-return guards fire.
By the time `ahrs=OK` arrives at t≈43 s, very little runtime remains
in this log. Worth re-running with a longer duration to see whether
throttle actually starts once `ahrs=OK` has been stable for a few
seconds — this may not be a bug so much as "we need to wait longer".

---

### Issue 5 — `NAV_CONTROLLER_OUTPUT.nav_bearing` stuck at 0°

Every `nav:` line shows `nav_bearing=0°` even after `target_bearing=15°`
is computed and `xtrack_err=0`. This matches the V3-documented
behaviour (see `gps_sim.py:928–934`): when `WP_PIVOT_ANGLE > 5` *and*
the pivot branch never actually runs, the non-pivot branch of
`AR_WPNav::update_steering_and_speed` never writes `_desired_heading_cd`,
so `nav_bearing` is reported as the uninitialised 0. In this run
`WP_PIVOT_ANGLE=60`, `target_bearing=15°`, so the pivot gate does
*not* open — but a non-pivot AUTO step should still be commanding
throttle. The fact that it isn't lines up with Issue 1 (no valid
mission item) and Issue 4 (AHRS unhealthy until late).

---

## Likely root cause, ranked

1. **Mission state is 1-WP-stub** (Issue 1). Without a valid seq≥1
   NAV_WAYPOINT the autopilot has nowhere to drive; AUTO reduces to a
   stop controller regardless of EKF health.
2. **AHRS remains unhealthy well past the EKF banner** (Issue 4),
   suppressing the `AR_WPNav` throttle path during the window where
   the test is actually watching.
3. **Latent VISO_* / DISARM_DELAY config missing** (Issue 3). Won't
   break *this* run but can break future ones; explains why the
   autopilot needed a second reboot to pick up external-nav config.
4. **Spurious second autopilot reboot** (Issue 2). Resets the EKF mid-
   session and would invalidate any throttle already starting to ramp.

## What to investigate next (no code changes in this doc)

- Re-upload the mission **after** all params are written and both
  reboots have settled, not before. Verify with `MISSION_COUNT_READBACK`
  that `count == len(items)` before starting AUTO.
- Add a pre-flight check that reads `MISSION_COUNT` and refuses to
  enter AUTO if it's < `last_mission_seq`.
- Instrument `SYS_STATUS.onboard_control_sensors_health` AHRS bit
  separately from the EKF banner so the "EKF healthy → AUTO can drive"
  message isn't emitted while AHRS is still disabled.
- After `VISO_TYPE=1` + reboot, re-fetch params and attempt a second
  write pass to cover `VISO_DELAY_MS / VISO_POS_M_NSE / VISO_YAW_M_NSE`
  once they exist.
- Find the cause of the second `ArduPilot Ready` at 22:51:37 — check
  whether any sim-side code sends a second `PREFLIGHT_REBOOT_SHUTDOWN`.

No fixes have been applied; this document is analysis only.
