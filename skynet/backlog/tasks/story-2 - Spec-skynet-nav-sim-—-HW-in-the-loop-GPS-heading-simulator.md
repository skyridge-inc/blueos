---
id: STORY-2
title: 'Spec: skynet nav sim — HW-in-the-loop GPS/heading simulator'
status: Done
assignee:
  - agent
created_date: '2026-04-11 22:26'
updated_date: '2026-04-11 22:26'
labels:
  - openspec
  - cli
  - mavlink
  - nav
  - sim
dependencies:
  - STORY-1
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Author the OpenSpec change `add-nav-sim` for a new `skynet nav sim` sub-action. The command runs a software-in-the-loop GPS/heading simulator on the BlueOS companion computer, downloads the current mission from a real Pixhawk Cube Orange+ via MAVLink, spawns at the first real waypoint (seq 1, after home), subscribes to `SERVO_OUTPUT_RAW` to read what the autopilot is commanding the skid-steer motors to do, runs a differential-drive kinematic model, and injects the resulting position and heading back as `GPS_INPUT` messages. The autopilot then flies the mission in AUTO mode against simulated sensor data with real IMUs, real EKF, and real motor-controller outputs in the loop.

Connection transport reuses `skynet.connection.mavlink_connection()` verbatim (same as `misc connect` and `nav upload`), so the BlueOS proxy is just `-d tcp:<host>:5760`.

Target vehicle: `FRAME_CLASS=2` skid-steer rover with `SERVO1_FUNCTION=73` (ThrottleLeft) and `SERVO3_FUNCTION=74` (ThrottleRight). The spec refuses any non-skid-steer frame at startup.

Specs authored under `openspec/changes/add-nav-sim/`:
- `proposal.md` — why & what changes
- `design.md` — GPS_INPUT vs HIL_GPS, skid-steer kinematic model, sidecar-based crash-safe param save/restore, mission-download state machine, arm handoff, stop conditions, rate/timing, risks
- `tasks.md` — implementation checklist for the future `/opsx:apply add-nav-sim` pass
- `specs/provisioning-cli/spec.md` — ADDED Requirement: `nav sim` Command
- `specs/mission-download/spec.md` — NEW capability: `download_mission()` + `MissionDownloadError`
- `specs/gps-simulator/spec.md` — NEW capability: `SkidSteerModel`, `ServoNormalizer`, `SimParamContext`, `GpsInputEmitter`, `StopWatcher`, Verification Harness Expectations

Validated with `openspec validate add-nav-sim --strict`.

Implementation is intentionally deferred — this story captures specs only. A follow-up `/opsx:apply add-nav-sim` session will execute `tasks.md`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 OpenSpec change `add-nav-sim` exists with proposal, design, tasks, and three spec deltas
- [x] #2 `openspec validate add-nav-sim --strict` passes
- [x] #3 Spec requires reuse of `skynet.connection.mavlink_connection()` (same transport as `misc connect` and `nav upload`)
- [x] #4 Spec requires a skid-steer kinematic model driven by SERVO_OUTPUT_RAW with refusal on any non-skid-steer frame
- [x] #5 Spec requires GPS_INPUT emission with nonzero yaw centidegrees (yaw floor of 1 cdeg) and fix_type=3
- [x] #6 Spec requires crash-safe param save/restore via a sidecar `.param` file under `~/.config/skynet/sim_restore_<slug>.param`
- [x] #7 Spec requires stop on DISARM (after observed-armed latch) and on MISSION_ITEM_REACHED for the final seq
- [x] #8 Spec enumerates six verification approaches (pure unit, mocked MAVLink, CLI, SITL bench, real-hw bench, crash-recovery drill)
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Authored OpenSpec change `add-nav-sim` covering the new `skynet nav sim` sub-action — a software-in-the-loop GPS/heading simulator for ArduRover skid-steer with a real Pixhawk Cube Orange+ in the loop.

