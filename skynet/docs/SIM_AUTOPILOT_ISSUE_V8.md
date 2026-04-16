# Sim runs but rover never moves — V8 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V7.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1715 lines, ~34 s runtime)
Autopilot log: operator paste (`22:25:32 → 22:26:00`)

## TL;DR — engagement gate race: EKF goes healthy BEFORE arm detected

V7 fix (remove AHRS gate) worked — `EKF healthy` banner fires at
`t=10.7 s`. But the sim doesn't detect arming until `t=13.7 s`.
Since the engagement gate only fires on the *first* healthy
observation (`not ekf_healthy_banner_printed`), by the time `holding`
becomes True the gate has already been consumed. The HOLD→AUTO
transition **never fires**, and the sim stays in HOLD for the entire
34 s session.

```
t= 10.7  EKF healthy (flags=831). AUTO mode can now drive    ← banner, holding=False
t= 13.7  GPS lock established. Autopilot is armed.           ← armed, holding→True
          Forced mode=HOLD. Switching to AUTO once EKF...     ← but gate already consumed!
t= 33.6  mode=HOLD (entire remaining session)
```

---

### Root cause — `ekf_healthy_banner_printed` is a one-shot latch

The engagement code in the EKF_STATUS_REPORT handler:

```python
if healthy and not ekf_healthy_banner_printed:
    ekf_healthy_banner_printed = True
    if holding and not nav_engaged:
        # ... transition HOLD → AUTO
```

The `if holding` guard is nested inside the one-shot `not
ekf_healthy_banner_printed` check. Once the banner fires (at
t=10.7 s, when `holding=False`), `ekf_healthy_banner_printed`
latches True and the inner block never executes again — even when
`holding` later becomes True.

The V3 design assumed the sequence was always:
1. User arms in AUTO → sim detects arm → forces HOLD → `holding=True`
2. EKF goes healthy → `holding and not nav_engaged` → transition

But in V8 the sequence was reversed:
1. EKF goes healthy → banner fires, `holding=False` → no transition
2. User arms → `holding=True` → too late, banner already consumed

This reversal happens when:
- The user arms in MANUAL (not AUTO) — the sim only detects arming
  from the HEARTBEAT armed bit, not from the flight mode
- The autopilot achieves EKF healthy faster than the user switches
  from MANUAL to AUTO/HOLD

---

### V8 improvements observed (V4–V7 fixes validated)

- **Mission upload retry** (V4): first upload failed with
  `MAV_MISSION_RESULT=15` at seq 3, retried successfully, verified
  5 items.
- **VISO late-param write** (V4): `Applied late sim params:
  VISO_DELAY_MS, VISO_POS_M_NSE, VISO_YAW_M_NSE` — first time
  this succeeded.
- **Only 1 autopilot boot** — no spontaneous reboot after mission
  upload.
- **EKF healthy banner** (V7): fired at t=10.7 s without waiting for
  AHRS.

---

## Fix implemented

**Decouple the HOLD→AUTO transition from the one-shot banner.**

The transition now runs on *every* EKF_STATUS_REPORT where `healthy`
is true AND `holding and not nav_engaged`, not just the first one.
The banner itself remains one-shot (no need to spam it). This way:

- If EKF goes healthy *before* arming: banner fires at first
  healthy, transition waits. When arm is detected → `holding=True`,
  next EKF_STATUS_REPORT tick (within 1 s at 1 Hz) fires the
  transition.
- If EKF goes healthy *after* arming (the V3-era flow): both
  conditions are true on the same tick, transition fires immediately
  as before.
