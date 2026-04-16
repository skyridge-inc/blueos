# Sim runs but rover never moves — V7 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V6.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1893 lines, ~41 s runtime)
Autopilot log: operator paste (`21:43:31 → 21:44:38`)

## TL;DR — AHRS gate permanently blocks the HOLD→AUTO transition

The sim **never fires the "EKF+AHRS healthy" banner** in this run.
It stays in HOLD for the entire 41 s session:

```
t=  41.5  mode=HOLD    lat=40.30069285  lon=-83.03813540
ekf: flags=831  (POS_HORIZ_ABS set, CONST_POS_MODE clear — healthy)
sys: gps=OK ahrs=BAD(disabled)
```

`flags=831` is healthy. The gate requires `ahrs_healthy` **and**
`ekf_flags_healthy`. But `ahrs_healthy` **never becomes true**
because of a logic error introduced in V4.

---

### Root cause — SYS_STATUS AHRS bit requires ENABLED, but compasses are disabled

The V4 AHRS gate checks:

```python
ahrs_healthy = bool(
    (h & SYS_STATUS_SENSOR_AHRS)   # health bit
    and (e & SYS_STATUS_SENSOR_AHRS)  # enabled bit
)
```

On this rover, **compasses are intentionally disabled** (`COMPASS_USE
= 0`). With no compass, ArduPilot clears the
`MAV_SYS_STATUS_SENSOR_AHRS` (bit 12) from
`onboard_control_sensors_enabled`. This makes `e & AHRS = 0` and
`ahrs_healthy` can never be true — the gate is a permanent blocker.

The `(disabled)` suffix in the log confirms it:

```
sys: gps=OK ahrs=BAD(disabled)    ← 49 occurrences
sys: gps=OK ahrs=OK               ←  7 occurrences (brief flaps)
```

The 7 fleeting `OK` reads happen during EKF variance transients when
the autopilot momentarily toggles the enabled bit. They never form
2 consecutive OKs (V6 debounce requirement), so `ahrs_healthy`
stays false for the entire session.

**The V4 hypothesis that drove this gate was wrong.** V4 §Issue 4
assumed that `ahrs=BAD` meant the AHRS subsystem was unhealthy and
that `AR_AttitudeControl::get_forward_speed()` would early-return.
In reality, `ahrs=BAD(disabled)` means the *compass-based AHRS
sensor reporting* is not enabled — the EKF still functions via GPS
and ExternalNav and publishes velocity state (LPOS flowing at
300%+). The SYS_STATUS AHRS bit does not gate throttle in firmware;
only the EKF status flags do.

---

### Issue 1 — Repeated "Mission: 1 WP" in autopilot log (9 occurrences)

```
21:43:57.499  Mission: 1 WP
21:43:59.495  Mission: 1 WP
21:44:04.351  Mission: 1 WP
21:44:07.334  Mission: 1 WP
21:44:10.514  Mission: 1 WP
21:44:13.433  Mission: 1 WP
21:44:16.412  Mission: 1 WP
21:44:19.553  Mission: 1 WP
21:44:22.671  Mission: 1 WP
```

The mission state machine printed "advancing to WP 1" nine times
during the ~25 s window from `21:43:57` to `21:44:22`. Each print
corresponds to a `ModeAuto::_enter` call or a mission restart. The
sim's HOLD stickiness (V5) is re-asserting HOLD every time the
autopilot flips to AUTO — but the very act of flipping AUTO→HOLD
→AUTO (even for a fraction of a second) re-invokes `ModeAuto::_enter`
on each AUTO leg.

This is the V3-documented scurve state corruption risk amplified: 9
rapid `_enter` calls are far worse than the 4 seen in V6. Each one
calls `set_origin_and_destination_to_stopping_point` and may leave
`_desired_speed = 0` permanently.

Even if the AHRS gate is fixed, this issue can still kill the run
once AUTO engages — the autopilot's scurve / pos-control state may
already be corrupted from the 9 earlier mode-bounce cycles.

---

### Issue 2 — Autopilot ends with "EKF3 waiting for GPS config data"

```
21:44:38.413  EKF3 waiting for GPS config data   (×3)
```

These appear ~30 s into the session, after the EKF was already
fully healthy (`flags=831`). This is the same "spontaneous reboot
after mission interaction" pattern from V5 §Issue 1. After a reboot,
the EKF resets and waits for GPS_TYPE=MAV data from the sim again.
The sim is still streaming GPS_INPUT at 15 Hz, so the EKF would
recover — but combined with the permanent HOLD from the AHRS gate,
the session ended before that could happen.

---

### Issue 3 — `Start heading: 0.0°` (V5 §3 unchanged)

Still reading DCM fallback value before EKF yaw alignment. Not the
movement blocker but will affect heading tracking once the rover
starts moving.

---

## Fix implemented (Issue 0 — the blocker)

**Removed the SYS_STATUS AHRS requirement from the engagement gate.**

The gate now checks only `EKF_STATUS_REPORT.flags`:
`POS_HORIZ_ABS set AND CONST_POS_MODE clear`. The SYS_STATUS AHRS
bit is still logged for diagnostics but no longer drives the
`ahrs_healthy` variable used in the engagement decision.

This is a revert of the V4 §Issue 4 gate, validated by V7 evidence:
- `flags=831` is the direct readout of EKF navigability.
- The AHRS SYS_STATUS bit reflects compass subsystem status, not EKF
  navigability. On compass-disabled rovers it is permanently false.
- `AR_AttitudeControl::get_forward_speed()` checks
  `ahrs.get_velocity_NED()` — which succeeds when the EKF has
  velocity state (`flags=831` guarantees this), regardless of the
  compass sensor health bit.

Also cleaned up the AHRS debounce state variables (`ahrs_ok_streak`,
`ahrs_bad_streak`) which are no longer needed for gate decisions.