**Artifacts created** (all under `openspec/changes/add-nav-sim/`):
- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/provisioning-cli/spec.md` — ADDED Requirement: `nav sim` Command with 10 scenarios (USB + BlueOS TCP, dry-run, confirmation, frame refusal, empty mission, leftover sidecar, start-seq, DISARM stop, mission-complete stop, SERVO stream missing).
- `specs/mission-download/spec.md` — NEW capability: `download_mission(conn, timeout)` implementing MISSION_REQUEST_LIST → MISSION_COUNT → MISSION_REQUEST_INT → MISSION_ITEM_INT → MISSION_ACK state machine with one-retry-per-item policy. Returns `[home, wp1...wpN]` matching `read_waypoints(include_home=True)` convention. Plus `MissionDownloadError` exception.
- `specs/gps-simulator/spec.md` — NEW capability with five requirements: `SkidSteerModel` (pure kinematic), `ServoNormalizer` (PWM → [-1,+1] via SERVOn_MIN/TRIM/MAX), `SimParamContext` (crash-safe sidecar save/restore), `GpsInputEmitter` (5 Hz GPS_INPUT with yaw floor), `StopWatcher` (DISARM with armed-latch + mission-complete + duration + SIGINT), and Verification Harness Expectations listing six required verification approaches.

**Key design decisions locked by the spec:**
1. **GPS_INPUT over HIL_GPS** — keeps the real IMU/rate loop in the loop.
2. **Skid-steer kinematic model** reusing `skynet.mission_planning.to_xy`/`to_latlon` for frame parity with the planner. Refuse any non-skid-steer frame at startup (`FRAME_CLASS != 2` or `SERVO1/3_FUNCTION != 73/74`).
3. **Max speed at full throttle**, default 2 mph (≈0.8941 m/s), overridable via `--ground-speed MPH`. Linear scaling from 0 at zero throttle.
4. **Crash-safe param save/restore** via a sidecar `.param` file written *before* any mutation. Leftover sidecar refuses startup with the exact `skynet misc write` recovery command. Required params: `GPS_TYPE=14`, `GPS_TYPE2=0`, `AHRS_EKF_TYPE=3`, `EK3_SRC1_POSXY=3`, `EK3_SRC1_VELXY=3`, `EK3_SRC1_POSZ=1`, `EK3_SRC1_YAW=2`.
5. **Start at seq 1** (first real waypoint), overridable via `--start-seq N`.
6. **No auto-arm** — operator arms in AUTO from GCS once the sim banner prints "GPS lock established".
7. **Stop on DISARM (with armed-latch to avoid pre-arm tripping) or MISSION_ITEM_REACHED for last seq**, plus optional `--duration` and SIGINT. Every exit path routes through the sidecar restore.
8. **Device string reuse** — `--device` / `--baud` identical to `misc connect`; BlueOS proxy is just `-d tcp:<host>:5760`.
9. **Yaw floor of 1 centidegree** — ArduPilot EKF3 treats `yaw=0` as "no yaw" and refuses to consume the yaw channel; we floor at 1 cdeg when true heading is 0.

**Verification approaches specified** (six items in the Verification Harness Expectations requirement):
1. Pure unit tests of the kinematic model and servo normalizer (no MAVLink).
2. Mocked-MAVLink tests for download state machine, param save/restore, GPS_INPUT emission, and stop watcher.
3. CLI tests via `typer.testing.CliRunner` (dry-run opens no connection, frame mismatch, leftover sidecar).
4. SITL bench verification (manual): ArduRover SITL + `nav sim` against a 4-point 20m square, track within 2 m after 10 s.
5. Real-hardware bench verification (manual): Pixhawk Cube Orange+ with RTK unplugged, BlueOS proxy, 4-point square, verify Mission Planner position indicator walks the square, `.bin` log shows GPS tracking POS within 0.5 m, AHRS.Yaw within 2°, mission-complete message, sidecar gone after disarm.
6. Crash-recovery drill (manual): SIGKILL mid-run, verify sidecar survives with originals, recover via `skynet misc write`, verify next run refuses to start until sidecar is removed.

**Validation:** `openspec validate add-nav-sim --strict` → `Change 'add-nav-sim' is valid`.

Implementation is intentionally deferred. Run `/opsx:apply add-nav-sim` to start the build.
<!-- SECTION:FINAL_SUMMARY:END -->
