# Sim runs but rover never moves — V10 analysis

Date: 2026-04-15 (follow-up to `SIM_AUTOPILOT_ISSUE_V9.md`)
Firmware: ArduRover 4.6.3 (`3fc7011a`) on CubeOrangePlus
Sim log: `/tmp/sim.log` (1919 lines, ~56 s runtime)
Autopilot log: operator paste (`23:08:30 → 23:10:20`)

## TL;DR — Yaw sweep confirms heading injection works; spawn geometry is degenerate

### What worked

1. **Heading injection is live.** The yaw sweep fired at t=20.5 s
   and the rover **visibly rotated** in QGC — confirming GPS_INPUT
   yaw → EKF → QGC heading display pipeline is functional.

2. **Servo output stayed L=R=1500 throughout** (767 neutral lines,
   zero differential). The autopilot did NOT attempt to correct the
   heading rotation via differential motor output, confirming the
   motor output path is **completely dead** — the firmware is not
   commanding ANY steering or throttle in AUTO mode on this mission.

3. **All V4–V8 gates worked correctly.** EKF healthy at t=10.5 s,
   engagement at t=10.5 s (no race), mission seq=1 with
   `wp_dist=2 m target_bearing=0°`.

### Spawn position analysis

The operator reported the spawn did not appear 3 m south of WP1 in
QGC. The math is correct:

```
WP1 lat (from mission):  40.30073620
Spawn lat (computed):     40.30070925
Delta:                    0.00002695° × 111320 m/° = 3.00 m south
```

The `wp_dist=2 m` in `NAV_CONTROLLER_OUTPUT` is integer truncation
of ~2.7–3.0 m (the EKF's position estimate includes small noise).
The visual appearance in QGC is indistinguishable at typical zoom
because 3 m is ~3 pixels at neighbourhood zoom levels.

### Spawn geometry is degenerate for the L1 controller

The perpendicular-offset strategy (V9) aimed to create non-zero
cross-track error. It failed because of a fundamental constraint:

- **HOME is always set from the first GPS_INPUT fix** — which IS
  the spawn position.
- The L1 controller's track for WP1 goes from the **previous
  mission item** (HOME, seq 0) to WP1 (seq 1).
- Since HOME = spawn, the rover starts **exactly on the
  HOME→WP1 track** regardless of where we place the spawn.
- Result: `xtrack_err=0.00 m` — no cross-track correction ever
  computed.

`target_bearing=0°` (WP1 is due north of spawn) with
`nav_bearing=0°` and `xtrack_err=0.00 m` is exactly the same
degenerate L1 state seen in V4–V9, where the non-pivot AR_WPNav
branch produces zero throttle.

## Fix — place spawn EAST of WP1 (cross-track from HOME→WP1 line)

The correct approach is:

1. Place spawn laterally offset from the HOME→WP1 line, not along
   it. Since HOME = spawn, this means we must place spawn such that
   **WP1 is not directly ahead**. With spawn east of the Home→WP1
   track, the rover has both a wp_dist > 0 AND a cross-track error,
   forcing the L1 controller to compute a real correction.

2. Concretely: offset spawn 3 m to the EAST (or WEST) of WP1
   rather than south. If WP1→WP2 goes roughly north, then the
   HOME→WP1 track would have non-zero xtrack from the start.

However, since HOME = spawn, the HOME→WP1 track ALWAYS starts at
the spawn — so xtrack at the spawn point is zero by definition.
The cross-track only becomes non-zero as the rover progresses
along the track past the HOME endpoint.

**The real fix**: offset spawn along WP1→WP2 direction (keeping
the V4 "behind" approach) but at a larger distance (10+ m) so the
L1 controller has a meaningful segment to follow, AND use a heading
that is NOT aligned with the track. This forces both a turning
correction (non-zero yaw error) and throttle to reach WP1.
