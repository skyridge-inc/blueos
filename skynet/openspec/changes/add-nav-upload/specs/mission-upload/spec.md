## ADDED Requirements

### Requirement: upload_mission Function
The system SHALL provide `upload_mission(conn, items, progress_callback=None,
timeout=5.0)` in `skynet.mission_upload`. `conn` is an open
`pymavlink.mavutil.mavlink_connection` as produced by
`skynet.connection.mavlink_connection()`. `items` is a non-empty list of
`(lat, lon)` tuples where index 0 is the home position and indices 1..N
are mission waypoints.

The function SHALL perform the MAVLink mission-upload protocol with
`mission_type = MAV_MISSION_TYPE_MISSION`:

1. Send `MISSION_COUNT` with `count = len(items)`.
2. Repeatedly wait (up to `timeout` seconds) for a `MISSION_REQUEST_INT`
   or legacy `MISSION_REQUEST` message from the autopilot, and reply with
   a `MISSION_ITEM_INT` for the requested seq, using:
   - `frame = MAV_FRAME_GLOBAL_RELATIVE_ALT`
   - `command = MAV_CMD_NAV_WAYPOINT` (16)
   - `current = 1` when `seq == 0`, else `0`
   - `autocontinue = 1`
   - `param1..param4 = 0`
   - `x = round(lat * 1e7)` (int32 scaled)
   - `y = round(lon * 1e7)` (int32 scaled)
   - `z = 0.0`
3. After the final item, wait for a `MISSION_ACK` and check its result.

The function SHALL raise `MissionUploadError` (a subclass of
`MowerProvisionerError`) when any of the following occur:

- `items` is empty.
- The autopilot sends `MISSION_ACK` with a result that is not
  `MAV_MISSION_ACCEPTED`. The error message SHALL include the numeric
  result and the last seq requested.
- A `MISSION_REQUEST(_INT)` is not received within `timeout` seconds for
  the same seq on two consecutive tries (single retry of the current
  item).
- The autopilot requests a seq outside `0..len(items)-1`.

When `progress_callback` is provided, it SHALL be called as
`progress_callback(sent, total)` after each item successfully sent, with
`total = len(items)`. The function SHALL NOT send `MISSION_CLEAR_ALL`
before uploading; sending `MISSION_COUNT` is sufficient to replace the
existing mission.

#### Scenario: Successful upload
- **WHEN** `upload_mission(conn, [home, wp1, wp2])` is called against a
  mock connection that emits `MISSION_REQUEST_INT` for seqs 0, 1, 2 and
  then `MISSION_ACK(MAV_MISSION_ACCEPTED)`
- **THEN** exactly three `MISSION_ITEM_INT` messages are sent in seq
  order
- **AND** each uses frame `MAV_FRAME_GLOBAL_RELATIVE_ALT`, command 16,
  and int32-scaled lat/lon
- **AND** the function returns without raising

#### Scenario: Autopilot rejects mission
- **WHEN** the mock autopilot responds with `MISSION_ACK` whose result is
  `MAV_MISSION_ERROR`
- **THEN** `upload_mission` raises `MissionUploadError`
- **AND** the message contains the numeric result and the failing seq

#### Scenario: Legacy MISSION_REQUEST is accepted
- **WHEN** the mock autopilot emits float `MISSION_REQUEST` instead of
  `MISSION_REQUEST_INT` for a given seq
- **THEN** the upload still completes and the item is sent as
  `MISSION_ITEM_INT`

#### Scenario: Retry on single timeout
- **WHEN** the autopilot fails to request seq 1 within `timeout`, then
  requests it after a resend
- **THEN** `upload_mission` resends the current item once and the upload
  completes

#### Scenario: Second timeout fails
- **WHEN** the autopilot never requests seq 1 across two consecutive
  `timeout` windows
- **THEN** `upload_mission` raises `MissionUploadError` identifying seq 1

#### Scenario: Progress callback invoked
- **WHEN** `upload_mission` is called with a `progress_callback`
- **THEN** the callback is invoked `len(items)` times with
  monotonically increasing `sent` values ending at `len(items)`

#### Scenario: Empty items rejected
- **WHEN** `upload_mission(conn, [])` is called
- **THEN** `MissionUploadError` is raised before any MAVLink message is
  sent

### Requirement: MissionUploadError Exception
The system SHALL define `MissionUploadError` in `skynet.exceptions` as a
subclass of `MowerProvisionerError`. All mission-upload failures SHALL be
surfaced via this type so the CLI can map them uniformly to a red stderr
message and a non-zero exit status.

#### Scenario: Exception hierarchy
- **WHEN** `MissionUploadError("x")` is raised
- **THEN** it is an instance of `MowerProvisionerError`
