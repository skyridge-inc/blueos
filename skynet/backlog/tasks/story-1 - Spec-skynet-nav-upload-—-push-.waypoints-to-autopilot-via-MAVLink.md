---
id: STORY-1
title: 'Spec: skynet nav upload — push .waypoints to autopilot via MAVLink'
status: Done
assignee:
  - agent
created_date: '2026-04-11 21:17'
updated_date: '2026-04-11 21:17'
labels:
  - openspec
  - cli
  - mavlink
  - nav
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a `skynet nav upload` sub-action that uploads a QGC WPL 110 `.waypoints` file (e.g. `./output/700_long_mower1.waypoints`) to a Pixhawk Cube Orange+ running ArduPilot Rover. The command reuses the existing `skynet.connection.mavlink_connection()` context manager — the exact same transport used by `skynet misc connect` — so pointing at the BlueOS MAVLink proxy is just `-d tcp:<host>:5760`, and USB serial still works at `/dev/ttyACM0`.

Specs authored under `openspec/changes/add-nav-upload/`:
- `proposal.md` — why & what changes
- `design.md` — MISSION_ITEM_INT, state-machine rationale, retry policy, reuse of `mavlink_connection`
- `tasks.md` — implementation checklist
- `specs/provisioning-cli/spec.md` — ADDED `nav upload` Command requirement
- `specs/mission-planning/spec.md` — ADDED QGC WPL 110 Waypoint Input requirement (read_waypoints include_home)
- `specs/mission-upload/spec.md` — NEW capability: upload_mission + MissionUploadError

Validated with `openspec validate add-nav-upload --strict`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Openspec change `add-nav-upload` exists with proposal, design, tasks, and spec deltas
- [x] #2 `openspec validate add-nav-upload --strict` passes
- [x] #3 Spec requires reuse of `skynet.connection.mavlink_connection()` (same transport as `misc connect`)
- [x] #4 Spec covers both USB serial and BlueOS TCP proxy device strings
- [x] #5 Spec covers MAVLink mission-upload state machine (MISSION_COUNT → MISSION_REQUEST_INT → MISSION_ITEM_INT → MISSION_ACK) with retry and error mapping
- [x] #6 Spec extends `read_waypoints` with `include_home=True` so seq 0 is home
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Authored OpenSpec change `add-nav-upload` covering the new `skynet nav upload` sub-action.

**Artifacts created** (all under `openspec/changes/add-nav-upload/`):
- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/provisioning-cli/spec.md` — ADDED Requirement: `nav upload` Command (USB serial + BlueOS TCP proxy scenarios, dry-run, confirmation, error paths)
- `specs/mission-planning/spec.md` — ADDED Requirement: QGC WPL 110 Waypoint Input (extends `read_waypoints` with `include_home=True` so seq 0 = home for upload)
- `specs/mission-upload/spec.md` — NEW capability defining `upload_mission(conn, items, progress_callback, timeout)` and `MissionUploadError`

**Key design choices locked in the spec:**
1. Reuse `skynet.connection.mavlink_connection()` verbatim — no second transport. Device string syntax identical to `misc connect`, so the BlueOS proxy is `-d tcp:<host>:5760`.
2. Use `MISSION_ITEM_INT` with int32-scaled lat/lon (preserves 8-decimal precision from the QGC WPL 110 file) and `MAV_FRAME_GLOBAL_RELATIVE_ALT`, command 16.
3. Full MAVLink mission-upload state machine (MISSION_COUNT → MISSION_REQUEST(_INT) → MISSION_ITEM_INT → MISSION_ACK). Accept both legacy `MISSION_REQUEST` and `MISSION_REQUEST_INT`.
4. Retry policy: one resend per item on timeout, then `MissionUploadError`. Non-ACCEPTED ack fails immediately with seq + numeric result.
5. Home row at index 0 is always sent. `MISSION_COUNT` implicitly replaces existing mission — no `MISSION_CLEAR_ALL`.
6. CLI options mirror `write`/`sync`/`config upload`: `--device`, `--baud`, `--dry-run`, `--yes`. `MissionUploadError` maps to red stderr + non-zero exit.

**Validation:** `openspec validate add-nav-upload --strict` → `Change 'add-nav-upload' is valid`.

Implementation is intentionally deferred — this story captures the spec only. Run `/opsx:apply add-nav-upload` to start the build.
<!-- SECTION:FINAL_SUMMARY:END -->
